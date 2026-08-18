import secrets

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from apps.content.models import PlatformContent
from apps.identity.permissions import (
    CanManageCampaigns,
    CanManageLeads,
    CanManagePublishing,
    CanReadCampaigns,
    CanReadLeads,
)
from apps.platforms.connection_status import connection_summary
from integrations.platforms.runtime import get_social_provider_runtime
from integrations.sources.base import SourceAdapterError

from .candidate_imports import CandidateImportInvalid, import_candidate_list
from .discovery import DiscoveryAlreadyRunning, run_discovery
from .enrichment import (
    CandidateEnrichmentRequired,
    CandidateReviewRequired,
    add_candidate_to_follow_up,
    enrichment_payload,
    prepare_candidate_enrichment,
)
from .models import (
    ChannelPackage,
    Contact,
    DiscoveryCandidate,
    DiscoveryProfile,
    DiscoveryRun,
    FieldProvenance,
    FollowUp,
    GoogleMapsDiscoveryConfig,
    GrowthMission,
    GrowthPublishBatch,
    InboundLead,
    IntentSignal,
    MissionEntityLink,
    MetricReceipt,
    MarketCountryProfile,
    OpportunityReview,
    OutreachDraft,
    ReactivationRecord,
    CRMHandoff,
    TargetAccount,
    TradeDatasetSnapshot,
    TradeSyncRun,
)
from .mission_services import link_mission_entity
from integrations.secrets import encrypt_secret
from .maps_discovery import (
    MapsDiscoveryMissingKey,
    MapsDiscoveryNotEnabled,
    probe_maps_connection,
    run_maps_discovery,
)
from .website_enrichment import build_website_transport, prepare_website_enrichment
from .lead_intent import record_lead_visit
from .inbound_rfq import record_inbound_rfq, resolve_website_organization
from .webhook_auth import verify_webhook_signature
from .promotion_plan import (
    approve_promotion_plan,
    clear_promotion_plan_approval,
    promotion_plan_preview,
    promotion_plan_status,
)

from .manual_imports import import_manual_opportunity
from .market_pilots import market_pilot_summary, market_profiles_for
from .serializers import (
    ChannelPackageBatchApproveSerializer,
    FourChannelManualExportSerializer,
    ChannelPackageSerializer,
    CandidateListImportResultSerializer,
    CandidateListImportSerializer,
    CandidateEnrichmentResultSerializer,
    DiscoveryCandidateReviewResultSerializer,
    DiscoveryCandidateReviewSerializer,
    DiscoveryCandidateSerializer,
    EnrichmentCandidateSerializer,
    ContactSerializer,
    DiscoveryProfileUpdateSerializer,
    DiscoveryRunResultSerializer,
    DiscoverySummarySerializer,
    FieldProvenanceSerializer,
    FollowUpSerializer,
    GoogleMapsDiscoveryConfigResponseSerializer,
    GoogleMapsDiscoveryConfigUpdateSerializer,
    GoogleMapsDiscoveryRunResultSerializer,
    LeadVisitRequestSerializer,
    LeadVisitResultSerializer,
    InboundRfqRequestSerializer,
    InboundRfqResultSerializer,
    GrowthPublishBatchSerializer,
    GrowthErrorSerializer,
    GrowthValidationErrorSerializer,
    InboundLeadSerializer,
    IntentSignalSerializer,
    ManualOpportunityImportResponseSerializer,
    ManualOpportunityImportSerializer,
    MarketWatchCreateSerializer,
    MetricReceiptSerializer,
    OpportunityReviewCreateSerializer,
    OpportunityReviewSerializer,
    OutreachDraftSerializer,
    ReactivationCreateSerializer,
    CRMHandoffCreateSerializer,
    CRMHandoffSerializer,
    PublishBatchCreateSerializer,
    TargetAccountSerializer,
    TradeDatasetSnapshotSerializer,
    TradeIndicatorResponseSerializer,
    TradeSnapshotListSerializer,
    TradeSyncRequestSerializer,
    TradeSyncResponseSerializer,
)
from .manual_export import FourChannelExportNotReady, build_four_channel_export
from .reactivation import (
    LegalRelationshipRequired,
    ReactivationBlocked,
    ReactivationEvidenceInsufficient,
    approve_reactivation_draft,
    create_reactivation_draft,
    reactivation_payload,
    select_for_reactivation,
)
from .publishing import (
    PublishBatchConflict,
    PublishPackageSelectionInvalid,
    create_publish_batch,
    retry_failed_items,
)
from .services import (
    ChannelPackageBatchInvalid,
    ChannelPackagePreparationBlocked,
    PackageReviewRequired,
    prepare_channel_package_from_platform_content,
    OpportunityHandoffBlocked,
    add_to_follow_up,
    approve_channel_package,
    approve_channel_package_batch,
    create_outreach_draft,
    create_mock_crm_handoff,
    export_manual_channel_package,
    verify_company_fact,
    record_opportunity_review,
)
from .trade_data import sync_trade_data, trade_indicators
from .trade_runtime import (
    COUNTRY_REPORTER_CODES,
    TradeProviderConfigurationRequired,
    trade_source_runtime,
)
from integrations.sources.comtrade import TradeQuery


def _webhook_rate_limited(request, prefix, limit=30, window_seconds=60):
    ip = request.META.get("REMOTE_ADDR", "unknown")
    key = f"webhook-rate:{prefix}:{ip}"
    try:
        current = cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window_seconds)
        current = 1
    return current > limit


