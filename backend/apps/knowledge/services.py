from dataclasses import asdict, dataclass
from datetime import datetime
from functools import wraps
from typing import Iterable, Sequence
from uuid import UUID

from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.audit.models import ReviewAction
from apps.audit.services import record_review_transition
from apps.common.tenancy import tenant_atomic
from apps.identity.models import Organization

from .models import (
    CompanyFact,
    CompanyKnowledgeProfile,
    ICPProductLink,
    ICPProfile,
    KnowledgeAlias,
    KnowledgeConcept,
    KnowledgeEvidence,
    KnowledgeRelation,
    KnowledgeStatus,
    WebsitePage,
    WebsitePageConceptLink,
    WebsitePageProductLink,
)
from .guards import _audited_review_writes, _company_review_writes
from .normalization import normalize_alias
from .relation_rules import validate_predicate_types


class OntologyDepthError(ValueError):
    pass


class KnowledgeStateError(ValueError):
    pass


class CompanyRevisionStateError(ValueError):
    pass


def _tenant_service_atomic(method):
    @wraps(method)
    def wrapped(service, *args, **kwargs):
        with tenant_atomic(service.organization.id):
            return method(service, *args, **kwargs)

    return wrapped


class _CompanyReviewService:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    def _ensure_organization(self, instance) -> None:
        if instance.organization_id != self.organization.id:
            raise ValidationError("Company revision belongs to another organization.")

    def _record_transition(
        self,
        *,
        instance,
        action: str,
        actor: AbstractBaseUser,
        before_status: str,
        comment: str,
    ) -> None:
        record_review_transition(
            organization=self.organization,
            object_type=f"{instance._meta.app_label}.{instance.__class__.__name__}",
            object_id=instance.pk,
            action=action,
            status=instance.status,
            object_version=instance.version,
            actor=actor,
            comment=comment,
            before_metadata={"status": before_status, "version": instance.version},
            after_metadata={"status": instance.status, "version": instance.version},
        )


