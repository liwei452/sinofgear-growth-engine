from django.urls import include, path
from drf_spectacular.views import SpectacularJSONAPIView

from apps.common.api import health_check

urlpatterns = [
    path("api/v1/health", health_check, name="health-check"),
    path("api/v1/schema", SpectacularJSONAPIView.as_view(), name="openapi-schema"),
]
urlpatterns += [path("api/v1/", include("apps.identity.urls"))]
