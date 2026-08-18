import hashlib

from django.conf import settings
from django.utils import timezone

from .models import PostMetric, PublishedPost, publishing_writes


def _demo_metrics(post) -> dict:
    seed = int(hashlib.sha256(str(post.id).encode()).hexdigest()[:8], 16)
    age_days = max(0, (timezone.now() - post.published_at).days)
    decay = max(1, age_days + 1)
    impressions = (500 + seed % 1500) // decay
    is_video = post.platform_content.platform.code.upper() in {
        "TIKTOK", "INSTAGRAM", "YOUTUBE",
    }
    likes = impressions // 12
    comments = likes // 4
    shares = likes // 8
    clicks = impressions // 25
    return {
        "impressions": impressions,
        "plays": impressions if is_video else 0,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "clicks": clicks,
    }


def sync_post_metrics(*, organization, now=None) -> int:
    if not getattr(settings, "DEMO_POST_METRICS_ENABLED", False):
        return 0
    now = now or timezone.now()
    collected_on = now.date()
    posts = (
        PublishedPost.objects.filter(organization=organization)
        .select_related("platform_content__platform")
    )
    created = 0
    for post in posts:
        values = {"source": "demo", **_demo_metrics(post)}
        with publishing_writes():
            _post_metric, was_created = PostMetric.objects.update_or_create(
                organization=organization,
                post=post,
                collected_on=collected_on,
                defaults=values,
            )
        created += int(was_created)
    return created