def connector_readiness(organization):
    results = []
    runtime = get_social_provider_runtime()
    for channel in ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK", "YOUTUBE"):
        summary = connection_summary(
            organization=organization, platform_code=channel,
        )
        provider = runtime.readiness.get(channel)
        status = summary.status
        connection_label = summary.connection_label
        recovery_action = summary.recovery_action
        if status == "NOT_CONNECTED" and provider is not None:
            status = provider.status
            if status == "CONFIGURATION_REQUIRED":
                connection_label = "未配置"
                recovery_action = "连接账号"
            elif status == "WAITING_PLATFORM_REVIEW":
                connection_label = "等待平台审核"
                recovery_action = ""
            elif status == "PRIVATE_ONLY":
                connection_label = "仅私密发布"
                recovery_action = ""
        results.append({
            "channel": channel,
            "status": status,
            "connection_label": connection_label,
            "recovery_action": recovery_action,
            "mode": summary.mode,
            "account_id": summary.account_id,
            "publication_mode": provider.publication_mode if provider else "UNAVAILABLE",
        })
    return results


def discovery_profile_for(organization):
    profile, _ = DiscoveryProfile.objects.get_or_create(organization=organization)
    return profile


def discovery_run_payload(run):
    count = run.created_signal_count
    message = (
        f"发现 {count} 条新采购信号，等待你审核。"
        if run.status == DiscoveryRun.Status.SUCCEEDED
        else "自动查找暂时未完成，请稍后重试。"
    )
    return {
        "status": run.status,
        "finished_at": run.finished_at,
        "found_count": run.fetched_count,
        "new_company_count": run.created_account_count,
        "new_signal_count": count,
        "duplicate_count": run.duplicate_count,
        "skipped_count": run.skipped_count,
        "message": message,
    }


def discovery_summary(profile):
    last_run = profile.runs.exclude(status=DiscoveryRun.Status.RUNNING).first()
    candidates = profile.organization.discoverycandidate_set.filter(
        status=DiscoveryCandidate.Status.PENDING_REVIEW,
    )[:20]
    enrichment_candidates = profile.organization.discoverycandidate_set.filter(
        status=DiscoveryCandidate.Status.ACCEPTED,
    ).select_related("enrichment_snapshot")[:20]
    return {
        "enabled": profile.enabled,
        "source_label": "欧盟与英国官方采购数据",
        "schedule_label": "每天自动查找" if profile.enabled else "已暂停自动查找",
        "product_scope_label": "齿轮、传动与驱动部件",
        "next_run_at": profile.next_run_at,
        "last_run": discovery_run_payload(last_run) if last_run else None,
        "candidate_count": profile.organization.discoverycandidate_set.filter(
            status=DiscoveryCandidate.Status.PENDING_REVIEW,
        ).count(),
        "candidates": DiscoveryCandidateSerializer(candidates, many=True).data,
        "enrichment_candidates": EnrichmentCandidateSerializer(
            enrichment_candidates, many=True,
        ).data,
        "available_sources": [
            {"code": "TED", "label": "TED 欧盟采购公告", "status": "ACTIVE"},
            {
                "code": "UK_CONTRACTS_FINDER",
                "label": "英国 Contracts Finder",
                "status": "ACTIVE",
            },
            {
                "code": "GOOGLE_PLACES",
                "label": "Google Maps 官方企业发现",
                "status": "KEY_REQUIRED",
            },
        ],
    }


class GrowthWorkspaceView(APIView):
    permission_classes = [CanReadLeads]

    @extend_schema(tags=["Growth workspace"])
    def get(self, request):
        organization = request.organization
        limit, offset = self._pagination(request)
        payload = self._workspace_payload(organization, limit=limit, offset=offset)
        return Response(payload)

    @staticmethod
    def _pagination(request):
        try:
            limit = int(request.query_params.get("limit", 500))
            offset = int(request.query_params.get("offset", 0))
        except (TypeError, ValueError):
            raise ValidationError("分页参数必须是整数。")
        return max(1, min(limit, 500)), max(0, offset)

    def _workspace_payload(self, organization, *, limit, offset):
        accounts = list(
            TargetAccount.objects.filter(organization=organization).order_by("-created_at", "-id")
        )
        all_signals = list(IntentSignal.objects.filter(organization=organization))
        page_accounts = accounts[offset:offset + limit]
        return {
            "target_accounts": TargetAccountSerializer(page_accounts, many=True).data,
            "accounts_total": len(accounts),
            "accounts_has_more": offset + limit < len(accounts),
            "accounts_offset": offset,
            "contacts": ContactSerializer(
                Contact.objects.filter(organization=organization)[:limit], many=True,
            ).data,
            "intent_signals": IntentSignalSerializer(
                all_signals[:limit], many=True,
            ).data,
            "inbound_leads": InboundLeadSerializer(
                InboundLead.objects.filter(organization=organization)[:limit], many=True,
            ).data,
            "follow_ups": FollowUpSerializer(
                FollowUp.objects.filter(organization=organization)[:limit], many=True,
            ).data,
            "outreach_drafts": OutreachDraftSerializer(
                OutreachDraft.objects.filter(organization=organization)
                .order_by("-created_at", "-id")[:limit], many=True,
            ).data,
            "reactivations": [
                reactivation_payload(record)
                for record in ReactivationRecord.objects.filter(organization=organization)
                .select_related("account", "draft")
                .prefetch_related("events", "account__intent_signals")[:limit]
            ],
            "opportunity_reviews": OpportunityReviewSerializer(
                OpportunityReview.objects.filter(organization=organization)[:limit], many=True,
            ).data,
            "crm_handoffs": CRMHandoffSerializer(
                CRMHandoff.objects.filter(organization=organization)[:limit], many=True,
            ).data,
            "channel_packages": ChannelPackageSerializer(
                ChannelPackage.objects.filter(organization=organization)
                .order_by("channel", "id")[:limit], many=True,
            ).data,
            "publish_batches": GrowthPublishBatchSerializer(
                GrowthPublishBatch.objects.filter(organization=organization)
                .prefetch_related("items")[:5],
                many=True,
            ).data,
            "metric_receipts": MetricReceiptSerializer(
                MetricReceipt.objects.filter(organization=organization)
                .order_by("-created_at", "-id")[:limit], many=True,
            ).data,
            "field_provenance": FieldProvenanceSerializer(
                FieldProvenance.objects.filter(organization=organization)[:limit], many=True,
            ).data,
            "connectors": connector_readiness(organization),
            "discovery": discovery_summary(discovery_profile_for(organization)),
            "market_pilots": market_pilot_summary(
                signals=all_signals,
                accounts=accounts,
                profiles=market_profiles_for(organization),
            ),
            "promotion_plan": promotion_plan_preview(organization),
            "promotion_plan_approval": promotion_plan_status(organization),
        }


