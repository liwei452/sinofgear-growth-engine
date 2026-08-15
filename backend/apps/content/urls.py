from django.urls import path

from .views import (
    ContentRecommendationDetailView, ContentRecommendationListCreateView,
    ContentRecommendationSelectView,
    GenerateMasterView, GeneratePlatformView, MasterApproveView, MasterArchiveView,
    MasterDetailView, MasterListView, MasterRejectView, MasterRevisionView,
    MasterSubmitView, PlatformDetailView, PlatformListView,
    PlatformApproveView, PlatformArchiveView, PlatformRejectView,
    PlatformRevisionView, PlatformSubmitView,
)


urlpatterns = [
    path("content-recommendations", ContentRecommendationListCreateView.as_view()),
    path("content-recommendations/<uuid:recommendation_id>", ContentRecommendationDetailView.as_view()),
    path(
        "content-recommendations/<uuid:recommendation_id>/options/<uuid:option_id>/select",
        ContentRecommendationSelectView.as_view(),
    ),
    path("content-briefs/<uuid:brief_id>/generate-master-content", GenerateMasterView.as_view()),
    path("master-contents", MasterListView.as_view()),
    path("master-contents/<uuid:content_id>", MasterDetailView.as_view()),
    path("master-contents/<uuid:content_id>/revisions", MasterRevisionView.as_view()),
    path("master-contents/<uuid:content_id>/submit-review", MasterSubmitView.as_view()),
    path("master-contents/<uuid:content_id>/approve", MasterApproveView.as_view()),
    path("master-contents/<uuid:content_id>/reject", MasterRejectView.as_view()),
    path("master-contents/<uuid:content_id>/archive", MasterArchiveView.as_view()),
    path("master-contents/<uuid:content_id>/generate-platform-content", GeneratePlatformView.as_view()),
    path("platform-contents", PlatformListView.as_view()),
    path("platform-contents/<uuid:content_id>", PlatformDetailView.as_view()),
    path("platform-contents/<uuid:content_id>/revisions", PlatformRevisionView.as_view()),
    path("platform-contents/<uuid:content_id>/submit-review", PlatformSubmitView.as_view()),
    path("platform-contents/<uuid:content_id>/approve", PlatformApproveView.as_view()),
    path("platform-contents/<uuid:content_id>/reject", PlatformRejectView.as_view()),
    path("platform-contents/<uuid:content_id>/archive", PlatformArchiveView.as_view()),
]
