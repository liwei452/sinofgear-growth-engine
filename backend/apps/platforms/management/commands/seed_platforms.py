from django.core.management.base import BaseCommand

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
    help = "Seed the Phase A social platform catalogue."

    def handle(self, *args: object, **options: object) -> None:
        for code, (name, capabilities) in PLATFORM_CAPABILITIES.items():
            platform, _ = Platform.objects.update_or_create(code=code, defaults={"name": name})
            PlatformCapability.objects.filter(platform=platform).exclude(code__in=capabilities).delete()
            for capability in capabilities:
                PlatformCapability.objects.update_or_create(platform=platform, code=capability)
        self.stdout.write(self.style.SUCCESS("Platform catalogue seeded."))