class PromotionPlanApproveView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(
        tags=["Growth workspace"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        approve_promotion_plan(organization=request.organization, actor=request.user)
        return Response(promotion_plan_status(request.organization))


class PromotionPlanRegenerateView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(
        tags=["Growth workspace"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        clear_promotion_plan_approval(organization=request.organization)
        return Response(promotion_plan_status(request.organization))


class LeadVisitView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Growth workspace"],
        request=LeadVisitRequestSerializer,
        responses={
            200: LeadVisitResultSerializer,
            403: GrowthValidationErrorSerializer,
        },
    )
    def post(self, request):
        if _webhook_rate_limited(request, "lead-visits"):
            return Response({
                "code": "RATE_LIMITED",
                "message": "访问回传过于频繁，请稍后再试。",
                "recovery_action": "稍后重试。",
            }, status=429)
        expected = getattr(settings, "LEAD_VISIT_WEBHOOK_SECRET", "")
        provided = request.headers.get("X-Lead-Visit-Secret", "")
        if not expected or not secrets.compare_digest(expected, provided):
            return Response({
                "code": "INVALID_WEBHOOK_SECRET",
                "message": "无效的网站回传密钥。",
                "recovery_action": "请在网站端配置正确的回传密钥。",
            }, status=403)
        serializer = LeadVisitRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        candidate = record_lead_visit(**serializer.validated_data)
        if candidate is None:
            return Response({
                "code": "LEAD_NOT_FOUND",
                "message": "找不到对应的客户记录。",
                "recovery_action": "确认 lead_id 是否有效。",
            }, status=404)
        return Response({
            "lead_id": str(candidate.id),
            "intent_score": candidate.intent_score,
            "intent_breakdown": candidate.intent_breakdown,
        })


class InboundRfqView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["Growth workspace"],
        request=InboundRfqRequestSerializer,
        responses={201: InboundRfqResultSerializer, 403: GrowthValidationErrorSerializer},
    )
    def post(self, request):
        if _webhook_rate_limited(request, "inbound-rfq"):
            return Response({
                "code": "RATE_LIMITED",
                "message": "询盘提交过于频繁，请稍后再试。",
                "recovery_action": "稍后重试。",
            }, status=429)
        secret = getattr(settings, "RFQ_WEBHOOK_SECRET", "")
        timestamp = request.headers.get("X-Timestamp", "")
        signature = request.headers.get("X-Signature", "")
        if not verify_webhook_signature(
            secret=secret,
            timestamp=timestamp,
            signature=signature,
            payload=request.data,
        ):
            return Response({
                "code": "INVALID_WEBHOOK_SIGNATURE",
                "message": "询盘签名无效或已过期。",
                "recovery_action": "请使用正确的 HMAC 签名和时间戳重试。",
            }, status=403)
        serializer = InboundRfqRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organization = resolve_website_organization(
            serializer.validated_data.get("lead_id", ""),
        )
        if organization is None:
            return Response({
                "code": "NO_ORGANIZATION",
                "message": "无法确定询盘所属组织。",
                "recovery_action": "请配置网站对应的组织标识。",
            }, status=400)
        result = record_inbound_rfq(organization=organization, **serializer.validated_data)
        return Response(result, status=201)


class DiscoveryRunView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=None,
        responses={
            200: DiscoveryRunResultSerializer,
            409: GrowthErrorSerializer,
            503: GrowthErrorSerializer,
        },
    )
    def post(self, request):
        profile = discovery_profile_for(request.organization)
        try:
            run = run_discovery(profile.id, trigger=DiscoveryRun.Trigger.MANUAL)
        except DiscoveryAlreadyRunning:
            return Response({
                "code": "DISCOVERY_ALREADY_RUNNING",
                "message": "正在查找客户，请等待当前任务完成。",
                "recovery_action": "稍后刷新客户机会。",
            }, status=409)
        except SourceAdapterError:
            return Response({
                "code": "DISCOVERY_SOURCE_UNAVAILABLE",
                "message": "官方数据源暂时不可用。",
                "recovery_action": "请稍后再次点击立即查找。",
            }, status=503)
        return Response(discovery_run_payload(run))


class CandidateListImportView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=CandidateListImportSerializer,
        responses={200: CandidateListImportResultSerializer, 201: CandidateListImportResultSerializer},
    )
    def post(self, request):
        serializer = CandidateListImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = import_candidate_list(
                organization=request.organization,
                import_format=serializer.validated_data["format"],
                content=serializer.validated_data["content"],
                source_owner=serializer.validated_data["source_owner"],
                license_contract=serializer.validated_data["license_contract"],
                retention_days=serializer.validated_data["retention_days"],
                redistribution_allowed=serializer.validated_data["redistribution_allowed"],
            )
        except CandidateImportInvalid as error:
            return Response({"message": str(error)}, status=400)
        return Response(result, status=201 if result["created_count"] else 200)


