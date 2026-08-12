from django.urls import include, path
from drf_spectacular.utils import extend_schema
from drf_spectacular.views import SpectacularJSONAPIView

from apps.common.api import health_check


@extend_schema(tags=["System"])
class OpenAPISchemaView(SpectacularJSONAPIView):
    pass

urlpatterns = [
    path("api/v1/health", health_check, name="health-check"),
    path("api/v1/schema", OpenAPISchemaView.as_view(), name="openapi-schema"),
]
urlpatterns += [path("", include("apps.tracking.urls"))]
urlpatterns += [path("api/v1/", include("apps.identity.urls"))]
urlpatterns += [path("api/v1/", include("apps.platforms.urls"))]
urlpatterns += [path("api/v1/", include("apps.knowledge.urls"))]
urlpatterns += [path("api/v1/", include("apps.catalog.urls"))]
urlpatterns += [path("api/v1/", include("apps.assets.urls"))]
urlpatterns += [path("api/v1/", include("apps.campaigns.urls"))]
urlpatterns += [path("api/v1/", include("apps.jobs.urls"))]
urlpatterns += [path("api/v1/", include("apps.sources.urls"))]
urlpatterns += [path("api/v1/", include("apps.leads.urls"))]
urlpatterns += [path("api/v1/", include("apps.ai.urls"))]
urlpatterns += [path("api/v1/", include("apps.content.urls"))]
urlpatterns += [path("api/v1/", include("apps.publishing.urls"))]
urlpatterns += [path("api/v1/", include("apps.director.urls"))]
