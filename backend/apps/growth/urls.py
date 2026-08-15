from django.urls import path

from .views import (
    ChannelPackageApproveView,
    ChannelPackageManualExportView,
    CompanyFactVerifyView,
    DiscoveryProfileView,
    DiscoveryRunView,
    FollowUpView,
    GrowthWorkspaceView,
    MetricReceiptCreateView,
    ManualOpportunityImportView,
    OutreachDraftView,
    PublishBatchCreateView,
    PublishBatchDetailView,
    PublishBatchRetryFailedView,
)

urlpatterns = [
    path("growth/workspace", GrowthWorkspaceView.as_view(), name="growth-workspace"),
    path("growth/discovery/run", DiscoveryRunView.as_view(), name="growth-discovery-run"),
    path(
        "growth/discovery/profile",
        DiscoveryProfileView.as_view(),
        name="growth-discovery-profile",
    ),
    path(
        "growth/opportunity-imports/manual-url",
        ManualOpportunityImportView.as_view(),
        name="growth-manual-opportunity-import",
    ),
    path("growth/opportunities/<uuid:account_id>/follow-up", FollowUpView.as_view(), name="growth-follow-up"),
    path("growth/opportunities/<uuid:account_id>/draft", OutreachDraftView.as_view(), name="growth-draft"),
    path(
        "growth/channel-packages/<uuid:package_id>/approve",
        ChannelPackageApproveView.as_view(),
        name="growth-channel-package-approve",
    ),
    path(
        "growth/channel-packages/<uuid:package_id>/manual-export",
        ChannelPackageManualExportView.as_view(),
        name="growth-channel-package-manual-export",
    ),
    path("growth/metric-receipts", MetricReceiptCreateView.as_view(), name="growth-metric-receipts"),
    path("growth/publish-batches", PublishBatchCreateView.as_view(), name="growth-publish-batches"),
    path(
        "growth/publish-batches/<uuid:batch_id>",
        PublishBatchDetailView.as_view(),
        name="growth-publish-batch-detail",
    ),
    path(
        "growth/publish-batches/<uuid:batch_id>/retry-failed",
        PublishBatchRetryFailedView.as_view(),
        name="growth-publish-batch-retry-failed",
    ),
    path(
        "growth/company-facts/<uuid:fact_id>/verify",
        CompanyFactVerifyView.as_view(),
        name="growth-company-fact-verify",
    ),
]