class DiscoveryCandidateReviewView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=DiscoveryCandidateReviewSerializer,
        responses={200: DiscoveryCandidateReviewResultSerializer},
    )
    def post(self, request, candidate_id):
        serializer = DiscoveryCandidateReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            candidate = get_object_or_404(
                DiscoveryCandidate.objects.select_for_update(),
                id=candidate_id,
                organization=request.organization,
            )
            if candidate.status != DiscoveryCandidate.Status.PENDING_REVIEW:
                return Response({
                    "code": "CANDIDATE_ALREADY_REVIEWED",
                    "message": "这家公司已经完成核实。",
                    "recovery_action": "刷新候选列表查看最新状态。",
                }, status=409)
            accepted = serializer.validated_data["decision"] == "ACCEPT"
            candidate.status = (
                DiscoveryCandidate.Status.ACCEPTED
                if accepted else DiscoveryCandidate.Status.DISMISSED
            )
            candidate.review_note = serializer.validated_data["note"]
            candidate.reviewed_at = timezone.now()
            candidate.reviewed_by = request.user
            candidate.save(update_fields=[
                "status", "review_note", "reviewed_at", "reviewed_by", "updated_at",
            ])
        return Response({
            "id": str(candidate.id),
            "status": candidate.status,
            "status_label": "待补全公司资料" if accepted else "已忽略",
            "message": (
                "已加入公司资料补全，不会自动联系客户。"
                if accepted else "已忽略这家公司，不会进入后续处理。"
            ),
        })


class CandidateEnrichmentPrepareView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=None,
        responses={200: CandidateEnrichmentResultSerializer, 201: CandidateEnrichmentResultSerializer},
    )
    def post(self, request, candidate_id):
        candidate = get_object_or_404(
            DiscoveryCandidate,
            id=candidate_id,
            organization=request.organization,
        )
        try:
            snapshot, created = prepare_candidate_enrichment(candidate=candidate)
        except CandidateReviewRequired:
            return Response({
                "code": "CANDIDATE_REVIEW_REQUIRED",
                "message": "请先核实这家公司，再准备资料补全。",
                "recovery_action": "回到待核实公司并选择加入资料补全。",
            }, status=409)
        return Response(
            enrichment_payload(snapshot, created=created),
            status=201 if created else 200,
        )


class CandidateWebsiteEnrichmentView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=None,
        responses={
            200: CandidateEnrichmentResultSerializer,
            201: CandidateEnrichmentResultSerializer,
        },
    )
    def post(self, request, candidate_id):
        candidate = get_object_or_404(
            DiscoveryCandidate,
            id=candidate_id,
            organization=request.organization,
        )
        try:
            snapshot, created = prepare_website_enrichment(
                candidate,
                transport=build_website_transport(),
            )
        except CandidateReviewRequired:
            return Response({
                "code": "CANDIDATE_REVIEW_REQUIRED",
                "message": "请先核实这家公司，再读取官网补全。",
                "recovery_action": "回到待核实公司并选择加入资料补全。",
            }, status=409)
        except ValueError as error:
            return Response({
                "code": "WEBSITE_UNREADABLE",
                "message": str(error),
                "recovery_action": "这家公司没有官网或官网暂时无法读取，可稍后重试或改用名单事实。",
            }, status=422)
        return Response(
            enrichment_payload(snapshot, created=created),
            status=201 if created else 200,
        )


class CandidateEnrichmentFollowUpView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(tags=["Growth workspace"], request=None)
    def post(self, request, candidate_id):
        candidate = get_object_or_404(
            DiscoveryCandidate,
            id=candidate_id,
            organization=request.organization,
        )
        try:
            account, follow_up, created = add_candidate_to_follow_up(candidate=candidate)
        except CandidateEnrichmentRequired:
            return Response({
                "code": "CANDIDATE_ENRICHMENT_REQUIRED",
                "message": "请先准备公司资料，再加入跟进。",
                "recovery_action": "点击准备公司资料并人工检查已有事实与缺口。",
            }, status=409)
        return Response({
            "account_id": str(account.id),
            "follow_up_id": str(follow_up.id),
            "status": follow_up.status,
            "created": created,
            "message": "已加入人工跟进；没有生成采购意向，也没有联系客户。",
        }, status=201 if created else 200)


class MarketWatchView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"], request=None)
    def post(self, request, country_code):
        market_profiles_for(request.organization)
        market = get_object_or_404(
            MarketCountryProfile,
            organization=request.organization,
            country_code=country_code.upper(),
        )
        if not market.is_watched:
            market.is_watched = True
            market.save(update_fields=["is_watched", "updated_at"])
        return Response({
            "country_code": market.country_code,
            "is_watched": True,
            "message": "已加入观察市场。",
        })