class CompanyProfileReviewService(_CompanyReviewService):
    @_tenant_service_atomic
    @transaction.atomic
    def submit(
        self,
        profile: CompanyKnowledgeProfile,
        *,
        actor: AbstractBaseUser,
        review_note: str = "",
    ) -> CompanyKnowledgeProfile:
        return self._transition(
            profile,
            expected=CompanyKnowledgeProfile.Status.DRAFT,
            target=CompanyKnowledgeProfile.Status.IN_REVIEW,
            action=ReviewAction.SUBMIT,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def approve(
        self,
        profile: CompanyKnowledgeProfile,
        *,
        actor: AbstractBaseUser,
        review_note: str = "",
    ) -> CompanyKnowledgeProfile:
        locked = CompanyKnowledgeProfile.objects.select_for_update().get(pk=profile.pk)
        self._ensure_organization(locked)
        if locked.status != CompanyKnowledgeProfile.Status.IN_REVIEW:
            raise CompanyRevisionStateError(f"Cannot approve profile in status {locked.status}.")

        current = (
            CompanyKnowledgeProfile.objects.select_for_update()
            .filter(
                organization=self.organization,
                status=CompanyKnowledgeProfile.Status.APPROVED,
            )
            .exclude(pk=locked.pk)
            .first()
        )
        if current:
            if locked.supersedes_id != current.pk:
                raise CompanyRevisionStateError("A new approved profile must supersede the current approved revision.")
            before_status = current.status
            current.status = CompanyKnowledgeProfile.Status.SUPERSEDED
            with _company_review_writes():
                current.save(update_fields=["status"])
            self._record_transition(
                instance=current,
                action=ReviewAction.DEPRECATE,
                actor=actor,
                before_status=before_status,
                comment=review_note.strip(),
            )

        return self._transition_locked(
            locked,
            target=CompanyKnowledgeProfile.Status.APPROVED,
            action=ReviewAction.APPROVE,
            actor=actor,
            review_note=review_note,
        )

    def _transition(
        self,
        profile: CompanyKnowledgeProfile,
        *,
        expected: str,
        target: str,
        action: str,
        actor: AbstractBaseUser,
        review_note: str,
    ) -> CompanyKnowledgeProfile:
        locked = CompanyKnowledgeProfile.objects.select_for_update().get(pk=profile.pk)
        self._ensure_organization(locked)
        if locked.status != expected:
            raise CompanyRevisionStateError(f"Cannot transition profile from {locked.status} to {target}.")
        return self._transition_locked(
            locked,
            target=target,
            action=action,
            actor=actor,
            review_note=review_note,
        )

    def _transition_locked(
        self,
        profile: CompanyKnowledgeProfile,
        *,
        target: str,
        action: str,
        actor: AbstractBaseUser,
        review_note: str,
    ) -> CompanyKnowledgeProfile:
        before_status = profile.status
        profile.status = target
        profile.review_note = review_note.strip()
        update_fields = ["status", "review_note"]
        if target == CompanyKnowledgeProfile.Status.APPROVED:
            profile.reviewed_by = actor
            profile.reviewed_at = timezone.now()
            update_fields.extend(["reviewed_by", "reviewed_at"])
        with _company_review_writes():
            profile.save(update_fields=update_fields)
        self._record_transition(
            instance=profile,
            action=action,
            actor=actor,
            before_status=before_status,
            comment=profile.review_note,
        )
        return profile


class CompanyFactReviewService(_CompanyReviewService):
    @_tenant_service_atomic
    @transaction.atomic
    def submit(
        self,
        fact: CompanyFact,
        *,
        actor: AbstractBaseUser,
        review_note: str = "",
    ) -> CompanyFact:
        return self._transition(
            fact,
            expected=CompanyFact.Status.DRAFT,
            target=CompanyFact.Status.IN_REVIEW,
            action=ReviewAction.SUBMIT,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def verify(
        self,
        fact: CompanyFact,
        *,
        actor: AbstractBaseUser,
        review_note: str = "",
    ) -> CompanyFact:
        locked = CompanyFact.objects.select_for_update().get(pk=fact.pk)
        self._ensure_organization(locked)
        if locked.status != CompanyFact.Status.IN_REVIEW:
            raise CompanyRevisionStateError(f"Cannot verify fact in status {locked.status}.")
        current = (
            CompanyFact.objects.select_for_update()
            .filter(
                profile=locked.profile,
                namespace=locked.namespace,
                key=locked.key,
                status=CompanyFact.Status.VERIFIED,
            )
            .exclude(pk=locked.pk)
            .first()
        )
        if current:
            if locked.supersedes_id != current.pk:
                raise CompanyRevisionStateError("A new verified fact must supersede the current verified revision.")
            before_status = current.status
            current.status = CompanyFact.Status.SUPERSEDED
            with _company_review_writes():
                current.save(update_fields=["status"])
            self._record_transition(
                instance=current,
                action=ReviewAction.DEPRECATE,
                actor=actor,
                before_status=before_status,
                comment=review_note.strip(),
            )
        return self._transition_locked(
            locked,
            target=CompanyFact.Status.VERIFIED,
            action=ReviewAction.APPROVE,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def reject(
        self,
        fact: CompanyFact,
        *,
        actor: AbstractBaseUser,
        review_note: str,
    ) -> CompanyFact:
        if not review_note.strip():
            raise ValueError("Reject review note must not be empty.")
        return self._transition(
            fact,
            expected=CompanyFact.Status.IN_REVIEW,
            target=CompanyFact.Status.REJECTED,
            action=ReviewAction.REJECT,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def create_revision(
        self,
        fact: CompanyFact,
        *,
        actor: AbstractBaseUser,
        **changes,
    ) -> CompanyFact:
        locked = CompanyFact.objects.select_for_update().get(pk=fact.pk)
        self._ensure_organization(locked)
        if locked.status != CompanyFact.Status.VERIFIED:
            raise CompanyRevisionStateError("Only a verified fact can be revised.")
        allowed_changes = set(CompanyFact.business_fields)
        unknown = set(changes) - allowed_changes
        if unknown:
            raise ValueError(f"Unsupported fact revision fields: {', '.join(sorted(unknown))}")
        values = {field: getattr(locked, field) for field in CompanyFact.business_fields}
        values.update(changes)
        return CompanyFact.objects.create(
            organization=locked.organization,
            profile=locked.profile,
            namespace=locked.namespace,
            key=locked.key,
            version=locked.version + 1,
            supersedes=locked,
            status=CompanyFact.Status.DRAFT,
            created_by=actor,
            **values,
        )

    def _transition(
        self,
        fact: CompanyFact,
        *,
        expected: str,
        target: str,
        action: str,
        actor: AbstractBaseUser,
        review_note: str,
    ) -> CompanyFact:
        locked = CompanyFact.objects.select_for_update().get(pk=fact.pk)
        self._ensure_organization(locked)
        if locked.status != expected:
            raise CompanyRevisionStateError(f"Cannot transition fact from {locked.status} to {target}.")
        return self._transition_locked(
            locked,
            target=target,
            action=action,
            actor=actor,
            review_note=review_note,
        )

    def _transition_locked(
        self,
        fact: CompanyFact,
        *,
        target: str,
        action: str,
        actor: AbstractBaseUser,
        review_note: str,
    ) -> CompanyFact:
        before_status = fact.status
        fact.status = target
        fact.review_note = review_note.strip()
        update_fields = ["status", "review_note"]
        if target in {CompanyFact.Status.VERIFIED, CompanyFact.Status.REJECTED}:
            fact.reviewed_by = actor
            fact.reviewed_at = timezone.now()
            update_fields.extend(["reviewed_by", "reviewed_at"])
        with _company_review_writes():
            fact.save(update_fields=update_fields)
        self._record_transition(
            instance=fact,
            action=action,
            actor=actor,
            before_status=before_status,
            comment=fact.review_note,
        )
        return fact


def _copy_revision_value(value):
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def _require_native_bool(name: str, value: object) -> None:
    if type(value) is not bool:
        raise ValidationError({name: "Revision copy options must be boolean values."})


class _ContextRevisionReviewService(_CompanyReviewService):
    model = None
    approved_status = ""

    def _locked(self, instance):
        locked = self.model.objects.select_for_update().get(pk=instance.pk)
        self._ensure_organization(locked)
        return locked

    def _transition(
        self,
        instance,
        *,
        expected: str,
        target: str,
        action: str,
        actor: AbstractBaseUser,
        review_note: str,
    ):
        locked = self._locked(instance)
        if locked.status != expected:
            raise CompanyRevisionStateError(
                f"Cannot transition {locked.__class__.__name__} from {locked.status} to {target}."
            )
        return self._transition_locked(
            locked,
            target=target,
            action=action,
            actor=actor,
            review_note=review_note,
        )

    def _transition_locked(
        self,
        instance,
        *,
        target: str,
        action: str,
        actor: AbstractBaseUser,
        review_note: str,
    ):
        before_status = instance.status
        instance.status = target
        instance.review_note = review_note.strip()
        update_fields = ["status", "review_note"]
        if target in {self.approved_status, self.model.Status.REJECTED}:
            instance.reviewed_by = actor
            instance.reviewed_at = timezone.now()
            update_fields.extend(["reviewed_by", "reviewed_at"])
        if isinstance(instance, WebsitePage) and target == WebsitePage.Status.VERIFIED:
            instance.last_verified_at = timezone.now()
            update_fields.append("last_verified_at")
        with _company_review_writes():
            instance.save(update_fields=update_fields)
        self._record_transition(
            instance=instance,
            action=action,
            actor=actor,
            before_status=before_status,
            comment=instance.review_note,
        )
        return instance

    def _supersede_current(self, *, locked, current_filter, actor, review_note) -> None:
        current = (
            self.model.objects.select_for_update()
            .filter(**current_filter, status=self.approved_status)
            .exclude(pk=locked.pk)
            .order_by("id")
            .first()
        )
        if not current:
            return
        if locked.supersedes_id != current.pk:
            raise CompanyRevisionStateError(
                "A newly approved revision must supersede the current approved revision."
            )
        before_status = current.status
        current.status = self.model.Status.SUPERSEDED
        with _company_review_writes():
            current.save(update_fields=["status"])
        self._record_transition(
            instance=current,
            action=ReviewAction.DEPRECATE,
            actor=actor,
            before_status=before_status,
            comment=review_note.strip(),
        )

    def _next_version(self, **identity_filter) -> int:
        versions = list(
            self.model.objects.select_for_update()
            .filter(**identity_filter)
            .order_by("id")
            .values_list("version", flat=True)
        )
        return max(versions, default=0) + 1


class ICPProfileReviewService(_ContextRevisionReviewService):
    model = ICPProfile
    approved_status = ICPProfile.Status.APPROVED

    @staticmethod
    def _locked_valid_product_links(profile: ICPProfile) -> list[ICPProductLink]:
        links = list(
            ICPProductLink.objects.select_for_update()
            .filter(icp_profile=profile)
            .order_by("id")
        )
        ICPProductLink._validate_targets(links, parents={profile.pk: profile})
        return links

    @_tenant_service_atomic
    @transaction.atomic
    def submit(
        self,
        profile: ICPProfile,
        *,
        actor: AbstractBaseUser,
        review_note: str = "",
    ) -> ICPProfile:
        locked = self._locked(profile)
        if locked.status != ICPProfile.Status.DRAFT:
            raise CompanyRevisionStateError(
                f"Cannot transition ICPProfile from {locked.status} to "
                f"{ICPProfile.Status.IN_REVIEW}."
            )
        self._locked_valid_product_links(locked)
        return self._transition_locked(
            locked,
            target=ICPProfile.Status.IN_REVIEW,
            action=ReviewAction.SUBMIT,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def approve(
        self,
        profile: ICPProfile,
        *,
        actor: AbstractBaseUser,
        review_note: str = "",
    ) -> ICPProfile:
        locked = self._locked(profile)
        if locked.status != ICPProfile.Status.IN_REVIEW:
            raise CompanyRevisionStateError(f"Cannot approve ICP in status {locked.status}.")
        self._locked_valid_product_links(locked)
        self._supersede_current(
            locked=locked,
            current_filter={"organization": self.organization, "code": locked.code},
            actor=actor,
            review_note=review_note,
        )
        return self._transition_locked(
            locked,
            target=ICPProfile.Status.APPROVED,
            action=ReviewAction.APPROVE,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def reject(
        self,
        profile: ICPProfile,
        *,
        actor: AbstractBaseUser,
        review_note: str,
    ) -> ICPProfile:
        if not review_note.strip():
            raise ValueError("Reject review note must not be empty.")
        return self._transition(
            profile,
            expected=ICPProfile.Status.IN_REVIEW,
            target=ICPProfile.Status.REJECTED,
            action=ReviewAction.REJECT,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def create_revision(
        self,
        profile: ICPProfile,
        *,
        actor: AbstractBaseUser,
        copy_product_links: bool = True,
        **changes,
    ) -> ICPProfile:
        _require_native_bool("copy_product_links", copy_product_links)
        locked = self._locked(profile)
        if locked.status != ICPProfile.Status.APPROVED:
            raise CompanyRevisionStateError("Only an approved ICP can be revised.")
        unknown = set(changes) - set(ICPProfile.business_fields)
        if unknown:
            raise ValueError(f"Unsupported ICP revision fields: {', '.join(sorted(unknown))}")
        identity_filter = {"organization": self.organization, "code": locked.code}
        values = {
            field: _copy_revision_value(getattr(locked, field))
            for field in ICPProfile.business_fields
        }
        values.update(changes)
        links = self._locked_valid_product_links(locked) if copy_product_links else []
        revision = ICPProfile.objects.create(
            organization=self.organization,
            code=locked.code,
            version=self._next_version(**identity_filter),
            supersedes=locked,
            status=ICPProfile.Status.DRAFT,
            created_by=actor,
            **values,
        )
        ICPProductLink.objects.bulk_create(
            [
                ICPProductLink(
                    icp_profile=revision,
                    product_id=link.product_id,
                    role=link.role,
                    priority=link.priority,
                    use_cases=list(link.use_cases),
                )
                for link in links
            ]
        )
        return revision


class WebsitePageReviewService(_ContextRevisionReviewService):
    model = WebsitePage
    approved_status = WebsitePage.Status.VERIFIED

    @staticmethod
    def _locked_valid_links(
        page: WebsitePage,
        *,
        include_products: bool = True,
        include_concepts: bool = True,
    ) -> tuple[list[WebsitePageProductLink], list[WebsitePageConceptLink]]:
        product_links = (
            list(
                WebsitePageProductLink.objects.select_for_update()
                .filter(website_page=page)
                .order_by("id")
            )
            if include_products
            else []
        )
        concept_links = (
            list(
                WebsitePageConceptLink.objects.select_for_update()
                .filter(website_page=page)
                .order_by("id")
            )
            if include_concepts
            else []
        )
        WebsitePageProductLink._validate_targets(
            product_links,
            parents={page.pk: page},
        )
        WebsitePageConceptLink._validate_targets(
            concept_links,
            parents={page.pk: page},
        )
        return product_links, concept_links

    @_tenant_service_atomic
    @transaction.atomic
    def submit(
        self,
        page: WebsitePage,
        *,
        actor: AbstractBaseUser,
        review_note: str = "",
    ) -> WebsitePage:
        locked = self._locked(page)
        if locked.status != WebsitePage.Status.DRAFT:
            raise CompanyRevisionStateError(
                f"Cannot transition WebsitePage from {locked.status} to "
                f"{WebsitePage.Status.IN_REVIEW}."
            )
        self._locked_valid_links(locked)
        return self._transition_locked(
            locked,
            target=WebsitePage.Status.IN_REVIEW,
            action=ReviewAction.SUBMIT,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def verify(
        self,
        page: WebsitePage,
        *,
        actor: AbstractBaseUser,
        review_note: str = "",
    ) -> WebsitePage:
        locked = self._locked(page)
        if locked.status != WebsitePage.Status.IN_REVIEW:
            raise CompanyRevisionStateError(f"Cannot verify page in status {locked.status}.")
        self._locked_valid_links(locked)
        self._supersede_current(
            locked=locked,
            current_filter={
                "organization": self.organization,
                "canonical_url": locked.canonical_url,
            },
            actor=actor,
            review_note=review_note,
        )
        return self._transition_locked(
            locked,
            target=WebsitePage.Status.VERIFIED,
            action=ReviewAction.APPROVE,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def reject(
        self,
        page: WebsitePage,
        *,
        actor: AbstractBaseUser,
        review_note: str,
    ) -> WebsitePage:
        if not review_note.strip():
            raise ValueError("Reject review note must not be empty.")
        return self._transition(
            page,
            expected=WebsitePage.Status.IN_REVIEW,
            target=WebsitePage.Status.REJECTED,
            action=ReviewAction.REJECT,
            actor=actor,
            review_note=review_note,
        )

    @_tenant_service_atomic
    @transaction.atomic
    def create_revision(
        self,
        page: WebsitePage,
        *,
        actor: AbstractBaseUser,
        copy_product_links: bool = True,
        copy_concept_links: bool = True,
        **changes,
    ) -> WebsitePage:
        _require_native_bool("copy_product_links", copy_product_links)
        _require_native_bool("copy_concept_links", copy_concept_links)
        locked = self._locked(page)
        if locked.status != WebsitePage.Status.VERIFIED:
            raise CompanyRevisionStateError("Only a verified website page can be revised.")
        unknown = set(changes) - set(WebsitePage.business_fields)
        if unknown:
            raise ValueError(f"Unsupported website page revision fields: {', '.join(sorted(unknown))}")
        identity_filter = {
            "organization": self.organization,
            "canonical_url": locked.canonical_url,
        }
        values = {
            field: _copy_revision_value(getattr(locked, field))
            for field in WebsitePage.business_fields
        }
        values.update(changes)
        product_links, concept_links = self._locked_valid_links(
            locked,
            include_products=copy_product_links,
            include_concepts=copy_concept_links,
        )
        revision = WebsitePage.objects.create(
            organization=self.organization,
            canonical_url=locked.canonical_url,
            version=self._next_version(**identity_filter),
            supersedes=locked,
            status=WebsitePage.Status.DRAFT,
            last_verified_at=None,
            created_by=actor,
            **values,
        )
        WebsitePageProductLink.objects.bulk_create(
            [
                WebsitePageProductLink(
                    website_page=revision,
                    product_id=link.product_id,
                    relation_type=link.relation_type,
                )
                for link in product_links
            ]
        )
        WebsitePageConceptLink.objects.bulk_create(
            [
                WebsitePageConceptLink(
                    website_page=revision,
                    concept_id=link.concept_id,
                    role=link.role,
                )
                for link in concept_links
            ]
        )
        return revision


@dataclass(frozen=True)
class ConceptMatch:
    concept_id: UUID
    code: str
    concept_type: str
    scope: str
    label_zh: str
    label_en: str


@dataclass(frozen=True)
class AliasResolution:
    ambiguous: bool
    candidates: tuple[ConceptMatch, ...]
    selected: ConceptMatch | None


@dataclass(frozen=True)
class ConceptVersion:
    concept_id: UUID
    code: str
    concept_type: str
    label_zh: str
    label_en: str
    version: int
    status: str


@dataclass(frozen=True)
class RelationVersion:
    relation_id: UUID
    subject_concept_id: UUID
    predicate: str
    object_concept_id: UUID
    version: int
    status: str


@dataclass(frozen=True)
class EvidenceReference:
    evidence_id: UUID
    evidence_type: str
    source_object_type: str
    source_object_id: UUID | None
    source_url: str | None
    excerpt: str
    captured_at: datetime | None
    version: int
    status: str


@dataclass(frozen=True)
class OntologySnapshot:
    organization_id: UUID
    concept_versions: tuple[ConceptVersion, ...]
    relation_versions: tuple[RelationVersion, ...]
    evidence_references: tuple[EvidenceReference, ...]
    generated_at: datetime

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _visible_filter(organization: Organization) -> Q:
    return Q(organization__isnull=True) | Q(organization=organization)


class KnowledgeReviewService:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    @_tenant_service_atomic
    @transaction.atomic
    def transition(
        self,
        *,
        instance,
        action: str,
        actor: AbstractBaseUser,
        comment: str = "",
    ):
        if action == ReviewAction.REJECT and not comment.strip():
            raise ValueError("Reject comment must not be empty.")
        from .graph import acquire_knowledge_graph_lock

        acquire_knowledge_graph_lock()
        model = type(instance)
        locked = model.objects.select_for_update().get(pk=instance.pk)
        self._ensure_visible(locked)
        before = self._metadata(locked)
        target_status = {
            ReviewAction.SUBMIT: KnowledgeStatus.SUGGESTED,
            ReviewAction.APPROVE: KnowledgeStatus.APPROVED,
            ReviewAction.REJECT: KnowledgeStatus.REJECTED,
            ReviewAction.DEPRECATE: KnowledgeStatus.DEPRECATED,
        }[action]
        allowed_status = {
            ReviewAction.SUBMIT: KnowledgeStatus.SUGGESTED,
            ReviewAction.APPROVE: KnowledgeStatus.SUGGESTED,
            ReviewAction.REJECT: KnowledgeStatus.SUGGESTED,
            ReviewAction.DEPRECATE: KnowledgeStatus.APPROVED,
        }[action]
        if locked.status != allowed_status:
            raise KnowledgeStateError(f"Cannot {action.lower()} knowledge in status {locked.status}.")
        locked.status = target_status
        locked.version += 1
        if action in {ReviewAction.APPROVE, ReviewAction.REJECT, ReviewAction.DEPRECATE}:
            locked.reviewed_by = actor
            locked.reviewed_at = timezone.now()
        with _audited_review_writes():
            locked.save(update_fields=["status", "version", "reviewed_by", "reviewed_at", "updated_at"])
        after = self._metadata(locked)
        record_review_transition(
            organization=self.organization,
            object_type=f"{locked._meta.app_label}.{locked.__class__.__name__}",
            object_id=locked.pk,
            action=action,
            status=target_status,
            object_version=locked.version,
            actor=actor,
            comment=comment.strip(),
            before_metadata=before,
            after_metadata=after,
        )
        return locked

    def _ensure_visible(self, instance) -> None:
        organization_id = getattr(instance, "organization_id", None)
        if organization_id not in {None, self.organization.id}:
            raise ValidationError("Knowledge object is not visible to this organization.")

    @staticmethod
    def _metadata(instance) -> dict[str, object]:
        return {
            "status": instance.status,
            "version": instance.version,
            "organization_id": str(instance.organization_id) if instance.organization_id else None,
        }


class KnowledgeRelationService:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    @_tenant_service_atomic
    @transaction.atomic
    def create(
        self,
        subject: KnowledgeConcept,
        predicate: str,
        object: KnowledgeConcept,
        *,
        status: str = KnowledgeStatus.SUGGESTED,
        confidence=1,
        suggested_by_ai_run_id: UUID | None = None,
        created_by: AbstractBaseUser | None = None,
        scope: str | None = None,
    ) -> KnowledgeRelation:
        self._ensure_concept_visible(subject)
        self._ensure_concept_visible(object)
        validate_predicate_types(subject=subject, predicate=predicate, object=object)
        if scope == KnowledgeConcept.Scope.SYSTEM:
            if subject.organization_id is not None or object.organization_id is not None:
                raise ValidationError("SYSTEM relations require SYSTEM concepts.")
            relation_organization = None
        elif scope == KnowledgeConcept.Scope.ORGANIZATION:
            relation_organization = self.organization
        else:
            relation_organization = None if subject.organization_id is None and object.organization_id is None else self.organization
        relation = KnowledgeRelation(
            organization=relation_organization,
            subject_concept=subject,
            predicate=predicate,
            object_concept=object,
            status=status,
            confidence=confidence,
            suggested_by_ai_run_id=suggested_by_ai_run_id,
            created_by=created_by,
        )
        relation.clean()
        relation.save()
        return relation

    def _ensure_concept_visible(self, concept: KnowledgeConcept) -> None:
        if concept.organization_id not in {None, self.organization.id}:
            raise ValidationError("Concept is not visible to this organization.")

    @staticmethod
    def graph_lock_concept_ids(
        *, subject: KnowledgeConcept, object: KnowledgeConcept
    ) -> tuple[UUID, ...]:
        return tuple(sorted({subject.id, object.id}, key=str))

class OntologyContextService:
    def __init__(self, organization: Organization) -> None:
        self.organization = organization

    def visible_concepts(self) -> QuerySet[KnowledgeConcept]:
        return KnowledgeConcept.objects.filter(_visible_filter(self.organization)).order_by("code", "id")

    def visible_relations(self) -> QuerySet[KnowledgeRelation]:
        return KnowledgeRelation.objects.filter(_visible_filter(self.organization)).order_by(
            "subject_concept__code", "predicate", "object_concept__code", "id"
        )

    def visible_aliases(self) -> QuerySet[KnowledgeAlias]:
        return KnowledgeAlias.objects.filter(_visible_filter(self.organization)).order_by(
            "normalized_alias", "concept__code", "id"
        )

    def visible_evidence(self) -> QuerySet[KnowledgeEvidence]:
        return KnowledgeEvidence.objects.filter(_visible_filter(self.organization)).order_by("created_at", "id")

    def resolve_alias(self, *, text: str, language: str) -> AliasResolution:
        normalized = normalize_alias(text, language=language)
        aliases = self.visible_aliases().filter(
            language=language.strip().lower(),
            normalized_alias=normalized,
            status=KnowledgeStatus.APPROVED,
            concept__status=KnowledgeStatus.APPROVED,
        ).select_related("concept")
        matches_by_id: dict[UUID, ConceptMatch] = {}
        for alias in aliases:
            concept = alias.concept
            matches_by_id[concept.id] = ConceptMatch(
                concept_id=concept.id,
                code=concept.code,
                concept_type=concept.concept_type,
                scope=concept.scope,
                label_zh=concept.label_zh,
                label_en=concept.label_en,
            )
        candidates = tuple(sorted(matches_by_id.values(), key=lambda item: (item.code, str(item.concept_id))))
        return AliasResolution(
            ambiguous=len(candidates) > 1,
            candidates=candidates,
            selected=candidates[0] if len(candidates) == 1 else None,
        )

    def expand_concepts(
        self,
        *,
        concept_ids: Sequence[UUID],
        predicates: Iterable[str] | None = None,
        max_depth: int = 2,
    ) -> OntologySnapshot:
        self._validate_depth(max_depth)
        predicate_values = tuple(
            sorted(set(KnowledgeRelation.Predicate.values if predicates is None else predicates))
        )
        invalid = set(predicate_values) - set(KnowledgeRelation.Predicate.values)
        if invalid:
            raise ValidationError({"predicates": f"Unsupported predicates: {', '.join(sorted(invalid))}"})
        concepts = {
            item.id: item
            for item in self.visible_concepts().filter(id__in=concept_ids, status=KnowledgeStatus.APPROVED)
        }
        frontier = set(concepts)
        included_relations: dict[UUID, KnowledgeRelation] = {}
        for _depth in range(max_depth):
            if not frontier:
                break
            relations = list(
                self.visible_relations()
                .filter(
                    subject_concept_id__in=frontier,
                    predicate__in=predicate_values,
                    status=KnowledgeStatus.APPROVED,
                    object_concept__status=KnowledgeStatus.APPROVED,
                )
                .select_related("subject_concept", "object_concept")
            )
            next_frontier: set[UUID] = set()
            for relation in relations:
                object_concept = relation.object_concept
                if object_concept.organization_id not in {None, self.organization.id}:
                    continue
                included_relations[relation.id] = relation
                if object_concept.id not in concepts:
                    concepts[object_concept.id] = object_concept
                    next_frontier.add(object_concept.id)
            frontier = next_frontier
        concept_rows = sorted(concepts.values(), key=lambda item: (item.code, str(item.id)))
        relation_rows = sorted(
            included_relations.values(),
            key=lambda item: (
                item.subject_concept.code,
                item.predicate,
                item.object_concept.code,
                str(item.id),
            ),
        )
        evidence = self._snapshot_evidence(concept_rows=concept_rows, relation_rows=relation_rows)
        return OntologySnapshot(
            organization_id=self.organization.id,
            concept_versions=tuple(
                ConceptVersion(
                    concept_id=item.id,
                    code=item.code,
                    concept_type=item.concept_type,
                    label_zh=item.label_zh,
                    label_en=item.label_en,
                    version=item.version,
                    status=item.status,
                )
                for item in concept_rows
            ),
            relation_versions=tuple(
                RelationVersion(
                    relation_id=item.id,
                    subject_concept_id=item.subject_concept_id,
                    predicate=item.predicate,
                    object_concept_id=item.object_concept_id,
                    version=item.version,
                    status=item.status,
                )
                for item in relation_rows
            ),
            evidence_references=tuple(
                EvidenceReference(
                    evidence_id=item.id,
                    evidence_type=item.evidence_type,
                    source_object_type=item.source_object_type,
                    source_object_id=item.source_object_id,
                    source_url=item.source_url,
                    excerpt=item.excerpt,
                    captured_at=item.captured_at,
                    version=item.version,
                    status=item.status,
                )
                for item in evidence
            ),
            generated_at=timezone.now(),
        )

    def build_snapshot(self, *, concept_ids: Sequence[UUID], max_depth: int = 2) -> OntologySnapshot:
        return self.expand_concepts(concept_ids=concept_ids, max_depth=max_depth)

    def _snapshot_evidence(
        self,
        *,
        concept_rows: Sequence[KnowledgeConcept],
        relation_rows: Sequence[KnowledgeRelation],
    ) -> list[KnowledgeEvidence]:
        evidence_ids: set[UUID] = set()
        for concept in concept_rows:
            evidence_ids.update(concept.evidence.values_list("id", flat=True))
        for relation in relation_rows:
            evidence_ids.update(relation.evidence.values_list("id", flat=True))
        return list(
            self.visible_evidence()
            .filter(id__in=evidence_ids, status=KnowledgeStatus.APPROVED)
            .order_by("id")
        )

    @staticmethod
    def _validate_depth(max_depth: int) -> None:
        if not isinstance(max_depth, int) or isinstance(max_depth, bool) or max_depth < 0 or max_depth > 2:
            raise OntologyDepthError("Ontology expansion depth must be between 0 and 2")

    def submit_review(self, concept_id: UUID, *, actor: AbstractBaseUser, comment: str = "") -> KnowledgeConcept:
        return self._transition(concept_id, actor=actor, action=ReviewAction.SUBMIT, comment=comment)

    def approve(self, concept_id: UUID, *, actor: AbstractBaseUser, comment: str = "") -> KnowledgeConcept:
        return self._transition(concept_id, actor=actor, action=ReviewAction.APPROVE, comment=comment)

    def reject(self, concept_id: UUID, *, actor: AbstractBaseUser, comment: str) -> KnowledgeConcept:
        return self._transition(concept_id, actor=actor, action=ReviewAction.REJECT, comment=comment)

    def deprecate(self, concept_id: UUID, *, actor: AbstractBaseUser, comment: str = "") -> KnowledgeConcept:
        return self._transition(concept_id, actor=actor, action=ReviewAction.DEPRECATE, comment=comment)

    def _transition(
        self, concept_id: UUID, *, actor: AbstractBaseUser, action: str, comment: str
    ) -> KnowledgeConcept:
        concept = self.visible_concepts().get(id=concept_id)
        return KnowledgeReviewService(self.organization).transition(
            instance=concept, action=action, actor=actor, comment=comment
        )


def build_snapshot(
    *, organization: Organization, concept_ids: Sequence[UUID], max_depth: int = 2
) -> OntologySnapshot:
    return OntologyContextService(organization).build_snapshot(concept_ids=concept_ids, max_depth=max_depth)
