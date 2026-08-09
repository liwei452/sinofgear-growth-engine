from django.urls import path

from .views import (
    PublishCalendarView, PublishCancelView, PublishRetryView, PublishRunView, PublishScheduleView,
    PublishTaskDetailView, PublishTaskListView,
)


urlpatterns = [
    path("publish-tasks", PublishTaskListView.as_view()),
    path("publish-tasks/schedule", PublishScheduleView.as_view()),
    path("publish-tasks/<uuid:task_id>", PublishTaskDetailView.as_view()),
    path("publish-tasks/<uuid:task_id>/cancel", PublishCancelView.as_view()),
    path("publish-tasks/<uuid:task_id>/retry", PublishRetryView.as_view()),
    path("publish-tasks/<uuid:task_id>/run", PublishRunView.as_view()),
    path("publish-calendar", PublishCalendarView.as_view()),
]