class MarketWatchCreateView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"], request=MarketWatchCreateSerializer)
    @transaction.atomic
    def post(self, request):
        serializer = MarketWatchCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        existing = MarketCountryProfile.objects.select_for_update().filter(
            organization=request.organization,
            country_code=data["country_code"],
        ).first()
        created = existing is None or existing.is_demo or not existing.is_watched
        market = existing or MarketCountryProfile(
            organization=request.organization,
            country_code=data["country_code"],
            priority_order=MarketCountryProfile.objects.filter(organization=request.organization).count() + 100,
        )
        route_label = {
            "CUSTOMS_STRONG": "许可交易数据",
            "MIXED_ACQUISITION": "混合公开信号",
        }[data["path_family"]]
        market.country_label = data["country_label"]
        market.region = "OTHER"
        market.path_family = data["path_family"]
        market.suitable_industries = []
        market.data_availability_label = "待验证"
        market.evidence_note = "用户建立的观察市场，尚无样本证据。"
        market.recommended_action = "导入有许可的名单或公开线索，验证首批公司。"
        market.is_demo = False
        market.is_watched = True
        market.status = MarketCountryProfile.Status.OBSERVATION_POOL
        market.route = data["path_family"]
        market.route_label = route_label
        market.recommended_wave = "用户观察"
        market.source_types = []
        market.last_researched_at = timezone.localdate()
        market.scores = {}
        market.sample_quality = {}
        market.recommendation_reasons = []
        market.hold_reasons = ["尚未验证数据来源、样本质量和真实需求。"]
        market.save()
        return Response({
            "created": created,
            "market": {
                "country_code": market.country_code,
                "country_label": market.country_label,
                "status": market.status,
                "path_family": market.path_family,
                "route_label": market.route_label,
                "data_availability_label": market.data_availability_label,
                "evidence_note": market.evidence_note,
                "recommended_action": market.recommended_action,
                "is_demo": market.is_demo,
                "is_watched": market.is_watched,
                "scores": market.scores,
                "sample_quality": market.sample_quality,
                "recommendation_reasons": market.recommendation_reasons,
                "hold_reasons": market.hold_reasons,
            },
        }, status=201 if created else 200)


class TradeSyncView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(
        tags=["Growth workspace"],
        request=TradeSyncRequestSerializer,
        responses={200: TradeSyncResponseSerializer, 201: TradeSyncResponseSerializer},
    )
    def post(self, request):
        serializer = TradeSyncRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            source, mode = trade_source_runtime()
        except TradeProviderConfigurationRequired:
            return Response({
                "code": "CONFIGURATION_REQUIRED",
                "message": "公开贸易数据源尚未启用。",
                "recovery_action": "由管理员明确启用官方公共数据连接器；当前不会自动加载演示数据。",
            }, status=503)
        values = serializer.validated_data
        reporter_code = COUNTRY_REPORTER_CODES[values["country_code"]]
        results = []
        for partner_code in ("0", "156"):
            try:
                results.append(sync_trade_data(
                    organization=request.organization,
                    actor=request.user,
                    query=TradeQuery(
                        reporter_code=reporter_code,
                        partner_code=partner_code,
                        flow="M",
                        hs_codes=tuple(values["hs_codes"]),
                        periods=tuple(values["periods"]),
                    ),
                    source=source,
                ))
            except SourceAdapterError as error:
                return Response({
                    "code": error.code,
                    "message": "官方公开贸易数据同步失败。",
                    "recovery_action": "稍后重试；系统没有创建买家公司或采购意向。",
                }, status=502)
        runs = list(TradeSyncRun.objects.filter(
            organization=request.organization,
            id__in=[result.run_id for result in results],
        ))
        snapshot_ids = tuple(dict.fromkeys(
            snapshot_id for result in results for snapshot_id in result.snapshot_ids
        ))
        created_count = sum(run.created_snapshot_count for run in runs)
        payload = {
            "mode": mode,
            "is_demo": mode == "FIXTURE",
            "run_ids": [str(result.run_id) for result in results],
            "snapshot_ids": [str(value) for value in snapshot_ids],
            "created_snapshot_count": created_count,
            "reused_snapshot_count": sum(run.reused_snapshot_count for run in runs),
            "scope_warning": "宏观贸易仅用于市场判断，不是具体买家证据。",
        }
        return Response(payload, status=201 if created_count else 200)


class TradeSnapshotListView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Growth workspace"], responses={200: TradeSnapshotListSerializer})
    def get(self, request):
        queryset = TradeDatasetSnapshot.objects.filter(organization=request.organization)
        country_code = str(request.query_params.get("country_code", "")).upper()
        if country_code:
            reporter_code = COUNTRY_REPORTER_CODES.get(country_code)
            if reporter_code is None:
                return Response({"country_code": ["Unsupported reporter country."]}, status=400)
            queryset = queryset.filter(reporter_code=reporter_code)
        hs_codes = request.query_params.getlist("hs_code")
        if hs_codes:
            if any(len(value) not in {4, 6} or not value.isdigit() for value in hs_codes):
                return Response({"hs_code": ["Use four or six digit HS codes."]}, status=400)
            queryset = queryset.filter(hs_code__in=hs_codes)
        results = list(queryset[:100])
        return Response({
            "count": len(results),
            "results": TradeDatasetSnapshotSerializer(results, many=True).data,
        })


class TradeIndicatorView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Growth workspace"], responses={200: TradeIndicatorResponseSerializer})
    def get(self, request):
        country_code = str(request.query_params.get("country_code", "")).upper()
        reporter_code = COUNTRY_REPORTER_CODES.get(country_code)
        if reporter_code is None:
            return Response({"country_code": ["Unsupported reporter country."]}, status=400)
        hs_codes = tuple(request.query_params.getlist("hs_code") or ("848340", "848390"))
        periods = tuple(request.query_params.getlist("period"))
        try:
            query = TradeQuery(
                reporter_code=reporter_code,
                partner_code="0",
                flow="M",
                hs_codes=hs_codes,
                periods=periods,
            )
        except ValueError as error:
            return Response({"query": [str(error)]}, status=400)
        payload = trade_indicators(
            organization=request.organization,
            reporter_code=reporter_code,
            hs_codes=query.hs_codes,
            periods=query.periods,
        )
        payload["is_demo"] = bool(payload["evidence"]) and all(
            item["is_demo"] for item in payload["evidence"]
        )
        if payload["scope_warning"] == "AGGREGATE_TRADE_IS_NOT_COMPANY_BUYER_EVIDENCE":
            payload["scope_warning"] = "宏观贸易仅用于市场判断，不是具体买家证据。"
        return Response(payload)


