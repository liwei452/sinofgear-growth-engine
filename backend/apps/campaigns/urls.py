from django.urls import path

from .views import (
    CampaignDetailView,
    CampaignListView,
    ContentBriefDetailView,
    ContentBriefListView,
    ContentBriefReadyView,
    ContentBriefRevisionView,
)


urlpatterns = [
    path("campaigns", CampaignListView.as_view(), name="campaigns"),
    path("campaigns/<uuid:campaign_id>", CampaignDetailView.as_view(), name="campaign-detail"),
    path("content-briefs", ContentBriefListView.as_view(), name="content-briefs"),
    path("content-briefs/<uuid:brief_id>", ContentBriefDetailView.as_view(), name="content-brief-detail"),
    path("content-briefs/<uuid:brief_id>/ready", ContentBriefReadyView.as_view(), name="content-brief-ready"),
    path("content-briefs/<uuid:brief_id>/revisions", ContentBriefRevisionView.as_view(), name="content-brief-revisions"),
]
