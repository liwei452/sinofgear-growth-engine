from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.platforms.models import Platform, PlatformCapability


PLATFORM_CAPABILITIES = {
    "LINKEDIN": ("LinkedIn", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "FACEBOOK": ("Facebook", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "INSTAGRAM": ("Instagram", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "YOUTUBE": ("YouTube", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "TIKTOK": ("TikTok", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "DOUYIN": ("Douyin", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "KUAISHOU": ("Kuaishou", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "WECHAT_OFFICIAL_ACCOUNT": ("WeChat Official Account", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "WECHAT_CHANNELS": ("WeChat Channels", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "XIAOHONGSHU": ("Xiaohongshu", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
    "BILIBILI": ("Bilibili", ("PUBLISH", "METRICS_READ", "COMMENT_READ", "MEDIA_UPLOAD")),
}


class Command(BaseCommand):
    help = "Seed the Phase A social platform catalogue (owner role only)."

    @staticmethod
    def _require_owner_connection() -> None:
        if connection.vendor == "sqlite":
            return
        if connection.vendor != "postgresql":
            raise CommandError("Platform seeding requires PostgreSQL or SQLite preview mode.")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user"
            )
            privileged = cursor.fetchone()
        if privileged != (True,):
            raise CommandError("Platform seeding requires the migration/owner database role.")

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        self._require_owner_connection()
        for code, (name, capabilities) in PLATFORM_CAPABILITIES.items():
            platform, _ = Platform.objects.update_or_create(code=code, defaults={"name": name})
            PlatformCapability.objects.filter(platform=platform).exclude(code__in=capabilities).delete()
            for capability in capabilities:
                PlatformCapability.objects.update_or_create(platform=platform, code=capability)
        self.stdout.write(self.style.SUCCESS("Platform catalogue seeded."))
