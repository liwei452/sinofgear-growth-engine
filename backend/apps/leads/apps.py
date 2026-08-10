from django.apps import AppConfig


class LeadsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.leads"

    def ready(self):
        from apps.jobs.models import Job
        from apps.jobs.services import register_job_terminal_handler

        from .orchestration import recover_terminal_lead_job

        register_job_terminal_handler(
            Job.Type.LEAD_ANALYZE,
            recover_terminal_lead_job,
        )
