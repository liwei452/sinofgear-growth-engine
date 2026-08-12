from datetime import timedelta

from django.db.models import Case, IntegerField, Q, When

from apps.identity.permissions import PermissionCode
from apps.jobs.models import Job

from .models import DirectorDecision, DirectorProposal


_DECISION_ACTIONS = [
    DirectorDecision.Action.APPROVE,
    DirectorDecision.Action.REQUEST_ADJUSTMENT,
    DirectorDecision.Action.REJECT,
]
_JOB_LABELS = {
    Job.Type.CONTENT_GENERATE: "正在生成平台内容",
    Job.Type.SOURCE_IMPORT: "正在导入公开来源",
    Job.Type.SOURCE_NORMALIZE: "正在整理来源信息",
    Job.Type.EVIDENCE_EXTRACT: "正在提取客户证据",
    Job.Type.LEAD_ANALYZE: "正在分析客户机会",
    Job.Type.RETENTION_CLEANUP: "正在清理过期数据",
}


def _has(permissions, code):
    return str(code) in {str(permission) for permission in permissions}


def _decision_items(*, organization, permissions, now):
    actions = _DECISION_ACTIONS if _has(permissions, PermissionCode.DIRECTOR_DECIDE) else []
    proposals = DirectorProposal.objects.filter(
        organization=organization,
        status=DirectorProposal.Status.PENDING,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).order_by(
        "-priority", "created_at", "id"
    )[:3]
    return [
        {
            "id": proposal.id,
            "type": proposal.proposal_type,
            "title": proposal.title_zh,
            "explanation": proposal.summary_zh,
            "priority": proposal.priority,
            "version": proposal.version,
            "actions": actions,
        }
        for proposal in proposals
    ]


def _active_work(*, organization, permissions):
    if not _has(permissions, PermissionCode.JOBS_READ):
        return []
    status_priority = Case(
        When(status=Job.Status.RUNNING, then=0),
        When(status=Job.Status.RETRY_QUEUED, then=1),
        When(status=Job.Status.QUEUED, then=2),
        default=3,
        output_field=IntegerField(),
    )
    jobs = Job.objects.filter(
        organization=organization,
        status__in=[Job.Status.RUNNING, Job.Status.RETRY_QUEUED, Job.Status.QUEUED],
    ).annotate(_status_priority=status_priority).order_by(
        "_status_priority", "-created_at", "-id"
    )[:5]
    return [
        {
            "job_id": job.id,
            "label": _JOB_LABELS.get(job.type, "AI 正在处理任务"),
            "status": job.status,
            "progress": job.progress,
            "progress_is_determinate": job.status == Job.Status.RUNNING,
        }
        for job in jobs
    ]


def _recent_outcomes(*, organization, permissions, now):
    outcomes = []
    since = now - timedelta(days=30)
    if _has(permissions, PermissionCode.PUBLISHING_READ):
        from apps.publishing.models import PublishedPost

        count = PublishedPost.objects.filter(
            organization=organization, published_at__gte=since
        ).count()
        outcomes.append({
            "kind": "PUBLISHING",
            "label": "内容发布",
            "value": str(count),
            "detail": "最近 30 天真实完成记录",
        })
    if _has(permissions, PermissionCode.LEADS_READ):
        from apps.leads.models import LeadCandidate

        count = LeadCandidate.objects.filter(
            organization=organization,
            status=LeadCandidate.Status.READY_FOR_HANDOFF,
            updated_at__gte=since,
        ).count()
        outcomes.append({
            "kind": "LEADS",
            "label": "待交接客户机会",
            "value": str(count),
            "detail": "最近 30 天真实待交接记录",
        })
    if _has(permissions, PermissionCode.TRACKING_READ):
        from apps.tracking.models import ClickEvent

        count = ClickEvent.objects.filter(
            organization=organization, occurred_at__gte=since
        ).count()
        outcomes.append({
            "kind": "TRACKING",
            "label": "网站访问",
            "value": str(count),
            "detail": "最近 30 天真实访问记录",
        })
    if _has(permissions, PermissionCode.CONTENT_READ):
        from apps.content.models import PlatformContent

        count = PlatformContent.objects.filter(
            organization=organization, created_at__gte=since
        ).count()
        outcomes.append({
            "kind": "CONTENT",
            "label": "平台内容",
            "value": str(count),
            "detail": "最近 30 天真实创建记录",
        })
    return outcomes[:4]


def cockpit_snapshot(*, organization, permissions, now):
    return {
        "decisions": _decision_items(
            organization=organization, permissions=permissions, now=now
        ),
        "active_work": _active_work(
            organization=organization, permissions=permissions
        ),
        "recent_outcomes": _recent_outcomes(
            organization=organization, permissions=permissions, now=now
        ),
        "generated_at": now,
    }
