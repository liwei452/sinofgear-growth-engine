from drf_spectacular.utils import extend_schema
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanManageCampaigns, CanReadCampaigns
from apps.platforms.connection_status import connection_summary
from integrations.sources.base import SourceAdapterError

from .candidate_imports import CandidateImportInvalid, import_candidate_list
from .discovery import DiscoveryAlreadyRunning, run_discovery
from .enrichment import (
    CandidateEnrichmentRequired,
    CandidateReviewRequired,
    add_candidate_to_follow_up,
    enrichment_payload,
    prepare_fake_enrichment,
)
from .models import (
    ChannelPackage,
    Contact,
    DiscoveryCandidate,
    DiscoveryProfile,
    DiscoveryRun,
    FieldProvenance,
    FollowUp,
    GrowthPublishBatch,
    InboundLead,
    IntentSignal,
    MetricReceipt,
    MarketCountryProfile,
    OpportunityReview,
    OutreachDraft,
    CRMHandoff,
    TargetAccount,
)
from .manual_imports import import_manual_opportunity
from .market_pilots import market_pilot_summary, market_profiles_for
from .serializers import (
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
    GrowthPublishBatchSerializer,
    GrowthErrorSerializer,
    GrowthValidationErrorSerializer,
    InboundLeadSerializer,
    IntentSignalSerializer,
    ManualOpportunityImportResponseSerializer,
    ManualOpportunityImportSerializer,
    MetricReceiptSerializer,
    OpportunityReviewCreateSerializer,
    OpportunityReviewSerializer,
    OutreachDraftSerializer,
    CRMHandoffCreateSerializer,
    CRMHandoffSerializer,
    PublishBatchCreateSerializer,
    TargetAccountSerializer,
)
from .publishing import (
    PublishBatchConflict,
    PublishPackageSelectionInvalid,
    create_publish_batch,
    retry_failed_items,
)
from .services import (
    PackageReviewRequired,
    OpportunityHandoffBlocked,
    add_to_follow_up,
    approve_channel_package,
    create_outreach_draft,
    create_mock_crm_handoff,
    export_manual_channel_package,
    verify_company_fact,
    record_opportunity_review,
)


def connector_readiness(organization):
    results = []
    for channel in ("LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK"):
        summary = connection_summary(
            organization=organization, platform_code=channel,
        )
        results.append({
            "channel": channel,
            "status": summary.status,
            "connection_label": summary.connection_label,
            "recovery_action": summary.recovery_action,
            "mode": summary.mode,
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
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def get(self, request):
        organization = request.organization
        accounts = list(TargetAccount.objects.filter(organization=organization))
        signals = list(IntentSignal.objects.filter(organization=organization))
        return Response({
            "target_accounts": TargetAccountSerializer(accounts, many=True).data,
            "contacts": ContactSerializer(Contact.objects.filter(organization=organization), many=True).data,
            "intent_signals": IntentSignalSerializer(signals, many=True).data,
            "inbound_leads": InboundLeadSerializer(InboundLead.objects.filter(organization=organization), many=True).data,
            "follow_ups": FollowUpSerializer(FollowUp.objects.filter(organization=organization), many=True).data,
            "outreach_drafts": OutreachDraftSerializer(
                OutreachDraft.objects.filter(organization=organization).order_by("-created_at", "-id"), many=True,
            ).data,
            "opportunity_reviews": OpportunityReviewSerializer(
                OpportunityReview.objects.filter(organization=organization), many=True,
            ).data,
            "crm_handoffs": CRMHandoffSerializer(
                CRMHandoff.objects.filter(organization=organization), many=True,
            ).data,
            "channel_packages": ChannelPackageSerializer(
                ChannelPackage.objects.filter(organization=organization).order_by("channel", "id"), many=True,
            ).data,
            "publish_batches": GrowthPublishBatchSerializer(
                GrowthPublishBatch.objects.filter(organization=organization)
                .prefetch_related("items")[:5],
                many=True,
            ).data,
            "metric_receipts": MetricReceiptSerializer(
                MetricReceipt.objects.filter(organization=organization).order_by("-created_at", "-id"), many=True,
            ).data,
            "field_provenance": FieldProvenanceSerializer(
                FieldProvenance.objects.filter(organization=organization), many=True,
            ).data,
            "connectors": connector_readiness(organization),
            "discovery": discovery_summary(discovery_profile_for(organization)),
            "market_pilots": market_pilot_summary(
                signals=signals,
                accounts=accounts,
                profiles=market_profiles_for(organization),
            ),
        })


class DiscoveryRunView(APIView):
    permission_classes = [CanManageCampaigns]

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
    permission_classes = [CanManageCampaigns]

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
    permission_classes = [CanManageCampaigns]

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
    permission_classes = [CanManageCampaigns]

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
            snapshot, created = prepare_fake_enrichment(candidate=candidate)
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


class CandidateEnrichmentFollowUpView(APIView):
    permission_classes = [CanManageCampaigns]

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


class DiscoveryProfileView(APIView):
    permission_classes = [CanManageCampaigns]

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


class ManualOpportunityImportView(APIView):
    permission_classes = [CanManageCampaigns]

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
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request, account_id):
        account = get_object_or_404(TargetAccount, id=account_id, organization=request.organization)
        follow_up, created = add_to_follow_up(account=account)
        return Response({"id": follow_up.id, "status": follow_up.status}, status=201 if created else 200)


class OutreachDraftView(APIView):
    permission_classes = [CanManageCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def post(self, request, account_id):
        account = get_object_or_404(TargetAccount, id=account_id, organization=request.organization)
        draft = create_outreach_draft(account=account)
        return Response({
            "id": draft.id,
            "status": draft.status,
            "English draft": draft.english_draft,
            "Chinese explanation": draft.chinese_explanation,
            "delivery": "NEVER_SENT",
        }, status=201)


class OpportunityReviewView(APIView):
    permission_classes = [CanManageCampaigns]

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
    permission_classes = [CanManageCampaigns]

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
        return Response({
            "package_id": str(package.id),
            "channel": receipt.channel,
            "mode": receipt.mode,
            "data_label": receipt.data_label,
            "delivery": "MANUAL_ONLY",
            "filename": f"{package.channel.lower()}-manual-package.json",
            "payload": receipt.payload,
        })


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