class ReactivationCreateView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(tags=["Growth workspace"], request=ReactivationCreateSerializer)
    def post(self, request):
        serializer = ReactivationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        account = get_object_or_404(
            TargetAccount,
            id=serializer.validated_data["account_id"],
            organization=request.organization,
        )
        try:
            record, created = select_for_reactivation(
                account=account,
                actor=request.user,
                relationship_source=serializer.validated_data["relationship_source"],
                last_interacted_at=serializer.validated_data["last_interacted_at"],
                interaction_summary=serializer.validated_data["interaction_summary"],
                relationship_confirmed=serializer.validated_data["relationship_confirmed"],
            )
        except LegalRelationshipRequired as error:
            return Response({"code": error.code, "message": str(error)}, status=400)
        return Response(reactivation_payload(record), status=201 if created else 200)


class ReactivationDraftView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(tags=["Growth workspace"], request=None)
    def post(self, request, reactivation_id):
        record = get_object_or_404(
            ReactivationRecord.objects.select_related("account", "draft"),
            id=reactivation_id,
            organization=request.organization,
        )
        try:
            draft, created = create_reactivation_draft(record=record, actor=request.user)
        except ReactivationEvidenceInsufficient as error:
            return Response({"code": error.code, "message": str(error)}, status=409)
        return Response({
            "id": str(record.id),
            "draft_id": str(draft.id),
            "status": record.status,
            "draft_status": draft.status,
            "english_draft": draft.english_draft,
            "chinese_explanation": draft.chinese_explanation,
            "delivery": "NEVER_SENT",
        }, status=201 if created else 200)


class ReactivationApproveView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(tags=["Growth workspace"], request=None)
    def post(self, request, reactivation_id):
        record = get_object_or_404(
            ReactivationRecord.objects.select_related("account", "draft"),
            id=reactivation_id,
            organization=request.organization,
        )
        try:
            approve_reactivation_draft(record=record, actor=request.user)
        except ReactivationBlocked as error:
            return Response({"code": error.code, "message": str(error)}, status=409)
        return Response({
            "id": str(record.id),
            "status": record.status,
            "draft_status": record.draft.status,
            "delivery": "NEVER_SENT",
            "message": "Draft approved for future manual sending; nothing was sent.",
        })


class DiscoveryProfileView(APIView):
    permission_classes = [CanReadLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=DiscoveryProfileUpdateSerializer,
        responses={200: DiscoverySummarySerializer, 400: GrowthValidationErrorSerializer},
    )
    def patch(self, request):
        serializer = DiscoveryProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = discovery_profile_for(request.organization)
        profile.enabled = serializer.validated_data["enabled"]
        profile.save(update_fields=["enabled", "updated_at"])
        return Response(discovery_summary(profile))


def maps_config_for(organization):
    config, _ = GoogleMapsDiscoveryConfig.objects.get_or_create(organization=organization)
    return config


def maps_config_payload(config):
    return {
        "api_key_configured": bool(config.api_key_ciphertext),
        "enabled": config.enabled,
        "cities": config.cities,
        "keywords": config.keywords,
        "radius_km": config.radius_km,
        "daily_quota": config.daily_quota,
        "schedule_time": config.schedule_time,
        "next_run_at": config.next_run_at,
        "last_succeeded_at": config.last_succeeded_at,
        "consecutive_failures": config.consecutive_failures,
        "last_error_code": config.last_error_code,
    }


class GoogleMapsDiscoveryConfigView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        responses={200: GoogleMapsDiscoveryConfigResponseSerializer},
    )
    def get(self, request):
        return Response(maps_config_payload(maps_config_for(request.organization)))

    @extend_schema(
        tags=["Growth workspace"],
        request=GoogleMapsDiscoveryConfigUpdateSerializer,
        responses={
            200: GoogleMapsDiscoveryConfigResponseSerializer,
            400: GrowthValidationErrorSerializer,
        },
    )
    def put(self, request):
        serializer = GoogleMapsDiscoveryConfigUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        config = maps_config_for(request.organization)
        update_fields = []
        if "api_key" in data:
            api_key = data["api_key"].strip()
            config.api_key_ciphertext = encrypt_secret(api_key) if api_key else ""
            update_fields.append("api_key_ciphertext")
        for field in ("enabled", "cities", "keywords", "radius_km", "daily_quota", "schedule_time"):
            if field in data:
                setattr(config, field, data[field])
                update_fields.append(field)
        if update_fields:
            update_fields.append("updated_at")
            config.save(update_fields=update_fields)
        return Response(maps_config_payload(config))


class GoogleMapsDiscoveryRunView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=None,
        responses={
            200: GoogleMapsDiscoveryRunResultSerializer,
            400: GrowthValidationErrorSerializer,
        },
    )
    def post(self, request):
        config = maps_config_for(request.organization)
        try:
            result = run_maps_discovery(config.id, trigger="MANUAL")
        except MapsDiscoveryNotEnabled:
            return Response(
                {
                    "code": "MAPS_DISCOVERY_DISABLED",
                    "message": "谷歌地图自动发现尚未启用。",
                    "recovery_action": "先在数据源设置里填写 API Key 并开启自动发现。",
                },
                status=400,
            )
        except MapsDiscoveryMissingKey:
            return Response(
                {
                    "code": "MAPS_API_KEY_NOT_CONFIGURED",
                    "message": "还没有填写 Google Maps API Key。",
                    "recovery_action": "请在数据源设置里填写你的 Google Maps API Key。",
                },
                status=400,
            )
        except SourceAdapterError as error:
            return Response(
                {
                    "code": error.code,
                    "message": "谷歌地图接口返回错误。",
                    "recovery_action": "请检查 API Key 是否有效、是否启用了 Places API 及配额。",
                },
                status=502,
            )
        return Response(result)


