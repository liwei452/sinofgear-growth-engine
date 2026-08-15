from django.urls import path

from .views import (
    AssetDetailView,
    AssetDownloadURLView,
    AssetLinkProductView,
    AssetListView,
    AssetUnderstandingRetryView,
    AssetUnderstandingView,
    ProductEvidenceFactReviewView,
)


urlpatterns = [
    path("assets", AssetListView.as_view(), name="assets"),
    path("assets/<uuid:asset_id>", AssetDetailView.as_view(), name="asset-detail"),
    path(
        "assets/<uuid:asset_id>/link-product",
        AssetLinkProductView.as_view(),
        name="asset-link-product",
    ),
    path(
        "assets/<uuid:asset_id>/download-url",
        AssetDownloadURLView.as_view(),
        name="asset-download-url",
    ),
    path(
        "assets/<uuid:asset_id>/understanding",
        AssetUnderstandingView.as_view(),
        name="asset-understanding",
    ),
    path(
        "assets/<uuid:asset_id>/understanding/retry",
        AssetUnderstandingRetryView.as_view(),
        name="asset-understanding-retry",
    ),
    path(
        "assets/facts/<uuid:fact_id>/review",
        ProductEvidenceFactReviewView.as_view(),
        name="asset-fact-review",
    ),
]
