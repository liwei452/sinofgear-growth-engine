from django.urls import path

from .views import (
    AssetDetailView,
    AssetDownloadURLView,
    AssetLinkProductView,
    AssetListView,
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
]