class GoogleMapsDiscoveryTestView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=None,
        responses={200: OpenApiTypes.OBJECT},
    )
    def post(self, request):
        config = maps_config_for(request.organization)
        result = probe_maps_connection(config.id)
        return Response(result)


class ManualOpportunityImportView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=ManualOpportunityImportSerializer,
        responses={
            200: ManualOpportunityImportResponseSerializer,
            201: ManualOpportunityImportResponseSerializer,
            400: GrowthValidationErrorSerializer,
            403: GrowthErrorSerializer,
        },
    )
    def post(self, request):
        serializer = ManualOpportunityImportSerializer(data=request.data)
        if not serializer.is_valid():
            first_messages = next(iter(serializer.errors.values()), ["请检查导入内容。"])
            first_message = first_messages[0] if first_messages else "请检查导入内容。"
            return Response({
                "code": "INVALID_MANUAL_OPPORTUNITY",
                "message": str(first_message),
                "errors": serializer.errors,
            }, status=400)
        account, signal, created = import_manual_opportunity(
            organization=request.organization,
            data=serializer.validated_data,
        )
        payload = {
            "account": TargetAccountSerializer(account).data,
            "signal": IntentSignalSerializer(signal).data,
            "created": created,
        }
        return Response(payload, status=201 if created else 200)


class FollowUpView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request, account_id):
        account = get_object_or_404(TargetAccount, id=account_id, organization=request.organization)
        follow_up, created = add_to_follow_up(account=account)
        return Response({"id": follow_up.id, "status": follow_up.status}, status=201 if created else 200)


class OutreachDraftView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request, account_id):
        account = get_object_or_404(TargetAccount, id=account_id, organization=request.organization)
        draft, created = create_outreach_draft(account=account)
        return Response({
            "id": draft.id,
            "status": draft.status,
            "English draft": draft.english_draft,
            "Chinese explanation": draft.chinese_explanation,
            "delivery": "NEVER_SENT",
        }, status=201 if created else 200)


class OpportunityReviewView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=OpportunityReviewCreateSerializer,
        responses={201: OpportunityReviewSerializer},
    )
    def post(self, request, account_id):
        account = get_object_or_404(
            TargetAccount, id=account_id, organization=request.organization,
        )
        serializer = OpportunityReviewCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            review = record_opportunity_review(
                account=account,
                reviewer=request.user,
                decision=serializer.validated_data["decision"],
            )
        except OpportunityHandoffBlocked as error:
            return Response({"message": str(error)}, status=409)
        return Response(OpportunityReviewSerializer(review).data, status=201)


class CRMHandoffView(APIView):
    permission_classes = [CanManageLeads]

    @extend_schema(
        tags=["Growth workspace"],
        request=CRMHandoffCreateSerializer,
        responses={200: CRMHandoffSerializer, 201: CRMHandoffSerializer},
    )
    def post(self, request, account_id):
        account = get_object_or_404(
            TargetAccount, id=account_id, organization=request.organization,
        )
        serializer = CRMHandoffCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        draft = get_object_or_404(
            OutreachDraft,
            id=serializer.validated_data["draft_id"],
            account=account,
            organization=request.organization,
        )
        try:
            handoff, created = create_mock_crm_handoff(
                account=account, draft=draft, reviewer=request.user,
            )
        except OpportunityHandoffBlocked as error:
            return Response({"message": str(error)}, status=409)
        return Response(
            CRMHandoffSerializer(handoff).data,
            status=201 if created else 200,
        )


class ChannelPackageApproveView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request, package_id):
        package = get_object_or_404(
            ChannelPackage, id=package_id, organization=request.organization,
        )
        approve_channel_package(package=package)
        return Response({
            "id": str(package.id), "status": package.status, "delivery": "MANUAL_ONLY",
        })


class ChannelPackageBatchApproveView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request):
        serializer = ChannelPackageBatchApproveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            packages = approve_channel_package_batch(
                organization=request.organization,
                package_ids=serializer.validated_data["package_ids"],
            )
        except ChannelPackageBatchInvalid as error:
            return Response({
                "code": "CHANNEL_PACKAGE_SELECTION_INVALID",
                "message": str(error),
                "recovery_action": "返回推广页，确认四个渠道均使用当前组织的内容包。",
            }, status=409)
        return Response({
            "status": "APPROVED",
            "delivery": "MANUAL_ONLY",
            "packages": [
                {"id": str(package.id), "channel": package.channel, "status": package.status}
                for package in packages
            ],
        })


class ChannelPackageFromPlatformContentView(APIView):
    permission_classes = [CanManagePublishing]

    @extend_schema(tags=["Growth workspace"], responses={201: ChannelPackageSerializer})
    def post(self, request, content_id):
        content = get_object_or_404(
            PlatformContent,
            id=content_id,
            organization=request.organization,
        )
        try:
            package, created = prepare_channel_package_from_platform_content(content=content)
        except ChannelPackagePreparationBlocked as error:
            return Response({
                "code": "CHANNEL_PACKAGE_PREPARATION_BLOCKED",
                "message": str(error),
                "recovery_action": "返回内容审核中心，确认使用已批准的最新版本。",
            }, status=409)
        mission_id = request.data.get("mission_id")
        if mission_id:
            mission = GrowthMission.objects.filter(
                organization=request.organization, id=mission_id
            ).first()
            if mission is not None:
                link_mission_entity(
                    mission=mission,
                    entity=package,
                    lane=MissionEntityLink.Lane.SOCIAL,
                    actor=request.user,
                )
        return Response(
            ChannelPackageSerializer(package).data,
            status=201 if created else 200,
        )


