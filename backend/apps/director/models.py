import uuid
from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


_proposal_state_write = ContextVar("director_proposal_state_write", default=False)


@contextmanager
def director_proposal_state_writes():
    token = _proposal_state_write.set(True)
    try:
        yield
    finally:
        _proposal_state_write.reset(token)


class DirectorProposalQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if {"organization", "organization_id"} & set(kwargs):
            raise ValidationError("Proposal organization is immutable after creation.")
        if {"status", "version"} & set(kwargs) and not _proposal_state_write.get():
            raise ValidationError(
                "Proposal state may change only through DirectorService."
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        field_names = {field.name if hasattr(field, "name") else str(field) for field in fields}
        if {"organization", "organization_id"} & field_names:
            raise ValidationError("Proposal organization is immutable after creation.")
        if {"status", "version"} & field_names and not _proposal_state_write.get():
            raise ValidationError(
                "Proposal state may change only through DirectorService."
            )
        return super().bulk_update(objs, fields, **kwargs)

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Director proposal upserts are not allowed.")
        rows = list(objs)
        if not _proposal_state_write.get() and any(
            row.status != DirectorProposal.Status.PENDING or row.version != 1
            for row in rows
        ):
            raise ValidationError(
                "Proposal state may change only through DirectorService."
            )
        return super().bulk_create(rows, **kwargs)


class DirectorProposal(models.Model):
    class ProposalType(models.TextChoices):
        PROMOTION_PLAN = "PROMOTION_PLAN", "Promotion plan"
        CONTENT_APPROVAL = "CONTENT_APPROVAL", "Content approval"
        LEAD_HANDOFF = "LEAD_HANDOFF", "Lead handoff"
        FACT_CONFLICT = "FACT_CONFLICT", "Fact conflict"
        COST_APPROVAL = "COST_APPROVAL", "Cost approval"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        ADJUSTMENT_REQUESTED = "ADJUSTMENT_REQUESTED", "Adjustment requested"
        REJECTED = "REJECTED", "Rejected"
        SUPERSEDED = "SUPERSEDED", "Superseded"
        EXPIRED = "EXPIRED", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT)
    proposal_type = models.CharField(max_length=32, choices=ProposalType.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    priority = models.PositiveSmallIntegerField(default=50)
    title_zh = models.CharField(max_length=160)
    summary_zh = models.TextField()
    reason_snapshot = models.JSONField(default=dict)
    action_reference = models.JSONField(default=dict)
    expires_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = models.Manager.from_queryset(DirectorProposalQuerySet)()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(priority__gte=1) & models.Q(priority__lte=100),
                name="director_proposal_priority_range",
            ),
            models.CheckConstraint(
                condition=~models.Q(title_zh=""), name="director_proposal_title_nonempty"
            ),
            models.CheckConstraint(
                condition=models.Q(version__gt=0), name="director_proposal_version_positive"
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            original = type(self).objects.only(
                "organization_id", "status", "version"
            ).get(pk=self.pk)
            if self.organization_id != original.organization_id:
                raise ValidationError("Proposal organization is immutable after creation.")
            if (
                self.status != original.status or self.version != original.version
            ) and not _proposal_state_write.get():
                raise ValidationError(
                    "Proposal state may change only through DirectorService."
                )
        elif (
            self.status != self.Status.PENDING or self.version != 1
        ) and not _proposal_state_write.get():
            raise ValidationError(
                "Proposal state may change only through DirectorService."
            )
        return super().save(*args, **kwargs)


class DirectorDecisionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Director decision history is append-only.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Director decision history is append-only.")

    def bulk_create(self, objs, **kwargs):
        if kwargs.get("update_conflicts"):
            raise ValidationError("Director decision upserts are not allowed.")
        rows = list(objs)
        for obj in rows:
            obj._validate_organization_match()
        return super().bulk_create(rows, **kwargs)

    def delete(self):
        raise ValidationError("Director decision history is append-only.")


class DirectorDecision(models.Model):
    class Action(models.TextChoices):
        APPROVE = "APPROVE", "Approve"
        REQUEST_ADJUSTMENT = "REQUEST_ADJUSTMENT", "Request adjustment"
        REJECT = "REJECT", "Reject"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    proposal = models.ForeignKey(
        DirectorProposal, on_delete=models.PROTECT, related_name="decisions"
    )
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT)
    action = models.CharField(max_length=32, choices=Action.choices)
    proposal_version = models.PositiveIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="director_decisions"
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager.from_queryset(DirectorDecisionQuerySet)()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(proposal_version__gt=0),
                name="director_decision_proposal_version_positive",
            ),
            models.UniqueConstraint(
                fields=["proposal", "proposal_version"],
                name="director_one_decision_per_proposal_version",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self)._base_manager.filter(pk=self.pk).exists():
            raise ValidationError("Director decision history is append-only.")
        self._validate_organization_match()
        return super().save(*args, **kwargs)

    def _validate_organization_match(self):
        if not self.organization_id or not self.proposal_id:
            return
        proposal_organization_id = (
            DirectorProposal._base_manager.filter(pk=self.proposal_id)
            .values_list("organization_id", flat=True)
            .first()
        )
        if proposal_organization_id != self.organization_id:
            raise ValidationError(
                {"organization": "Decision organization must match its proposal organization."}
            )

    def delete(self, *args, **kwargs):
        raise ValidationError("Director decision history is append-only.")
