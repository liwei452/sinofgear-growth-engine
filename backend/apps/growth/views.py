from drf_spectacular.utils import extend_schema
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.identity.permissions import CanManageCampaigns, CanReadCampaigns
from apps.platforms.connection_status import connection_summary

from .models import (
    ChannelPackage,
    Contact,
    FieldProvenance,
    FollowUp,
    GrowthPublishBatch,
    InboundLead,
    IntentSignal,
    MetricReceipt,
    OutreachDraft,
    TargetAccount,
)
from .manual_imports import import_manual_opportunity
from .serializers import (
    ChannelPackageSerializer,
    ContactSerializer,
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
    OutreachDraftSerializer,
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
    add_to_follow_up,
    approve_channel_package,
    create_outreach_draft,
    export_manual_channel_package,
    verify_company_fact,
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


class GrowthWorkspaceView(APIView):
    permission_classes = [CanReadCampaigns]

    @extend_schema(tags=["Growth workspace"])
    def get(self, request):
        organization = request.organization
        return Response({
            "target_accounts": TargetAccountSerializer(TargetAccount.objects.filter(organization=organization), many=True).data,
            "contacts": ContactSerializer(Contact.objects.filter(organization=organization), many=True).data,
            "intent_signals": IntentSignalSerializer(IntentSignal.objects.filter(organization=organization), many=True).data,
            "inbound_leads": InboundLeadSerializer(InboundLead.objects.filter(organization=organization), many=True).data,
            "follow_ups": FollowUpSerializer(FollowUp.objects.filter(organization=organization), many=True).data,
            "outreach_drafts": OutreachDraftSerializer(
                OutreachDraft.objects.filter(organization=organization).order_by("-created_at", "-id"), many=True,
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
        })


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