class ChannelPackageManualExportView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request, package_id):
        package = get_object_or_404(
            ChannelPackage, id=package_id, organization=request.organization,
        )
        try:
            receipt = export_manual_channel_package(package=package)
        except PackageReviewRequired:
            return Response({
                "code": "PACKAGE_REVIEW_REQUIRED",
                "message": "请先人工批准内容包，再下载手工发布包。",
                "recovery_action": "返回推广页审核内容包。",
            }, status=409)
        except ValueError as error:
            return Response({
                "code": "PACKAGE_FORMAT_INVALID",
                "message": str(error),
                "recovery_action": "返回推广页补全渠道必填信息后重新审核。",
            }, status=409)
        return Response({
            "package_id": str(package.id),
            "channel": receipt.channel,
            "mode": receipt.mode,
            "data_label": receipt.data_label,
            "delivery": "MANUAL_ONLY",
            "filename": f"{package.channel.lower()}-manual-package.json",
            "payload": receipt.payload,
        })


class FourChannelManualExportView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(
        tags=["Growth workspace"],
        request=FourChannelManualExportSerializer,
        responses={200: OpenApiTypes.BINARY, 409: GrowthErrorSerializer},
    )
    def post(self, request):
        serializer = FourChannelManualExportSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "code": "MANUAL_EXPORT_NOT_READY",
                "message": "请选择 LinkedIn、Facebook、Instagram、TikTok 四个渠道内容包。",
                "recovery_action": "返回推广页补齐并批准四渠道内容。",
            }, status=409)
        try:
            exported = build_four_channel_export(
                organization=request.organization,
                package_ids=serializer.validated_data["package_ids"],
            )
        except FourChannelExportNotReady as error:
            return Response({
                "code": "MANUAL_EXPORT_NOT_READY",
                "message": str(error),
                "recovery_action": "返回推广页补齐或重新审核四渠道内容。",
            }, status=409)
        response = HttpResponse(exported.content, content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="{exported.filename}"'
        response["X-Content-SHA256"] = exported.content_hash
        response["ETag"] = f'"{exported.content_hash}"'
        response["Cache-Control"] = "private, no-store"
        return response


class MetricReceiptCreateView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request):
        serializer = MetricReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receipt = serializer.save(organization=request.organization)
        return Response(MetricReceiptSerializer(receipt).data, status=201)


class CompanyFactVerifyView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request, fact_id):
        fact = get_object_or_404(
            FieldProvenance, id=fact_id, organization=request.organization,
        )
        verify_company_fact(fact=fact)
        return Response({
            "id": str(fact.id), "verification_status": fact.verification_status,
        })


class PublishBatchCreateView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request):
        if not promotion_plan_status(request.organization)["approved"]:
            return Response({
                "code": "PROMOTION_PLAN_NOT_APPROVED",
                "message": "请先在推广页确认推广计划，再提交发布。",
                "recovery_action": "前往推广页确认推广计划。",
            }, status=409)
        key = request.headers.get("Idempotency-Key", "")
        if not key:
            return Response({
                "code": "IDEMPOTENCY_KEY_REQUIRED",
                "message": "一键发布需要防重复请求标识。",
            }, status=400)
        serializer = PublishBatchCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                "code": "INVALID_PACKAGE_SELECTION",
                "message": "请选择至少一个有效内容包。",
                "errors": serializer.errors,
            }, status=400)
        existed = GrowthPublishBatch.objects.filter(
            organization=request.organization, idempotency_key=key.strip(),
        ).exists()
        try:
            batch = create_publish_batch(
                organization=request.organization,
                actor=request.user,
                package_ids=serializer.validated_data["package_ids"],
                idempotency_key=key,
            )
        except PublishPackageSelectionInvalid:
            return Response({
                "code": "PACKAGE_SELECTION_NOT_FOUND",
                "message": "所选内容包不存在或不可用。",
            }, status=404)
        except PublishBatchConflict:
            return Response({
                "code": "IDEMPOTENCY_CONFLICT",
                "message": "该发布请求与之前的操作不一致。",
            }, status=409)
        mission_id = serializer.validated_data.get("mission_id")
        if mission_id:
            mission = GrowthMission.objects.filter(
                organization=request.organization, id=mission_id
            ).first()
            if mission is not None:
                link_mission_entity(
                    mission=mission,
                    entity=batch,
                    lane=MissionEntityLink.Lane.SOCIAL,
                    actor=request.user,
                )
        return Response(
            GrowthPublishBatchSerializer(batch).data,
            status=200 if existed else 201,
        )


class PublishBatchDetailView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def get(self, request, batch_id):
        batch = get_object_or_404(
            GrowthPublishBatch.objects.prefetch_related("items"),
            id=batch_id,
            organization=request.organization,
        )
        return Response(GrowthPublishBatchSerializer(batch).data)


class PublishBatchRetryFailedView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request, batch_id):
        batch = get_object_or_404(
            GrowthPublishBatch, id=batch_id, organization=request.organization,
        )
        retry_failed_items(batch=batch, actor=request.user)
        batch = GrowthPublishBatch.objects.prefetch_related("items").get(pk=batch.pk)
        return Response(GrowthPublishBatchSerializer(batch).data)
