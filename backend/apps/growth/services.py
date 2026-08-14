from django.db import transaction

from integrations.platforms.manual_fake import ManualPackageFakeConnector, ManualPackageReceipt

from .models import ChannelPackage, FieldProvenance, FollowUp, OutreachDraft, TargetAccount


class PackageReviewRequired(RuntimeError):
    pass


@transaction.atomic
def add_to_follow_up(*, account: TargetAccount) -> tuple[FollowUp, bool]:
    return FollowUp.objects.get_or_create(organization=account.organization, account=account)


@transaction.atomic
def create_outreach_draft(*, account: TargetAccount) -> OutreachDraft:
    return OutreachDraft.objects.create(
        organization=account.organization,
        account=account,
        english_draft=(
            f"Hello {account.name} team, may I share a short manufacturing capability summary "
            "for your review?"
        ),
        chinese_explanation="仅建议询问对方是否愿意查看能力摘要；没有声称对方已经采购，也不会自动发送。",
    )


@transaction.atomic
def approve_channel_package(*, package: ChannelPackage) -> ChannelPackage:
    if package.status != "APPROVED":
        package.status = "APPROVED"
        package.save(update_fields=["status", "updated_at"])
    return package


def export_manual_channel_package(*, package: ChannelPackage) -> ManualPackageReceipt:
    if package.status != "APPROVED":
        raise PackageReviewRequired("Channel package requires human approval before export.")
    return ManualPackageFakeConnector().build_package(
        channel=package.channel,
        payload=package.payload,
    )


@transaction.atomic
def verify_company_fact(*, fact: FieldProvenance) -> FieldProvenance:
    if fact.verification_status != "VERIFIED":
        fact.verification_status = "VERIFIED"
        fact.save(update_fields=["verification_status", "updated_at"])
    return fact
