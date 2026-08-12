from django.urls import path

from .views import (
    AIRunDetailView,
    AIRunListView,
    AIProviderConfigurationTestView,
    AIProviderConfigurationView,
)


urlpatterns = [
    path("ai-runs", AIRunListView.as_view(), name="ai-run-list"),
    path("ai-runs/<uuid:run_id>", AIRunDetailView.as_view(), name="ai-run-detail"),
    path(
        "ai-provider-configuration",
        AIProviderConfigurationView.as_view(),
        name="ai-provider-configuration",
    ),
    path(
        "ai-provider-configuration/test",
        AIProviderConfigurationTestView.as_view(),
        name="ai-provider-configuration-test",
    ),
]
