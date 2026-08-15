from django.urls import path

from .views import AIRunDetailView, AIRunListView, ProductAIStatusView


urlpatterns = [
    path("ai/provider-status", ProductAIStatusView.as_view(), name="product-ai-provider-status"),
    path("ai-runs", AIRunListView.as_view(), name="ai-run-list"),
    path("ai-runs/<uuid:run_id>", AIRunDetailView.as_view(), name="ai-run-detail"),
]
