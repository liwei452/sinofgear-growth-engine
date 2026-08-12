from django.urls import path

from .views import DirectorCockpitView, DirectorProposalDecisionView


urlpatterns = [
    path("director/cockpit", DirectorCockpitView.as_view(), name="director-cockpit"),
    path(
        "director/proposals/<uuid:id>/decisions",
        DirectorProposalDecisionView.as_view(),
        name="director-proposal-decision",
    ),
]
