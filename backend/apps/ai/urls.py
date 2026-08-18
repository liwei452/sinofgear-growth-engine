from django.urls import path

from .views import (
    AIRunDetailView,
    AIRunListView,
    AIProviderConfigTestView,
    AIProviderConfigView,
    ProductAIStatusView,
)


urlpatterns = [
    path("ai/provider-status", ProductAIStatusView.as_view(), name="product-ai-provider-status"),
    path("ai/provider-config", AIProviderConfigView.as_view(), name="ai-provider-config"),
    path("ai/provider-config/test", AIProviderConfigTestView.as_view(), name="ai-provider-config-test"),
    path("ai-runs", AIRunListView.as_view(), name="ai-run-list"),
    path("ai-runs/<uuid:run_id>", AIRunDetailView.as_view(), name="ai-run-detail"),
]
