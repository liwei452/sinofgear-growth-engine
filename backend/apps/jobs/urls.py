from django.urls import path

from .views import JobCancelView, JobDetailView, JobListView, JobRetryView


urlpatterns = [
    path("jobs", JobListView.as_view(), name="jobs-list"),
    path("jobs/<uuid:job_id>", JobDetailView.as_view(), name="jobs-detail"),
    path("jobs/<uuid:job_id>/retry", JobRetryView.as_view(), name="jobs-retry"),
    path("jobs/<uuid:job_id>/cancel", JobCancelView.as_view(), name="jobs-cancel"),
]
