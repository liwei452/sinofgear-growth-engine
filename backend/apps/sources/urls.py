from django.urls import path

from .views import (
    IngestionBatchListView,
    MonitoringTargetListView,
    SourceContentListView,
    SourceEvidenceDetailView,
    SourceEvidenceListView,
    SourceSignalListView,
)


urlpatterns = [
    path("monitoring-targets", MonitoringTargetListView.as_view(), name="monitoring-targets"),
    path("ingestion-batches", IngestionBatchListView.as_view(), name="ingestion-batches"),
    path("source-contents", SourceContentListView.as_view(), name="source-contents"),
    path("source-signals", SourceSignalListView.as_view(), name="source-signals"),
    path("source-evidences", SourceEvidenceListView.as_view(), name="source-evidences"),
    path(
        "source-evidences/<uuid:evidence_id>",
        SourceEvidenceDetailView.as_view(),
        name="source-evidence-detail",
    ),
]
