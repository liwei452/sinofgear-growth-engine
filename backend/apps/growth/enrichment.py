from django.db import transaction
from django.utils import timezone

from .models import CandidateEnrichmentSnapshot, DiscoveryCandidate, FollowUp, TargetAccount


class CandidateReviewRequired(Exception):
    pass


class CandidateEnrichmentRequired(Exception):
    pass


@transaction.atomic
def prepare_fake_enrichment(*, candidate: DiscoveryCandidate):
    locked = DiscoveryCandidate.objects.select_for_update().get(pk=candidate.pk)
    if locked.status != DiscoveryCandidate.Status.ACCEPTED:
        raise CandidateReviewRequired

    facts = [
        {"field": "company_name", "value": locked.company_name, "source": "许可名单导入"},
        {"field": "country", "value": locked.country, "source": "许可名单导入"},
    ]
    for field, value in (("industry", locked.industry), ("website", locked.website)):
        if value:
            facts.append({"field": field, "value": value, "source": "许可名单导入"})

    snapshot, created = CandidateEnrichmentSnapshot.objects.get_or_create(
        organization=locked.organization,
        candidate=locked,
        defaults={
            "mode": "FAKE_PREVIEW",
            "facts": facts,
            "public_contact_paths": [],
            "uncertainties": [
                "尚未联网核实公司官网",
                "尚未发现可验证的公开联系页面",
                "没有采购意向证据",
            ],
            "evidence_envelope": {
                "source_owner": locked.source_governance.get("source_owner", ""),
                "license_contract": locked.source_governance.get("license_contract", ""),
                "access_method": "USER_UPLOAD",
                "connector": "FAKE_WEBSITE_ENRICHMENT",
                "network_access": False,
                "source_cost_micros": 0,
                "review_status": "PENDING_REVIEW",
                "observed_at": timezone.now().isoformat(),
            },
        },
    )
    return snapshot, created


def enrichment_payload(snapshot, *, created):
    return {
        "candidate_id": str(snapshot.candidate_id),
        "mode": snapshot.mode,
        "data_label": "Demo / Fake 资料补全预演",
        "facts": snapshot.facts,
        "public_contact_paths": snapshot.public_contact_paths,
        "uncertainties": snapshot.uncertainties,
        "message": "已生成资料补全预演；没有联网抓取，也不会联系客户。",
        "created": created,
        "account_id": str(snapshot.target_account_id) if snapshot.target_account_id else None,
    }


@transaction.atomic
def add_candidate_to_follow_up(*, candidate: DiscoveryCandidate):
    locked = DiscoveryCandidate.objects.select_for_update().get(pk=candidate.pk)
    try:
        snapshot = CandidateEnrichmentSnapshot.objects.select_for_update().get(candidate=locked)
    except CandidateEnrichmentSnapshot.DoesNotExist as error:
        raise CandidateEnrichmentRequired from error

    account, account_created = TargetAccount.objects.get_or_create(
        organization=locked.organization,
        source_identity=f"candidate:{locked.id}",
        defaults={
            "name": locked.company_name,
            "country": locked.country,
            "industry": locked.industry,
            "website": locked.website,
            "is_demo": locked.is_demo,
        },
    )
    if snapshot.target_account_id != account.id:
        snapshot.target_account = account
        snapshot.save(update_fields=["target_account", "updated_at"])
    follow_up, follow_up_created = FollowUp.objects.get_or_create(
        organization=locked.organization,
        account=account,
    )
    return account, follow_up, account_created or follow_up_created
