from django.urls import path

from .views import (
    LeadCandidateAnalyzeView,
    LeadCandidateDetailView,
    LeadCandidateListView,
    LeadInsightListView,
    LeadReviewCreateView,
)


urlpatterns = [
    path("lead-candidates", LeadCandidateListView.as_view(), name="lead-candidates"),
    path(
        "lead-candidates/<uuid:candidate_id>",
        LeadCandidateDetailView.as_view(),
        name="lead-candidate-detail",
    ),
    path(
        "lead-candidates/<uuid:candidate_id>/analyze",
        LeadCandidateAnalyzeView.as_view(),
        name="lead-candidate-analyze",
    ),
    path("lead-insights", LeadInsightListView.as_view(), name="lead-insights"),
    path("lead-reviews", LeadReviewCreateView.as_view(), name="lead-reviews"),
]
