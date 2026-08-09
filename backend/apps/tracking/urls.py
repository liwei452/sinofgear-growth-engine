from django.urls import path

from .views import (
    ChannelSummaryView, PublicRedirectView, ShortLinkDetailView, ShortLinkListView,
    TrackingLinkDetailView, TrackingLinkListView,
)


urlpatterns = [
    path("r/<str:code>", PublicRedirectView.as_view(), name="tracking-redirect"),
    path("api/v1/tracking-links", TrackingLinkListView.as_view()),
    path("api/v1/tracking-links/<uuid:link_id>", TrackingLinkDetailView.as_view()),
    path("api/v1/short-links", ShortLinkListView.as_view()),
    path("api/v1/short-links/<uuid:link_id>", ShortLinkDetailView.as_view()),
    path("api/v1/analytics/channel-summary", ChannelSummaryView.as_view()),
]
