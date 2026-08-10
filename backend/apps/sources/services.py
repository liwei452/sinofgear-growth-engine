import hashlib
import ipaddress
from collections import defaultdict
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.assets.models import MaterialAsset
from apps.audit.services import record_audit_event, record_system_audit_event
from apps.jobs.models import Job
from apps.jobs.services import JobConflictError, JobService, StaleJobWorkerError

from .models import (
    IngestionBatch,
    IngestionRow,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
    _EVIDENCE_TRUSTED_ASSET_CAPABILITY,
    _INGESTION_RETENTION_TOMBSTONE_CAPABILITY,
    _evidence_trusted_asset_writes,
    _ingestion_batch_state_writes,
    evidence_service_writes,
    ingestion_row_service_writes,
    prepared_reference_sha256,
)


def normalize_source_url(url: str) -> str:
    if not isinstance(url, str) or not url:
        raise ValidationError("Source URL must be a non-empty HTTP(S) URL.")
    if any(ord(character) <= 32 for character in url):
        raise ValidationError("Source URL must not contain whitespace or control characters.")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as error:
        raise ValidationError("Source URL is invalid.") from error
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValidationError("Source URL must use HTTP or HTTPS.")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("Source URL must not contain credentials.")
    hostname = parsed.hostname
    if not hostname:
        raise ValidationError("Source URL must include a host.")
    try:
        try:
            normalized_host = f"[{ipaddress.IPv6Address(hostname).compressed.lower()}]"
        except ipaddress.AddressValueError:
            normalized_host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValidationError("Source URL host is invalid.") from error
    if not normalized_host:
        raise ValidationError("Source URL host is invalid.")
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = normalized_host if port is None or default_port else f"{normalized_host}:{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))


def evidence_fingerprint(*, original_text: str, source_url: str, platform: str) -> str:
    canonical = "\n".join(
        (
            platform.strip().upper(),
            normalize_source_url(source_url),
            " ".join(original_text.split()),
        )
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


SOURCE_EVIDENCE_SNAPSHOT_SCHEMA = "SOURCE_EVIDENCE_SNAPSHOT_V1"


def _snapshot_scalar(value):
    return None if value is None else str(value)


def canonical_source_evidence_snapshot(
    evidence: SourceEvidence, *, organization
) -> dict[str, object]:
    """Build the complete public-evidence audit input from trusted persisted rows."""
    evidence_id = getattr(evidence, "pk", evidence)
    persisted = (
        SourceEvidence.objects.select_related(
            "source_signal__source_content",
            "source_signal__source_content__monitoring_target",
            "source_signal__monitoring_target",
        )
        .get(pk=evidence_id, organization=organization)
    )
    signal = persisted.source_signal
    content = signal.source_content
    target = signal.monitoring_target or (
        content.monitoring_target if content is not None else None
    )
    return {
        "schema": SOURCE_EVIDENCE_SNAPSHOT_SCHEMA,
        "id": str(persisted.id),
        "organization_id": str(persisted.organization_id),
        "source_signal_id": str(persisted.source_signal_id),
        "source_content_id": str(signal.source_content_id) if signal.source_content_id else None,
        "monitoring_target_id": str(target.id) if target is not None else None,
        "monitoring_target_type": target.target_type if target is not None else None,
        "monitoring_target_collection_mode": (
            target.collection_mode if target is not None else None
        ),
        "monitoring_target_platform": target.platform if target is not None else None,
        "monitoring_target_external_reference": (
            target.external_reference if target is not None else None
        ),
        "monitoring_target_normalized_url": (
            target.normalized_url if target is not None else None
        ),
        "evidence_type": persisted.evidence_type,
        "original_text": persisted.original_text,
        "translated_text": persisted.translated_text,
        "translated_language": persisted.translated_language,
        "source_url": persisted.source_url,
        "platform": persisted.platform,
        "public_published_at": _snapshot_scalar(persisted.public_published_at),
        "captured_at": _snapshot_scalar(persisted.captured_at),
        "collection_method": persisted.collection_method,
        "language": persisted.language,
        "screenshot_asset_id": (
            str(persisted.screenshot_asset_id) if persisted.screenshot_asset_id else None
        ),
        "import_asset_id": str(persisted.import_asset_id) if persisted.import_asset_id else None,
        "content_hash": persisted.content_hash,
        "availability": persisted.availability,
        "retention_class": persisted.retention_class,
        "created_by_id": str(persisted.created_by_id) if persisted.created_by_id else None,
        "created_at": _snapshot_scalar(persisted.created_at),
        "updated_at": _snapshot_scalar(persisted.updated_at),
        "signal_type": signal.signal_type,
        "signal_platform": signal.platform,
        "signal_external_id": signal.external_id,
        "signal_captured_at": _snapshot_scalar(signal.captured_at),
        "signal_created_by_id": str(signal.created_by_id) if signal.created_by_id else None,
        "signal_created_at": _snapshot_scalar(signal.created_at),
        "signal_updated_at": _snapshot_scalar(signal.updated_at),
        "source_content_platform": content.platform if content is not None else None,
        "source_content_external_id": content.external_id if content is not None else None,
        "source_content_canonical_url": content.canonical_url if content is not None else None,
        "source_content_author_public_name": (
            content.author_public_name if content is not None else None
        ),
        "source_content_title": content.title if content is not None else None,
        "source_content_original_text": content.original_text if content is not None else None,
        "source_content_public_published_at": (
            _snapshot_scalar(content.public_published_at) if content is not None else None
        ),
        "source_content_language": content.language if content is not None else None,
        "source_content_captured_at": (
            _snapshot_scalar(content.captured_at) if content is not None else None
        ),
        "source_content_hash": content.content_hash if content is not None else None,
        "source_content_created_by_id": (
            str(content.created_by_id) if content is not None and content.created_by_id else None
        ),
        "source_content_created_at": (
            _snapshot_scalar(content.created_at) if content is not None else None
        ),
        "source_content_updated_at": (
            _snapshot_scalar(content.updated_at) if content is not None else None
        ),
    }


@dataclass(frozen=True)
class _LockedAsset:
    _instance: MaterialAsset
    id: object
    organization_id: object
    status: str
    asset_type: str

    @classmethod
    def capture(cls, asset: MaterialAsset):
        return cls(
            _instance=asset,
            id=asset.id,
            organization_id=asset.organization_id,
            status=asset.status,
            asset_type=asset.asset_type,
        )

    def resolve(self, *, organization, field_name, image_required=False):
        asset = self._instance
        unchanged = (
            asset.id == self.id
            and asset.organization_id == self.organization_id
            and asset.status == self.status
            and asset.asset_type == self.asset_type
        )
        valid = (
            unchanged
            and self.organization_id == organization.id
            and self.status == MaterialAsset.Status.ACTIVE
            and (
                not image_required
                or self.asset_type == MaterialAsset.AssetType.IMAGE
            )
        )
        if not valid:
            raise ValidationError(
                {field_name: "Evidence asset is unavailable for this organization."}
            )
        return asset


@dataclass(frozen=True)
class _LockedIngestionResources:
    monitoring_target: MonitoringTarget | None
    assets: Mapping[str, _LockedAsset]
    import_asset_id: str | None
    screenshot_asset_ids: frozenset[str]

    def screenshot_asset(self, asset_id, *, organization):
        if asset_id is None:
            return None
        asset_key = str(asset_id)
        locked = self.assets.get(asset_key)
        if locked is None or asset_key not in self.screenshot_asset_ids:
            raise ValidationError(
                {"screenshot_asset": "Evidence asset is unavailable for this organization."}
            )
        return locked.resolve(
            organization=organization,
            field_name="screenshot_asset",
            image_required=True,
        )

    def import_asset(self, *, organization):
        if self.import_asset_id is None:
            return None
        locked = self.assets.get(self.import_asset_id)
        if locked is None:
            raise ValidationError(
                {"import_asset": "Evidence asset is unavailable for this organization."}
            )
        return locked.resolve(
            organization=organization,
            field_name="import_asset",
        )


_INGESTION_LOCKED_ASSET_CAPABILITY = object()


class EvidenceService:
    _EVIDENCE_TYPES = {
        SourceEvidence.CollectionMethod.API: SourceEvidence.EvidenceType.PUBLIC_METADATA,
        SourceEvidence.CollectionMethod.URL: SourceEvidence.EvidenceType.PUBLIC_TEXT,
        SourceEvidence.CollectionMethod.PASTE: SourceEvidence.EvidenceType.PUBLIC_TEXT,
        SourceEvidence.CollectionMethod.SCREENSHOT: SourceEvidence.EvidenceType.SCREENSHOT,
        SourceEvidence.CollectionMethod.CSV: SourceEvidence.EvidenceType.IMPORT_ROW,
        SourceEvidence.CollectionMethod.JSON: SourceEvidence.EvidenceType.IMPORT_ROW,
    }

    @staticmethod
    @transaction.atomic
    def create(
        *,
        organization,
        signal,
        original_text,
        source_url,
        platform,
        collection_method,
        public_published_at,
        created_by,
        screenshot_asset=None,
        import_asset=None,
        evidence_type=None,
        language="",
    ):
        signal = EvidenceService._locked_signal(signal, organization=organization)
        screenshot_asset = EvidenceService._locked_asset(
            screenshot_asset, "screenshot_asset", organization
        )
        import_asset = EvidenceService._locked_asset(
            import_asset, "import_asset", organization
        )
        return EvidenceService._create_evidence(
            organization=organization,
            signal=signal,
            original_text=original_text,
            source_url=source_url,
            platform=platform,
            collection_method=collection_method,
            public_published_at=public_published_at,
            created_by=created_by,
            screenshot_asset=screenshot_asset,
            import_asset=import_asset,
            evidence_type=evidence_type,
            language=language,
        )

    @staticmethod
    @transaction.atomic
    def _create_from_locked_ingestion_assets(
        *,
        _capability=None,
        resources,
        screenshot_asset_id,
        organization,
        signal,
        original_text,
        source_url,
        platform,
        collection_method,
        public_published_at,
        created_by,
        evidence_type=None,
        language="",
    ):
        if _capability is not _INGESTION_LOCKED_ASSET_CAPABILITY:
            raise ValidationError(
                "Only the ingestion service may use the trusted locked asset path."
            )
        signal = EvidenceService._locked_signal(signal, organization=organization)
        screenshot_asset = resources.screenshot_asset(
            screenshot_asset_id,
            organization=organization,
        )
        import_asset = resources.import_asset(organization=organization)
        return EvidenceService._create_evidence(
            organization=organization,
            signal=signal,
            original_text=original_text,
            source_url=source_url,
            platform=platform,
            collection_method=collection_method,
            public_published_at=public_published_at,
            created_by=created_by,
            screenshot_asset=screenshot_asset,
            import_asset=import_asset,
            evidence_type=evidence_type,
            language=language,
            _trusted_asset_capability=_INGESTION_LOCKED_ASSET_CAPABILITY,
        )

    @staticmethod
    def _create_evidence(
        *,
        organization,
        signal,
        original_text,
        source_url,
        platform,
        collection_method,
        public_published_at,
        created_by,
        screenshot_asset,
        import_asset,
        evidence_type=None,
        language="",
        _trusted_asset_capability=None,
    ):
        normalized_url = normalize_source_url(source_url)
        fingerprint = evidence_fingerprint(
            original_text=original_text,
            source_url=normalized_url,
            platform=platform,
        )
        method = str(collection_method).strip().upper()
        if method not in SourceEvidence.CollectionMethod.values:
            raise ValidationError({"collection_method": "Unsupported evidence collection method."})
        if evidence_type is not None and evidence_type not in SourceEvidence.EvidenceType.values:
            raise ValidationError({"evidence_type": "Unsupported evidence type."})
        resolved_evidence_type = evidence_type or EvidenceService._EVIDENCE_TYPES.get(method)
        if resolved_evidence_type is None:
            raise ValidationError({"collection_method": "Unsupported evidence collection method."})
        trusted_asset_fields = {
            field_name: asset
            for field_name, asset in {
                "screenshot_asset": screenshot_asset,
                "import_asset": import_asset,
            }.items()
            if asset is not None
        }
        if (
            _trusted_asset_capability is not None
            and _trusted_asset_capability is not _INGESTION_LOCKED_ASSET_CAPABILITY
        ):
            raise ValidationError("Invalid trusted locked asset capability.")
        asset_context = nullcontext()
        if _trusted_asset_capability is _INGESTION_LOCKED_ASSET_CAPABILITY:
            asset_context = _evidence_trusted_asset_writes(
                _capability=_EVIDENCE_TRUSTED_ASSET_CAPABILITY,
                **trusted_asset_fields,
            )
        with asset_context, evidence_service_writes():
            evidence, _ = SourceEvidence.objects.get_or_create(
                organization=organization,
                content_hash=fingerprint,
                defaults={
                    "source_signal": signal,
                    "evidence_type": resolved_evidence_type,
                    "original_text": original_text,
                    "source_url": normalized_url,
                    "platform": platform,
                    "collection_method": method,
                    "public_published_at": public_published_at,
                    "created_by": created_by,
                    "screenshot_asset": screenshot_asset,
                    "import_asset": import_asset,
                    "language": language,
                    "retention_class": SourceEvidence.RetentionClass.TRANSIENT_30D,
                },
            )
        return evidence

    @staticmethod
    def _locked_signal(signal, *, organization):
        signal_id = getattr(signal, "pk", None)
        try:
            locked = SourceSignal.objects.select_for_update().filter(
                pk=signal_id, organization=organization
            ).first()
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {"signal": "Source signal is unavailable for this organization."}
            ) from error
        if locked is None:
            raise ValidationError(
                {"signal": "Source signal is unavailable for this organization."}
            )
        return locked

    @staticmethod
    def _locked_asset(asset, field_name, organization):
        if asset is None:
            return None
        try:
            locked = MaterialAsset.objects.select_for_update().filter(
                pk=getattr(asset, "pk", None), organization=organization
            ).first()
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {field_name: "Evidence asset is unavailable for this organization."}
            ) from error
        if locked is None:
            raise ValidationError(
                {field_name: "Evidence asset is unavailable for this organization."}
            )
        return locked

    @staticmethod
    @transaction.atomic
    def protect_confirmed(*, organization, evidence_ids):
        """Promote selected organization evidence without weakening stronger protection."""
        requested = {getattr(item, "pk", item) for item in evidence_ids}
        if not requested:
            raise ValidationError({"evidence": "At least one evidence record is required."})
        rows = list(
            SourceEvidence.objects.select_for_update()
            .filter(organization=organization, pk__in=requested)
            .order_by("pk")
        )
        if {row.pk for row in rows} != requested:
            raise ValidationError(
                {"evidence": "Evidence is unavailable for this organization."}
            )
        for row in rows:
            if row.retention_class == SourceEvidence.RetentionClass.TRANSIENT_30D:
                row.retention_class = SourceEvidence.RetentionClass.CONFIRMED
                with evidence_service_writes():
                    row.save(update_fields=["retention_class", "updated_at"])
        return rows


create = EvidenceService.create


RETENTION_POLICY_VERSION = "SOURCE_EVIDENCE_RETENTION_V1"
RETENTION_JOB_SCHEMA = "SOURCE_RETENTION_JOB_V1"
RETENTION_AUDIT_ID_LIMIT = 100


def retention_cleanup_job_snapshot(*, organization, cutoff) -> dict[str, str]:
    if not isinstance(cutoff, datetime) or timezone.is_naive(cutoff):
        raise ValueError("Retention cutoff must be a timezone-aware datetime.")
    return {
        "schema": RETENTION_JOB_SCHEMA,
        "organization_id": str(organization.id),
        "cutoff": cutoff.isoformat(),
        "policy_version": RETENTION_POLICY_VERSION,
    }


@dataclass(frozen=True)
class RetentionResult:
    redacted: int = 0
    deleted_text: int = 0
    anonymized_actors: int = 0
    protected: int = 0
    failures: int = 0
    no_op: int = 0
    protected_reasons: Mapping[str, int] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def as_dict(self) -> dict[str, int]:
        return {
            "redacted": self.redacted,
            "deleted_text": self.deleted_text,
            "anonymized_actors": self.anonymized_actors,
            "protected": self.protected,
            "failures": self.failures,
            "no_op": self.no_op,
        }


@dataclass(frozen=True)
class _RetentionComponent:
    candidate_ids: tuple[object, ...]
    evidence_ids: tuple[object, ...]
    asset_ids: tuple[object, ...]
    asset_batch_ids: tuple[object, ...]
    shares_source_content: bool
    has_unproven_screenshot_identity: bool


class RetentionService:
    _HISTORY_ITERATOR_CHUNK_SIZE = 500
    _ACTIVE_JOB_STATUSES = frozenset(
        {Job.Status.QUEUED, Job.Status.RUNNING, Job.Status.RETRY_QUEUED}
    )
    _RAW_TEXT_KEYS = frozenset({"original_text", "translated_text", "text"})
    _RAW_ACTOR_KEYS = frozenset(
        {"author_name", "author_public_name", "author_handle", "handle"}
    )
    _RAW_ASSET_KEYS = frozenset({"screenshot_asset_id", "import_asset_id"})
    _RETENTION_MARKER = MappingProxyType(
        {
            "schema": "SOURCE_RETENTION_TOMBSTONE_V1",
            "status": "REDACTED_BY_RETENTION",
            "reason": "TRANSIENT_30D_EXPIRED",
        }
    )

    @staticmethod
    def _authorize(*, organization, actor) -> None:
        if actor is None:
            return
        from apps.identity.models import Membership
        from apps.identity.permissions import PermissionCode
        from apps.identity.services import get_active_membership, require_permission

        try:
            membership = get_active_membership(user=actor)
        except Membership.DoesNotExist as error:
            raise PermissionDenied("An active source-management membership is required.") from error
        if membership.organization_id != organization.id:
            raise PermissionDenied("An active source-management membership is required.")
        require_permission(
            membership=membership,
            permission=PermissionCode.SOURCES_MANAGE,
        )

    @staticmethod
    def _snapshot_evidence_ids(snapshot) -> set[str]:
        if not isinstance(snapshot, dict):
            return set()
        raw_ids = snapshot.get("evidence_ids", [])
        if not isinstance(raw_ids, list):
            raw_ids = []
        result = {
            str(item)
            for item in raw_ids
            if isinstance(item, (str, int))
        }
        evidence = snapshot.get("evidence", [])
        if isinstance(evidence, list):
            result.update(
                str(row["id"])
                for row in evidence
                if isinstance(row, dict) and row.get("id")
            )
        return result

    @staticmethod
    def _active_analysis_evidence_ids(*, organization) -> set[str]:
        from apps.ai.models import AIRun

        job_snapshots = Job.objects.filter(
            organization=organization,
            type=Job.Type.LEAD_ANALYZE,
        ).values_list("input_snapshot", flat=True)
        run_snapshots = AIRun.objects.filter(
            organization=organization,
            job__type=Job.Type.LEAD_ANALYZE,
        ).values_list("input_snapshot", flat=True)
        protected_ids: set[str] = set()
        for snapshots in (job_snapshots, run_snapshots):
            for snapshot in snapshots.iterator(
                chunk_size=RetentionService._HISTORY_ITERATOR_CHUNK_SIZE
            ):
                protected_ids.update(
                    RetentionService._snapshot_evidence_ids(snapshot)
                )
        return protected_ids

    @staticmethod
    def _validate_relationships(row: SourceEvidence, *, organization) -> None:
        if row.source_signal.organization_id != organization.id:
            raise ValidationError("Evidence source signal has inconsistent ownership.")
        content = row.source_signal.source_content
        if content is not None and content.organization_id != organization.id:
            raise ValidationError("Evidence source content has inconsistent ownership.")
        for field_name in ("screenshot_asset", "import_asset"):
            asset = getattr(row, field_name)
            if asset is not None and asset.organization_id != organization.id:
                raise ValidationError(f"Evidence {field_name} has inconsistent ownership.")
        for link in row.candidate_links.select_related(
            "candidate", "source_signal"
        ).order_by("pk"):
            if (
                link.organization_id != organization.id
                or link.candidate.organization_id != organization.id
                or link.source_signal_id != row.source_signal_id
            ):
                raise ValidationError("Evidence candidate history is inconsistent.")

    @staticmethod
    def _protection_reason(
        row: SourceEvidence, *, active_ids: set[str]
    ) -> str | None:
        if row.retention_class != SourceEvidence.RetentionClass.TRANSIENT_30D:
            return "NON_TRANSIENT_RETENTION_CLASS"
        if str(row.id) in active_ids:
            return "IMMUTABLE_ANALYSIS_REFERENCE"
        links = row.candidate_links
        if links.filter(
            candidate__status__in=[
                "REVIEWED",
                "READY_FOR_HANDOFF",
                "HANDED_OFF",
            ]
        ).exists():
            return "REVIEW_OR_HANDOFF_STATE"
        if links.filter(candidate__reviews__action__in=["CONFIRM", "CORRECT"]).exists():
            return "HUMAN_REVIEW_HISTORY"
        if links.filter(
            candidate__analysis_bindings__job__status__in=(
                RetentionService._ACTIVE_JOB_STATUSES
            )
        ).exists():
            return "ACTIVE_ANALYSIS_BINDING"
        return None

    @staticmethod
    def _has_shared_raw_copy_dependency(
        row: SourceEvidence,
        *,
        organization,
        ingestion_rows: list[IngestionRow],
        active_ingestion_fingerprints: set[str],
        has_unparseable_active_input: bool,
    ) -> bool:
        if (
            has_unparseable_active_input
            or row.content_hash in active_ingestion_fingerprints
        ):
            return True
        batch_ids = {ingestion_row.batch_id for ingestion_row in ingestion_rows}
        if not batch_ids:
            return False
        if IngestionBatch.objects.filter(
            organization=organization,
            pk__in=batch_ids,
            job__status__in=RetentionService._ACTIVE_JOB_STATUSES,
        ).exists():
            return True
        return False

    @staticmethod
    def _retention_components(
        *, organization, candidate_ids
    ) -> list[_RetentionComponent]:
        """Build only candidate-reachable transitive raw-data components."""
        candidate_ids = tuple(candidate_ids)
        if not candidate_ids:
            return []
        candidate_set = set(candidate_ids)
        adjacency: dict[tuple[str, object], set[tuple[str, object]]] = defaultdict(set)
        unproven_nodes: set[tuple[str, object]] = set()

        def connect(left, right):
            if left[1] is None or right[1] is None:
                return
            adjacency[left].add(right)
            adjacency[right].add(left)

        def chunks(values):
            ordered = sorted(set(values), key=str)
            size = RetentionService._HISTORY_ITERATOR_CHUNK_SIZE
            for offset in range(0, len(ordered), size):
                yield ordered[offset : offset + size]

        discovered = {
            "e": set(candidate_ids),
            "a": set(),
            "c": set(),
            "b": set(),
        }
        processed = {kind: set() for kind in discovered}

        def discover(kind, value):
            if value is not None:
                discovered[kind].add(value)

        def consume_rows(queryset):
            for batch_id, evidence_id, screenshot_id, unproven in queryset:
                batch_node = ("b", batch_id)
                evidence_node = ("e", evidence_id)
                asset_node = ("a", screenshot_id)
                connect(batch_node, evidence_node)
                connect(batch_node, asset_node)
                discover("b", batch_id)
                discover("e", evidence_id)
                discover("a", screenshot_id)
                if unproven:
                    unproven_nodes.add(batch_node)
                    if evidence_id is not None:
                        unproven_nodes.add(evidence_node)

        while any(discovered[kind] - processed[kind] for kind in discovered):
            pending_evidence = discovered["e"] - processed["e"]
            for chunk in chunks(pending_evidence):
                for evidence_id, content_id, screenshot_id, import_id in (
                    SourceEvidence.objects.filter(
                        organization=organization,
                        pk__in=chunk,
                    )
                    .order_by("pk")
                    .values_list(
                        "pk",
                        "source_signal__source_content_id",
                        "screenshot_asset_id",
                        "import_asset_id",
                    )
                ):
                    evidence_node = ("e", evidence_id)
                    connect(evidence_node, ("c", content_id))
                    connect(evidence_node, ("a", screenshot_id))
                    connect(evidence_node, ("a", import_id))
                    discover("c", content_id)
                    discover("a", screenshot_id)
                    discover("a", import_id)
                consume_rows(
                    IngestionRow.objects.filter(
                        organization=organization,
                        source_evidence_id__in=chunk,
                    )
                    .order_by("batch_id", "row_number", "pk")
                    .values_list(
                        "batch_id",
                        "source_evidence_id",
                        "request_screenshot_asset_id",
                        "request_screenshot_identity_unproven",
                    )
                )
            processed["e"].update(pending_evidence)

            pending_assets = discovered["a"] - processed["a"]
            for chunk in chunks(pending_assets):
                for evidence_id, screenshot_id, import_id in (
                    SourceEvidence.objects.filter(organization=organization)
                    .filter(
                        Q(screenshot_asset_id__in=chunk)
                        | Q(import_asset_id__in=chunk)
                    )
                    .order_by("pk")
                    .values_list("pk", "screenshot_asset_id", "import_asset_id")
                ):
                    evidence_node = ("e", evidence_id)
                    connect(evidence_node, ("a", screenshot_id))
                    connect(evidence_node, ("a", import_id))
                    discover("e", evidence_id)
                for batch_id, import_id in (
                    IngestionBatch.objects.filter(
                        organization=organization,
                        request_import_asset_id__in=chunk,
                    )
                    .order_by("pk")
                    .values_list("pk", "request_import_asset_id")
                ):
                    connect(("b", batch_id), ("a", import_id))
                    discover("b", batch_id)
                consume_rows(
                    IngestionRow.objects.filter(
                        organization=organization,
                        request_screenshot_asset_id__in=chunk,
                    )
                    .order_by("batch_id", "row_number", "pk")
                    .values_list(
                        "batch_id",
                        "source_evidence_id",
                        "request_screenshot_asset_id",
                        "request_screenshot_identity_unproven",
                    )
                )
            processed["a"].update(pending_assets)

            pending_contents = discovered["c"] - processed["c"]
            for chunk in chunks(pending_contents):
                for evidence_id, content_id in (
                    SourceEvidence.objects.filter(
                        organization=organization,
                        source_signal__source_content_id__in=chunk,
                    )
                    .order_by("pk")
                    .values_list("pk", "source_signal__source_content_id")
                ):
                    connect(("e", evidence_id), ("c", content_id))
                    discover("e", evidence_id)
            processed["c"].update(pending_contents)

            pending_batches = discovered["b"] - processed["b"]
            for chunk in chunks(pending_batches):
                for batch_id, import_id in (
                    IngestionBatch.objects.filter(
                        organization=organization,
                        pk__in=chunk,
                    )
                    .order_by("pk")
                    .values_list("pk", "request_import_asset_id")
                ):
                    connect(("b", batch_id), ("a", import_id))
                    discover("a", import_id)
                consume_rows(
                    IngestionRow.objects.filter(
                        organization=organization,
                        batch_id__in=chunk,
                    )
                    .order_by("batch_id", "row_number", "pk")
                    .values_list(
                        "batch_id",
                        "source_evidence_id",
                        "request_screenshot_asset_id",
                        "request_screenshot_identity_unproven",
                    )
                )
            processed["b"].update(pending_batches)

        seen = set()
        components = []
        for candidate_id in sorted(candidate_set, key=str):
            seed = ("e", candidate_id)
            if seed in seen:
                continue
            frontier = [seed]
            nodes = set()
            while frontier:
                node = frontier.pop()
                if node in nodes:
                    continue
                nodes.add(node)
                frontier.extend(adjacency.get(node, ()))
            seen.update(nodes)
            evidence_ids = {value for kind, value in nodes if kind == "e"}
            component_candidates = evidence_ids & candidate_set
            if not component_candidates:
                continue
            content_nodes = {node for node in nodes if node[0] == "c"}
            components.append(
                _RetentionComponent(
                    candidate_ids=tuple(sorted(component_candidates, key=str)),
                    evidence_ids=tuple(sorted(evidence_ids, key=str)),
                    asset_ids=tuple(
                        sorted(
                            {value for kind, value in nodes if kind == "a"},
                            key=str,
                        )
                    ),
                    asset_batch_ids=tuple(
                        sorted(
                            {value for kind, value in nodes if kind == "b"},
                            key=str,
                        )
                    ),
                    shares_source_content=any(
                        len(adjacency[node]) > 1 for node in content_nodes
                    ),
                    has_unproven_screenshot_identity=bool(
                        nodes.intersection(unproven_nodes)
                    ),
                )
            )
        return sorted(
            components,
            key=lambda component: str(component.evidence_ids[0]),
        )

    @staticmethod
    def _active_ingestion_raw_fingerprints(
        *, organization
    ) -> tuple[set[str], bool]:
        references = IngestionBatch.objects.filter(
            organization=organization,
            job__type=Job.Type.SOURCE_IMPORT,
            job__status__in=RetentionService._ACTIVE_JOB_STATUSES,
        ).values_list("input_reference", flat=True)
        fingerprints: set[str] = set()
        unparseable = False
        for reference in references:
            rows = reference.get("rows") if isinstance(reference, dict) else None
            if not isinstance(rows, list):
                unparseable = True
                continue
            for raw in rows:
                if not isinstance(raw, dict):
                    unparseable = True
                    continue
                if "retention" in raw:
                    continue
                try:
                    fingerprints.add(
                        evidence_fingerprint(
                            original_text=raw["original_text"],
                            source_url=raw["source_url"],
                            platform=raw["platform"],
                        )
                    )
                except (KeyError, TypeError, ValidationError):
                    unparseable = True
        return fingerprints, unparseable

    @staticmethod
    def _tombstone_raw_json(value) -> tuple[object, int, int]:
        deleted_text = 0
        anonymized = 0
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                if key in RetentionService._RAW_TEXT_KEYS:
                    deleted_text += int(bool(item))
                    result[key] = ""
                elif key in RetentionService._RAW_ACTOR_KEYS:
                    anonymized += int(bool(item))
                    result[key] = ""
                elif key in RetentionService._RAW_ASSET_KEYS:
                    result[key] = None
                else:
                    result[key], text_count, actor_count = (
                        RetentionService._tombstone_raw_json(item)
                    )
                    deleted_text += text_count
                    anonymized += actor_count
            return result, deleted_text, anonymized
        if isinstance(value, list):
            result = []
            for item in value:
                redacted, text_count, actor_count = (
                    RetentionService._tombstone_raw_json(item)
                )
                result.append(redacted)
                deleted_text += text_count
                anonymized += actor_count
            return result, deleted_text, anonymized
        return value, 0, 0

    @staticmethod
    def _contains_raw_json(value) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if (
                    key
                    in (
                        RetentionService._RAW_TEXT_KEYS
                        | RetentionService._RAW_ACTOR_KEYS
                        | RetentionService._RAW_ASSET_KEYS
                    )
                    and item not in (None, "")
                ):
                    return True
                if RetentionService._contains_raw_json(item):
                    return True
            return False
        if isinstance(value, list):
            return any(RetentionService._contains_raw_json(item) for item in value)
        return False

    @staticmethod
    def _redact_locked(
        row: SourceEvidence,
        *,
        organization,
        ingestion_rows: list[IngestionRow],
    ) -> tuple[int, int]:
        deleted_text = int(bool(row.original_text)) + int(bool(row.translated_text))
        row.original_text = ""
        row.translated_text = ""
        row.translated_language = ""
        row.screenshot_asset = None
        row.import_asset = None
        row.availability = SourceEvidence.Availability.REDACTED_BY_RETENTION
        with evidence_service_writes():
            row.save(
                update_fields=[
                    "original_text",
                    "translated_text",
                    "translated_language",
                    "screenshot_asset",
                    "import_asset",
                    "availability",
                    "updated_at",
                ]
            )

        content = row.source_signal.source_content
        anonymized = 0
        if content is not None and not SourceEvidence.objects.filter(
            organization=organization,
            source_signal__source_content=content,
        ).exclude(
            availability=SourceEvidence.Availability.REDACTED_BY_RETENTION
        ).exists():
            anonymized = int(bool(content.author_public_name))
            deleted_text += int(bool(content.original_text))
            content.author_public_name = ""
            content.original_text = ""
            content.save(
                update_fields=["author_public_name", "original_text", "updated_at"]
            )

        for ingestion_row in ingestion_rows:
            normalized_input, text_count, actor_count = (
                RetentionService._tombstone_raw_json(
                    deepcopy(ingestion_row.normalized_input)
                )
            )
            normalized_input["retention"] = dict(
                RetentionService._RETENTION_MARKER,
                source_evidence_id=str(row.id),
            )
            ingestion_row.normalized_input = normalized_input
            with ingestion_row_service_writes():
                ingestion_row.save(
                    update_fields=["normalized_input", "updated_at"]
                )
            deleted_text += text_count
            anonymized += actor_count

        return deleted_text, anonymized

    @staticmethod
    def _tombstone_batches_locked(
        *,
        organization,
        ingestion_rows: list[IngestionRow],
        ingestion_batches: list[IngestionBatch],
    ) -> tuple[int, int]:
        deleted_text = 0
        anonymized = 0
        rows_by_batch: dict[object, dict[int, object]] = {}
        for ingestion_row in ingestion_rows:
            rows_by_batch.setdefault(ingestion_row.batch_id, {})[
                ingestion_row.row_number
            ] = ingestion_row.source_evidence_id
        for batch in ingestion_batches:
            selected_rows = rows_by_batch.get(batch.id, {})
            if not selected_rows:
                continue
            reference_rows = (
                batch.input_reference.get("rows", [])
                if isinstance(batch.input_reference, dict)
                else []
            )
            text_count = 0
            actor_count = 0
            for reference_row in reference_rows:
                if (
                    isinstance(reference_row, dict)
                    and reference_row.get("row_number") in selected_rows
                ):
                    _redacted, row_text_count, row_actor_count = (
                        RetentionService._tombstone_raw_json(
                            deepcopy(reference_row)
                        )
                    )
                    text_count += row_text_count
                    actor_count += row_actor_count
            persisted = IngestionBatch.objects.filter(
                pk=batch.pk,
                organization=organization,
            )._service_tombstone_input_reference(
                _capability=_INGESTION_RETENTION_TOMBSTONE_CAPABILITY,
                evidence_ids_by_row=selected_rows,
            )
            batch.input_reference = persisted["input_reference"]
            deleted_text += text_count
            anonymized += actor_count
        return deleted_text, anonymized

    @staticmethod
    def cleanup(
        *,
        organization,
        cutoff,
        actor=None,
    ) -> RetentionResult:
        if actor is None:
            raise PermissionDenied(
                "Actorless retention cleanup is restricted to the claimed system path."
            )
        return RetentionService._cleanup(
            organization=organization,
            cutoff=cutoff,
            actor=actor,
        )

    @staticmethod
    def cleanup_owned(
        *,
        organization,
        cutoff,
        actor,
        job_id,
        claim_token,
    ) -> RetentionResult:
        return RetentionService._cleanup(
            organization=organization,
            cutoff=cutoff,
            actor=actor,
            job_id=job_id,
            claim_token=claim_token,
        )

    @staticmethod
    @transaction.atomic
    def _cleanup(
        *,
        organization,
        cutoff,
        actor,
        job_id=None,
        claim_token=None,
    ) -> RetentionResult:
        if not isinstance(cutoff, datetime) or timezone.is_naive(cutoff):
            raise ValueError("Retention cutoff must be a timezone-aware datetime.")
        RetentionService._authorize(organization=organization, actor=actor)
        from apps.identity.services import lock_organization_scope

        organization = lock_organization_scope(organization=organization)
        if actor is None and (job_id is None or claim_token is None):
            raise PermissionDenied(
                "Actorless retention cleanup requires a claimed retention job."
            )
        if (job_id is None) != (claim_token is None):
            raise ValidationError("Retention worker ownership is incomplete.")
        if job_id is not None:
            owned_job = JobService._locked(job_id, organization=organization)
            JobService._require_owner(owned_job, claim_token)
            if owned_job.type != Job.Type.RETENTION_CLEANUP:
                raise ValidationError("Retention worker owns the wrong job type.")

        active_ids = RetentionService._active_analysis_evidence_ids(
            organization=organization
        )
        (
            active_ingestion_fingerprints,
            has_unparseable_active_input,
        ) = RetentionService._active_ingestion_raw_fingerprints(
            organization=organization
        )
        candidate_ids = list(
            SourceEvidence.objects.filter(
                organization=organization,
                captured_at__lte=cutoff,
            )
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        counts = RetentionResult()
        changed_ids: list[str] = []
        failed_ids: list[str] = []
        protected_reasons: dict[str, int] = {}

        values = counts.as_dict()
        components = RetentionService._retention_components(
            organization=organization,
            candidate_ids=candidate_ids,
        )
        for component in components:
            component_ids = component.evidence_ids
            values_before = dict(values)
            changed_count_before = len(changed_ids)
            protected_reasons_before = dict(protected_reasons)
            try:
                with transaction.atomic():
                    locked_assets = list(
                        MaterialAsset.objects.select_for_update()
                        .filter(
                            organization=organization,
                            pk__in=component.asset_ids,
                        )
                        .order_by("pk")
                    )
                    component_batch_ids = sorted(
                        set(component.asset_batch_ids)
                        | set(
                            IngestionRow.objects.filter(
                                organization=organization,
                                source_evidence_id__in=component_ids,
                            ).values_list("batch_id", flat=True)
                        ),
                        key=str,
                    )
                    ingestion_batches = list(
                        IngestionBatch.objects.select_for_update()
                        .select_related("job")
                        .filter(
                            organization=organization,
                            pk__in=component_batch_ids,
                        )
                        .order_by("pk")
                    )
                    shared_batch_ids = set(component.asset_batch_ids)
                    evidence_rows = list(
                        SourceEvidence.objects.select_for_update()
                        .select_related(
                            "source_signal__source_content",
                            "screenshot_asset",
                            "import_asset",
                        )
                        .filter(pk__in=component_ids, organization=organization)
                        .order_by("pk")
                    )
                    if len(evidence_rows) != len(component_ids):
                        raise ValidationError(
                            "Retention component changed after organization lock."
                        )
                    ingestion_rows = list(
                        IngestionRow.objects.select_for_update()
                        .filter(
                            Q(source_evidence_id__in=component_ids)
                            | Q(batch_id__in=shared_batch_ids),
                            organization=organization,
                        )
                        .order_by("batch_id", "row_number", "pk")
                    )
                    component_set = set(component_ids)
                    rows_by_evidence: dict[object, list[IngestionRow]] = defaultdict(list)
                    rows_by_batch: dict[object, list[IngestionRow]] = defaultdict(list)
                    for ingestion_row in ingestion_rows:
                        rows_by_batch[ingestion_row.batch_id].append(ingestion_row)
                        if ingestion_row.source_evidence_id in component_set:
                            rows_by_evidence[ingestion_row.source_evidence_id].append(
                                ingestion_row
                            )

                    group_reason = (
                        "SHARED_SCREENSHOT_ASSET_IDENTITY_UNPROVEN"
                        if component.has_unproven_screenshot_identity
                        else None
                    )
                    if len(locked_assets) != len(component.asset_ids):
                        group_reason = "SHARED_IMPORT_ASSET_INCONSISTENT"
                    for batch in ingestion_batches:
                        if batch.id not in shared_batch_ids:
                            continue
                        if (
                            batch.job_id is not None
                            and batch.job.status
                            in RetentionService._ACTIVE_JOB_STATUSES
                        ):
                            group_reason = "SHARED_RAW_GROUP_ACTIVE"
                            break
                        reference = batch.input_reference
                        if batch.source_type == IngestionBatch.SourceType.API:
                            group_reason = "SHARED_IMPORT_ASSET_INCONSISTENT"
                        else:
                            from .importers import validate_prepared_import_reference

                            try:
                                validate_prepared_import_reference(
                                    reference,
                                    source_type=batch.source_type,
                                )
                            except ValidationError:
                                group_reason = "SHARED_IMPORT_ASSET_INCONSISTENT"
                        reference_rows = (
                            reference.get("rows", [])
                            if isinstance(reference, dict)
                            else []
                        )
                        reference_numbers = {
                            item.get("row_number")
                            for item in reference_rows
                            if isinstance(item, dict)
                        }
                        linked_rows = rows_by_batch.get(batch.id, [])
                        linked_numbers = {item.row_number for item in linked_rows}
                        current_asset_id = (
                            reference.get("import_asset_id")
                            if isinstance(reference, dict)
                            else None
                        )
                        is_tombstoned = (
                            isinstance(reference, dict)
                            and "retention" in reference
                        )
                        if (
                            reference_numbers != linked_numbers
                            or (
                                batch.request_import_asset_id is not None
                                and not is_tombstoned
                                and str(current_asset_id)
                                != str(batch.request_import_asset_id)
                            )
                            or any(
                                item.source_evidence_id not in component_set
                                for item in linked_rows
                            )
                        ):
                            group_reason = "SHARED_IMPORT_ASSET_INCONSISTENT"
                            break

                    raw_content_ids = {
                        evidence.source_signal.source_content_id
                        for evidence in evidence_rows
                        if evidence.source_signal.source_content is not None
                        and (
                            evidence.source_signal.source_content.original_text
                            or evidence.source_signal.source_content.author_public_name
                        )
                    }
                    shared_content = component.shares_source_content
                    if raw_content_ids:
                        content_members = list(
                            SourceEvidence.objects.filter(
                                organization=organization,
                                source_signal__source_content_id__in=raw_content_ids,
                            ).values_list(
                                "source_signal__source_content_id", "id"
                            )
                        )
                        members_by_content: dict[object, set[object]] = defaultdict(set)
                        for content_id, evidence_id in content_members:
                            members_by_content[content_id].add(evidence_id)
                        if any(
                            not members <= component_set
                            for members in members_by_content.values()
                        ):
                            group_reason = (
                                group_reason
                                or "SHARED_SOURCE_CONTENT_GROUP_PROTECTED"
                            )

                    individual_reasons: dict[object, str] = {}
                    not_expired_ids: set[object] = set()
                    for evidence in evidence_rows:
                        if evidence.captured_at >= cutoff:
                            not_expired_ids.add(evidence.id)
                            continue
                        RetentionService._validate_relationships(
                            evidence, organization=organization
                        )
                        reason = RetentionService._protection_reason(
                            evidence, active_ids=active_ids
                        )
                        if reason is None and RetentionService._has_shared_raw_copy_dependency(
                            evidence,
                            organization=organization,
                            ingestion_rows=rows_by_evidence.get(evidence.id, []),
                            active_ingestion_fingerprints=(
                                active_ingestion_fingerprints
                            ),
                            has_unparseable_active_input=(
                                has_unparseable_active_input
                            ),
                        ):
                            reason = "SHARED_OR_ACTIVE_RAW_COPY"
                        if reason is not None:
                            individual_reasons[evidence.id] = reason

                    is_shared_group = bool(component.asset_ids or shared_content)
                    if (
                        is_shared_group
                        and (individual_reasons or not_expired_ids)
                        and group_reason is None
                    ):
                        group_reason = (
                            "SHARED_RAW_GROUP_NOT_ALL_ELIGIBLE"
                        )
                    if group_reason is not None:
                        for evidence in evidence_rows:
                            reason = individual_reasons.get(evidence.id)
                            if reason is None and evidence.id in not_expired_ids:
                                reason = "RETENTION_NOT_EXPIRED"
                            reason = reason or group_reason
                            values["protected"] += 1
                            protected_reasons[reason] = (
                                protected_reasons.get(reason, 0) + 1
                            )
                        continue
                    if individual_reasons:
                        for evidence in evidence_rows:
                            reason = individual_reasons.get(evidence.id)
                            if reason is None:
                                continue
                            values["protected"] += 1
                            protected_reasons[reason] = (
                                protected_reasons.get(reason, 0) + 1
                            )
                        evidence_rows = [
                            evidence
                            for evidence in evidence_rows
                            if evidence.id not in individual_reasons
                        ]
                    if not_expired_ids:
                        values["no_op"] += len(not_expired_ids)
                        evidence_rows = [
                            evidence
                            for evidence in evidence_rows
                            if evidence.id not in not_expired_ids
                        ]
                    if not evidence_rows:
                        continue

                    actionable_evidence: list[SourceEvidence] = []
                    actionable_rows: list[IngestionRow] = []
                    batch_by_id = {batch.id: batch for batch in ingestion_batches}
                    for evidence in evidence_rows:
                        linked_rows = rows_by_evidence.get(evidence.id, [])
                        linked_raw_copy = any(
                            RetentionService._contains_raw_json(item.normalized_input)
                            for item in linked_rows
                        )
                        for ingestion_row in linked_rows:
                            batch = batch_by_id.get(ingestion_row.batch_id)
                            if batch is None or not isinstance(
                                batch.input_reference, dict
                            ):
                                continue
                            reference_row = next(
                                (
                                    item
                                    for item in batch.input_reference.get("rows", [])
                                    if isinstance(item, dict)
                                    and item.get("row_number")
                                    == ingestion_row.row_number
                                ),
                                None,
                            )
                            linked_raw_copy = linked_raw_copy or (
                                reference_row is not None
                                and RetentionService._contains_raw_json(reference_row)
                            )
                        content = evidence.source_signal.source_content
                        if content is not None:
                            linked_raw_copy = linked_raw_copy or bool(
                                content.original_text or content.author_public_name
                            )
                        was_redacted = (
                            evidence.availability
                            == SourceEvidence.Availability.REDACTED_BY_RETENTION
                        )
                        if was_redacted and not linked_raw_copy:
                            values["no_op"] += 1
                            continue
                        actionable_evidence.append(evidence)
                        actionable_rows.extend(linked_rows)
                        deleted_text, anonymized = RetentionService._redact_locked(
                            evidence,
                            organization=organization,
                            ingestion_rows=linked_rows,
                        )
                        values["redacted"] += int(not was_redacted)
                        values["deleted_text"] += deleted_text
                        values["anonymized_actors"] += anonymized
                        changed_ids.append(str(evidence.id))

                    if actionable_evidence:
                        deleted_text, anonymized = (
                            RetentionService._tombstone_batches_locked(
                                organization=organization,
                                ingestion_rows=actionable_rows,
                                ingestion_batches=ingestion_batches,
                            )
                        )
                        values["deleted_text"] += deleted_text
                        values["anonymized_actors"] += anonymized
            except (DatabaseError, ValidationError):
                values = values_before
                del changed_ids[changed_count_before:]
                protected_reasons = protected_reasons_before
                values["failures"] += len(component_ids)
                failed_ids.extend(str(evidence_id) for evidence_id in component_ids)

        result = RetentionResult(
            **values,
            protected_reasons=MappingProxyType(dict(sorted(protected_reasons.items()))),
        )
        if changed_ids or result.failures:
            bounded_changed = changed_ids[:RETENTION_AUDIT_ID_LIMIT]
            remaining = RETENTION_AUDIT_ID_LIMIT - len(bounded_changed)
            bounded_failed = failed_ids[:remaining]
            audit_values = {
                "organization": organization,
                "object_type": "sources.RetentionCleanup",
                "object_id": organization.id,
                "action": "ARCHIVE",
                "status": (
                    "COMPLETED_WITH_FAILURES" if result.failures else "COMPLETED"
                ),
                "object_version": 1,
                "comment": "Expired transient source evidence retention cleanup.",
                "after_metadata": {
                    "policy_version": RETENTION_POLICY_VERSION,
                    "cutoff": cutoff.isoformat(),
                    "counts": result.as_dict(),
                    "protected_reasons": dict(result.protected_reasons),
                    "evidence_ids": bounded_changed,
                    "failed_evidence_ids": bounded_failed,
                    "references_truncated": (
                        len(changed_ids) + len(failed_ids)
                        > RETENTION_AUDIT_ID_LIMIT
                    ),
                },
            }
            if actor is None:
                record_system_audit_event(
                    **audit_values,
                    job_id=job_id,
                    claim_token=claim_token,
                )
            else:
                from apps.identity.permissions import PermissionCode

                record_audit_event(
                    **audit_values,
                    actor=actor,
                    required_permission=PermissionCode.SOURCES_MANAGE,
                )
        return result


SOURCE_IMPORT_JOB_SCHEMA = "SOURCE_IMPORT_JOB_V1"
SOURCE_IMPORT_PREFLIGHT_ERROR = {
    "row": None,
    "code": "SOURCE_IMPORT_PREFLIGHT_FAILED",
    "recovery_action": "Review the source import configuration and retry.",
}


def source_import_job_snapshot(batch: IngestionBatch) -> dict[str, object]:
    return {
        "schema": SOURCE_IMPORT_JOB_SCHEMA,
        "ingestion_batch_id": str(batch.id),
        "source_type": batch.source_type,
        "monitoring_target_id": (
            str(batch.monitoring_target_id) if batch.monitoring_target_id else None
        ),
        "prepared_reference_sha256": batch.prepared_reference_sha256,
        "import_asset_id": (
            str(batch.request_import_asset_id)
            if batch.request_import_asset_id is not None
            else None
        ),
        "batch_idempotency_key": batch.idempotency_key,
    }


def source_import_job_matches_batch(*, job: Job, batch: IngestionBatch) -> bool:
    return (
        job.type == Job.Type.SOURCE_IMPORT
        and job.organization_id == batch.organization_id
        and job.idempotency_key == batch.idempotency_key
        and job.input_snapshot == source_import_job_snapshot(batch)
    )


class SourceIdempotencyConflictError(ValueError):
    pass


class SourceIngestionRequestService:
    @staticmethod
    @transaction.atomic
    def create_or_reuse(
        *,
        organization,
        creator,
        source_type,
        idempotency_key,
        prepared_reference,
        monitoring_target_id=None,
        import_asset_id=None,
    ):
        from .tasks import execute_source_import
        from apps.identity.services import lock_organization_scope

        organization = lock_organization_scope(organization=organization)

        monitoring_target = SourceIngestionRequestService._target(
            organization=organization, target_id=monitoring_target_id
        )
        safe_reference = deepcopy(prepared_reference)
        if import_asset_id is not None:
            safe_reference["import_asset_id"] = str(import_asset_id)
        if source_type != IngestionBatch.SourceType.API:
            from .importers import validate_prepared_import_reference
            validate_prepared_import_reference(safe_reference, source_type=source_type)

        requested_assets = SourceIngestionRequestService._lock_requested_assets(
            organization=organization,
            safe_reference=safe_reference,
        )
        existing_batch = (
            IngestionBatch.objects.select_for_update()
            .filter(organization=organization, idempotency_key=idempotency_key)
            .first()
        )
        if existing_batch is not None:
            if not SourceIngestionRequestService._same_request(
                batch=existing_batch,
                source_type=source_type,
                monitoring_target=monitoring_target,
                safe_reference=safe_reference,
            ):
                raise SourceIdempotencyConflictError(
                    "The idempotency key is already bound to a different prepared import."
                )
            return SourceIngestionRequestService._bound_job(
                batch=existing_batch,
                organization=organization,
            )

        SourceIngestionRequestService._validate_requested_assets(
            requested_assets=requested_assets,
            safe_reference=safe_reference,
        )
        SourceIngestionRequestService._reject_retained_asset_reuse(
            organization=organization,
            requested_asset_ids=set(requested_assets),
            requested_screenshot_asset_ids={
                str(row["screenshot_asset_id"])
                for row in safe_reference.get("rows", [])
                if isinstance(row, dict)
                and row.get("screenshot_asset_id") not in (None, "")
            },
        )
        retained_evidence_by_row = (
            SourceIngestionRequestService._redacted_evidence_by_row(
                organization=organization,
                safe_reference=safe_reference,
            )
        )
        try:
            with transaction.atomic():
                batch = IngestionBatch.objects.create(
                    organization=organization,
                    source_type=source_type,
                    monitoring_target=monitoring_target,
                    input_reference=safe_reference,
                    idempotency_key=idempotency_key,
                    created_by=creator,
                )
                if retained_evidence_by_row:
                    persisted = IngestionBatch.objects.filter(
                        pk=batch.pk,
                        organization=organization,
                    )._service_tombstone_input_reference(
                        _capability=_INGESTION_RETENTION_TOMBSTONE_CAPABILITY,
                        evidence_ids_by_row=retained_evidence_by_row,
                    )
                    batch.input_reference = persisted["input_reference"]
        except IntegrityError:
            batch = (
                IngestionBatch.objects.select_for_update()
                .filter(organization=organization, idempotency_key=idempotency_key)
                .first()
            )
            if batch is None:
                raise
            if not SourceIngestionRequestService._same_request(
                batch=batch,
                source_type=source_type,
                monitoring_target=monitoring_target,
                safe_reference=safe_reference,
            ):
                raise SourceIdempotencyConflictError(
                    "The idempotency key is already bound to a different prepared import."
                )

        if batch.job_id is not None:
            return SourceIngestionRequestService._bound_job(
                batch=batch,
                organization=organization,
            )

        request_snapshot = source_import_job_snapshot(batch)
        try:
            job = JobService.create(
                organization=organization,
                job_type=Job.Type.SOURCE_IMPORT,
                input_snapshot=request_snapshot,
                idempotency_key=idempotency_key,
                created_by=creator,
            )
        except JobConflictError as error:
            raise SourceIdempotencyConflictError(
                "The idempotency key is already bound to a different prepared import."
            ) from error
        if not getattr(job, "_service_created", False):
            raise SourceIdempotencyConflictError(
                "The idempotency key is already bound to an incomplete import request."
            )
        batch.job = job
        batch.save(update_fields=["job", "updated_at"])
        if getattr(job, "_service_created", False) and job.status in {
            Job.Status.QUEUED,
            Job.Status.RETRY_QUEUED,
        }:
            job_id = str(job.id)
            batch_id = str(batch.id)
            transaction.on_commit(
                lambda: execute_source_import.delay(job_id, batch_id)
            )
        return batch, job

    @staticmethod
    def _bound_job(*, batch, organization):
        if batch.job_id is None:
            raise SourceIdempotencyConflictError(
                "The idempotency key is already bound to an incomplete import request."
            )
        job = Job.objects.get(pk=batch.job_id, organization=organization)
        if not source_import_job_matches_batch(job=job, batch=batch):
            raise SourceIdempotencyConflictError(
                "The idempotency key is already bound to a different prepared import."
            )
        return batch, job

    @staticmethod
    def _lock_requested_assets(*, organization, safe_reference):
        requested_ids = IngestionService._required_asset_ids(safe_reference)
        if requested_ids is None:
            raise ValidationError(
                {"payload": "One or more attached assets are unavailable."}
            )
        if not requested_ids:
            return MappingProxyType({})
        locked = {
            str(asset.id): asset
            for asset in MaterialAsset.objects.select_for_update()
            .filter(
                organization=organization,
                pk__in=requested_ids,
            )
            .order_by("pk")
        }
        return MappingProxyType(locked)

    @staticmethod
    def _validate_requested_assets(*, requested_assets, safe_reference):
        requested_ids = IngestionService._required_asset_ids(safe_reference)
        if requested_ids is None or set(requested_assets) != requested_ids:
            raise ValidationError(
                {"payload": "One or more attached assets are unavailable."}
            )
        if any(
            asset.status != MaterialAsset.Status.ACTIVE
            for asset in requested_assets.values()
        ):
            raise ValidationError(
                {"payload": "One or more attached assets are unavailable."}
            )
        screenshot_ids = {
            str(row["screenshot_asset_id"])
            for row in safe_reference.get("rows", [])
            if isinstance(row, dict)
            and row.get("screenshot_asset_id") not in (None, "")
        }
        if any(
            requested_assets[asset_id].asset_type
            != MaterialAsset.AssetType.IMAGE
            for asset_id in screenshot_ids
        ):
            raise ValidationError(
                {"payload": "One or more attached assets are unavailable."}
            )

    @staticmethod
    def _reject_retained_asset_reuse(
        *,
        organization,
        requested_asset_ids,
        requested_screenshot_asset_ids,
    ):
        if not requested_asset_ids:
            return
        if requested_screenshot_asset_ids and IngestionRow.objects.filter(
            organization=organization,
            request_screenshot_identity_unproven=True,
        ).exists():
            raise ValidationError(
                {
                    "payload": (
                        "Historical retained screenshot identity is unresolved. "
                        "An administrator reconciliation or a new clean organization "
                        "state is required before attaching screenshots."
                    )
                }
            )
        retained = SourceEvidence.Availability.REDACTED_BY_RETENTION
        screenshot_reused = IngestionRow.objects.filter(
            organization=organization,
            request_screenshot_asset_id__in=requested_asset_ids,
            source_evidence__availability=retained,
        ).exists()
        import_reused = IngestionBatch.objects.filter(
            organization=organization,
            request_import_asset_id__in=requested_asset_ids,
            rows__source_evidence__availability=retained,
        ).exists()
        if screenshot_reused or import_reused:
            raise ValidationError(
                {
                    "payload": (
                        "An attached asset belongs to expired retained source data "
                        "and cannot be used in a new import request."
                    )
                }
            )

    @staticmethod
    def _redacted_evidence_by_row(*, organization, safe_reference):
        if not isinstance(safe_reference, dict):
            return {}
        rows = safe_reference.get("rows")
        if not isinstance(rows, list):
            return {}
        fingerprints_by_row = {
            row["row_number"]: evidence_fingerprint(
                original_text=row["original_text"],
                source_url=row["source_url"],
                platform=row["platform"],
            )
            for row in rows
            if isinstance(row, dict)
            and "retention" not in row
            and row.get("original_text")
        }
        if not fingerprints_by_row:
            return {}
        retained_by_hash = {
            evidence.content_hash: evidence.id
            for evidence in SourceEvidence.objects.select_for_update()
            .filter(
                organization=organization,
                content_hash__in=set(fingerprints_by_row.values()),
                availability=SourceEvidence.Availability.REDACTED_BY_RETENTION,
            )
            .order_by("pk")
        }
        return {
            row_number: retained_by_hash[fingerprint]
            for row_number, fingerprint in fingerprints_by_row.items()
            if fingerprint in retained_by_hash
        }

    @staticmethod
    def _same_request(*, batch, source_type, monitoring_target, safe_reference):
        return (
            batch.source_type == source_type
            and batch.monitoring_target_id
            == (monitoring_target.id if monitoring_target is not None else None)
            and batch.prepared_reference_sha256
            == prepared_reference_sha256(safe_reference)
        )

    @staticmethod
    def _target(*, organization, target_id):
        if target_id is None:
            return None
        try:
            target = (
                MonitoringTarget.objects.select_for_update()
                .filter(pk=target_id, organization=organization, enabled=True)
                .first()
            )
        except (TypeError, ValueError):
            target = None
        if target is None:
            raise ValidationError(
                {"monitoring_target_id": "Monitoring target is unavailable for this organization."}
            )
        return target

def _normalized_row_input(row) -> dict[str, object]:
    return {
        "platform": row.platform,
        "source_url": row.source_url,
        "signal_type": row.signal_type,
        "original_text": row.original_text,
        "author_name": row.author_name,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "screenshot_asset_id": str(row.screenshot_asset_id) if row.screenshot_asset_id else None,
    }


def _validation_message(error: ValidationError) -> str:
    if hasattr(error, "message_dict"):
        values = error.message_dict.values()
        return " ".join(str(message) for messages in values for message in messages)
    return " ".join(error.messages)


def _batch_parse_error(error: ValidationError) -> dict[str, object]:
    details = error.error_dict.get("rows", []) if hasattr(error, "error_dict") else []
    detail = details[0] if details else None
    return {
        "row": None,
        "code": getattr(detail, "code", None) or "IMPORT_PAYLOAD_INVALID",
        "recovery_action": _validation_message(error),
    }


class IngestionService:
    @staticmethod
    def _required_asset_ids(reference) -> set[str] | None:
        if not isinstance(reference, dict):
            return None
        rows = reference.get("rows")
        if not isinstance(rows, list):
            return None
        raw_ids = []
        if reference.get("import_asset_id") not in (None, ""):
            raw_ids.append(reference["import_asset_id"])
        for row in rows:
            if not isinstance(row, dict):
                return None
            if row.get("screenshot_asset_id") not in (None, ""):
                raw_ids.append(row["screenshot_asset_id"])
        try:
            return {str(UUID(str(asset_id))) for asset_id in raw_ids}
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _lock_assets_before_batch(*, batch_id, organization):
        reference = (
            IngestionBatch.objects.filter(
                pk=batch_id,
                organization=organization,
            )
            .values_list("input_reference", flat=True)
            .first()
        )
        required_asset_ids = IngestionService._required_asset_ids(reference)
        if not required_asset_ids:
            return MappingProxyType({})
        return MappingProxyType(
            {
                str(asset.id): _LockedAsset.capture(asset)
                for asset in MaterialAsset.objects.select_for_update()
                .filter(
                    organization=organization,
                    pk__in=required_asset_ids,
                )
                .order_by("pk")
            }
        )

    @staticmethod
    @transaction.atomic
    def run(*, batch_id, organization, claim_token) -> IngestionBatch:
        from .importers import import_result_from_reference
        from apps.identity.services import lock_organization_scope

        organization = lock_organization_scope(organization=organization)
        locked_assets = IngestionService._lock_assets_before_batch(
            batch_id=batch_id,
            organization=organization,
        )

        batch = (
            IngestionBatch.objects.select_for_update()
            .filter(pk=batch_id, organization=organization)
            .first()
        )
        if batch is None:
            raise IngestionBatch.DoesNotExist
        if batch.job_id is None:
            raise StaleJobWorkerError("Ingestion batch is not bound to an owned job.")
        job = (
            Job.objects.select_for_update()
            .filter(pk=batch.job_id, organization=organization)
            .first()
        )
        if job is None or job.type != Job.Type.SOURCE_IMPORT:
            raise StaleJobWorkerError("Ingestion batch is not bound to a source import job.")
        JobService._require_owner(job, claim_token)

        resources, preflight_error = IngestionService._preflight_resources(
            batch=batch,
            job=job,
            organization=organization,
            locked_assets=locked_assets,
        )
        if preflight_error is not None:
            IngestionService._finish_batch(
                batch,
                batch_errors=[preflight_error],
            )
            return batch

        now = timezone.now()
        IngestionService._write_batch_state(
            batch,
            status=IngestionBatch.Status.RUNNING,
            started_at=batch.started_at or now,
            finished_at=None,
        )

        try:
            parsed = import_result_from_reference(
                batch.input_reference, source_type=batch.source_type
            )
        except ValidationError as error:
            batch_error = _batch_parse_error(error)
            IngestionService._finish_batch(batch, batch_errors=[batch_error])
            return batch

        batch_errors = [error for error in parsed.errors if error.get("row") is None]
        for error in parsed.errors:
            if error.get("row") is None:
                continue
            IngestionService._persist_parse_error(
                batch=batch,
                organization=organization,
                error=error,
            )
        for retained_row in parsed.retained_rows:
            if IngestionRow.objects.filter(
                batch=batch, row_number=retained_row.row_number
            ).exists():
                continue
            IngestionService._persist_retained_row(
                batch=batch,
                organization=organization,
                row=retained_row,
            )
        for row in parsed.rows:
            if IngestionRow.objects.filter(batch=batch, row_number=row.row_number).exists():
                continue
            try:
                with transaction.atomic():
                    IngestionService._persist_valid_row(
                        batch=batch,
                        organization=organization,
                        row=row,
                        resources=resources,
                    )
            except ValidationError as error:
                IngestionService._persist_failed_row(
                    batch=batch,
                    organization=organization,
                    row=row,
                    error=IngestionService._row_processing_error(error, row=row),
                )
            except OperationalError:
                raise
            except DatabaseError:
                IngestionService._persist_failed_row(
                    batch=batch,
                    organization=organization,
                    row=row,
                    error={
                        "row": row.row_number,
                        "code": "ROW_DATABASE_CONFLICT",
                        "recovery_action": "Review this row's values and retry the import.",
                    },
                )

        IngestionService._finish_batch(batch, batch_errors=batch_errors)
        return batch

    @staticmethod
    def _persist_parse_error(*, batch, organization, error) -> None:
        row_number = int(error["row"])
        if IngestionRow.objects.filter(batch=batch, row_number=row_number).exists():
            return
        with ingestion_row_service_writes():
            IngestionRow.objects.create(
                organization=organization,
                batch=batch,
                row_number=row_number,
                normalized_input={"row_number": row_number},
                outcome=IngestionRow.Outcome.FAILED,
                error=error,
            )

    @staticmethod
    def _persist_valid_row(*, batch, organization, row, resources) -> None:
        normalized_input = _normalized_row_input(row)
        fingerprint = evidence_fingerprint(
            original_text=row.original_text,
            source_url=row.source_url,
            platform=row.platform,
        )
        existing_evidence = (
            SourceEvidence.objects.select_for_update().select_related(
                "source_signal", "source_signal__source_content"
            )
            .filter(organization=organization, content_hash=fingerprint)
            .order_by("pk")
            .first()
        )
        if existing_evidence is not None:
            duplicate_input = normalized_input
            if (
                existing_evidence.availability
                == SourceEvidence.Availability.REDACTED_BY_RETENTION
            ):
                persisted = IngestionBatch.objects.filter(
                    pk=batch.pk,
                    organization=organization,
                )._service_tombstone_input_reference(
                    _capability=_INGESTION_RETENTION_TOMBSTONE_CAPABILITY,
                    evidence_ids_by_row={row.row_number: existing_evidence.id},
                )
                batch.input_reference = persisted["input_reference"]
                duplicate_input = dict(
                    next(
                        item
                        for item in batch.input_reference["rows"]
                        if item["row_number"] == row.row_number
                    )
                )
                duplicate_input.pop("row_number")
            with ingestion_row_service_writes():
                IngestionRow.objects.create(
                    organization=organization,
                    batch=batch,
                    row_number=row.row_number,
                    normalized_input=duplicate_input,
                    outcome=IngestionRow.Outcome.DUPLICATE,
                    source_content=existing_evidence.source_signal.source_content,
                    source_signal=existing_evidence.source_signal,
                    source_evidence=existing_evidence,
                )
            return

        source_content, _ = SourceContent.objects.get_or_create(
            organization=organization,
            platform=row.platform,
            external_id="",
            content_hash=fingerprint,
            canonical_url=row.source_url,
            defaults={
                "monitoring_target": batch.monitoring_target,
                "author_public_name": row.author_name,
                "original_text": row.original_text,
                "public_published_at": row.published_at,
                "created_by": batch.created_by,
            },
        )
        signal = SourceSignal.objects.create(
            organization=organization,
            monitoring_target=batch.monitoring_target,
            source_content=source_content,
            signal_type=row.signal_type,
            platform=row.platform,
            external_id="",
            created_by=batch.created_by,
        )
        evidence = EvidenceService._create_from_locked_ingestion_assets(
            _capability=_INGESTION_LOCKED_ASSET_CAPABILITY,
            resources=resources,
            screenshot_asset_id=row.screenshot_asset_id,
            organization=organization,
            signal=signal,
            original_text=row.original_text,
            source_url=row.source_url,
            platform=row.platform,
            collection_method=batch.source_type,
            public_published_at=row.published_at,
            created_by=batch.created_by,
        )
        with ingestion_row_service_writes():
            IngestionRow.objects.create(
                organization=organization,
                batch=batch,
                row_number=row.row_number,
                normalized_input=normalized_input,
                outcome=IngestionRow.Outcome.ACCEPTED,
                source_content=source_content,
                source_signal=signal,
                source_evidence=evidence,
            )

    @staticmethod
    def _persist_retained_row(*, batch, organization, row) -> None:
        evidence = (
            SourceEvidence.objects.select_for_update()
            .select_related("source_signal", "source_signal__source_content")
            .filter(
                pk=row.source_evidence_id,
                organization=organization,
                availability=SourceEvidence.Availability.REDACTED_BY_RETENTION,
            )
            .order_by("pk")
            .first()
        )
        if evidence is None:
            raise ValidationError(
                "Retained import evidence is unavailable or no longer redacted."
            )
        normalized_input = deepcopy(row.normalized_input)
        normalized_input.pop("row_number", None)
        with ingestion_row_service_writes():
            IngestionRow.objects.create(
                organization=organization,
                batch=batch,
                row_number=row.row_number,
                normalized_input=normalized_input,
                outcome=IngestionRow.Outcome.DUPLICATE,
                source_content=evidence.source_signal.source_content,
                source_signal=evidence.source_signal,
                source_evidence=evidence,
            )

    @staticmethod
    def _row_processing_error(error: ValidationError, *, row) -> dict[str, object]:
        if hasattr(error, "error_dict") and "screenshot_asset" in error.error_dict:
            code = "SCREENSHOT_ASSET_UNAVAILABLE"
            recovery = "Attach a screenshot asset owned by this organization and re-import this row."
        elif hasattr(error, "error_dict") and "import_asset" in error.error_dict:
            code = "IMPORT_ASSET_UNAVAILABLE"
            recovery = "Attach an import asset owned by this organization and re-import this row."
        else:
            code = "ROW_INGESTION_INVALID"
            recovery = _validation_message(error)
        return {"row": row.row_number, "code": code, "recovery_action": recovery}

    @staticmethod
    def _persist_failed_row(*, batch, organization, row, error) -> None:
        if IngestionRow.objects.filter(batch=batch, row_number=row.row_number).exists():
            return
        with ingestion_row_service_writes():
            IngestionRow.objects.create(
                organization=organization,
                batch=batch,
                row_number=row.row_number,
                normalized_input=_normalized_row_input(row),
                outcome=IngestionRow.Outcome.FAILED,
                error=error,
            )

    @staticmethod
    def _finish_batch(batch, *, batch_errors=None) -> None:
        outcomes = list(batch.rows.values_list("outcome", "error"))
        accepted_count = sum(
            outcome == IngestionRow.Outcome.ACCEPTED for outcome, _error in outcomes
        )
        duplicate_count = sum(
            outcome == IngestionRow.Outcome.DUPLICATE for outcome, _error in outcomes
        )
        failed_count = sum(
            outcome == IngestionRow.Outcome.FAILED for outcome, _error in outcomes
        )
        row_errors = [error for outcome, error in outcomes if outcome == IngestionRow.Outcome.FAILED]
        if batch_errors:
            row_errors.extend(batch_errors)
        successful_count = accepted_count + duplicate_count
        if failed_count and successful_count:
            status = IngestionBatch.Status.PARTIAL_SUCCESS
        elif failed_count or batch_errors or not outcomes:
            status = IngestionBatch.Status.FAILED
        else:
            status = IngestionBatch.Status.SUCCEEDED
        IngestionService._write_batch_state(
            batch,
            status=status,
            received_count=len(outcomes),
            accepted_count=accepted_count,
            duplicate_count=duplicate_count,
            failed_count=failed_count,
            row_errors=row_errors,
            finished_at=timezone.now(),
        )

    @staticmethod
    def _write_batch_state(batch, **values) -> None:
        with _ingestion_batch_state_writes():
            persisted = IngestionBatch.objects.filter(
                pk=batch.pk,
                organization_id=batch.organization_id,
            )._service_update_state(**values)
        for field_name, value in persisted.items():
            setattr(batch, field_name, value)

    @staticmethod
    def _preflight_resources(*, batch, job, organization, locked_assets=None):
        from .importers import validate_prepared_import_reference

        if not source_import_job_matches_batch(job=job, batch=batch):
            return None, dict(SOURCE_IMPORT_PREFLIGHT_ERROR)
        try:
            validate_prepared_import_reference(
                batch.input_reference,
                source_type=batch.source_type,
            )
        except ValidationError:
            return None, dict(SOURCE_IMPORT_PREFLIGHT_ERROR)
        if (
            "retention" not in batch.input_reference
            and prepared_reference_sha256(batch.input_reference)
            != batch.prepared_reference_sha256
        ):
            return None, dict(SOURCE_IMPORT_PREFLIGHT_ERROR)

        locked_target = None
        if batch.monitoring_target_id:
            locked_target = (
                MonitoringTarget.objects.select_for_update()
                .filter(pk=batch.monitoring_target_id)
                .first()
            )
            if (
                locked_target is None
                or locked_target.organization_id != organization.id
                or not locked_target.enabled
            ):
                return None, dict(SOURCE_IMPORT_PREFLIGHT_ERROR)
            batch.monitoring_target = locked_target

        reference = batch.input_reference
        raw_import_asset_id = reference.get("import_asset_id")
        import_asset_id = str(raw_import_asset_id) if raw_import_asset_id is not None else None
        screenshot_asset_ids = frozenset(
            str(row["screenshot_asset_id"])
            for row in reference["rows"]
            if row.get("screenshot_asset_id") is not None
        )
        required_asset_ids = IngestionService._required_asset_ids(reference)
        if required_asset_ids is None:
            return None, dict(SOURCE_IMPORT_PREFLIGHT_ERROR)
        if not required_asset_ids:
            return (
                _LockedIngestionResources(
                    monitoring_target=locked_target,
                    assets=MappingProxyType({}),
                    import_asset_id=None,
                    screenshot_asset_ids=frozenset(),
                ),
                None,
            )

        if locked_assets is None:
            locked_assets = MappingProxyType(
                {
                    str(asset.id): _LockedAsset.capture(asset)
                    for asset in MaterialAsset.objects.select_for_update()
                    .filter(
                        organization=organization,
                        pk__in=required_asset_ids,
                    )
                    .order_by("pk")
                }
            )
        if set(locked_assets) != required_asset_ids:
            return None, dict(SOURCE_IMPORT_PREFLIGHT_ERROR)
        try:
            if import_asset_id is not None:
                locked_assets[import_asset_id].resolve(
                    organization=organization,
                    field_name="import_asset",
                )
            for screenshot_asset_id in screenshot_asset_ids:
                locked_assets[screenshot_asset_id].resolve(
                    organization=organization,
                    field_name="screenshot_asset",
                    image_required=True,
                )
        except ValidationError:
            return None, dict(SOURCE_IMPORT_PREFLIGHT_ERROR)
        return (
            _LockedIngestionResources(
                monitoring_target=locked_target,
                assets=MappingProxyType(dict(locked_assets)),
                import_asset_id=import_asset_id,
                screenshot_asset_ids=screenshot_asset_ids,
            ),
            None,
        )

    @staticmethod
    def preflight_failed(batch) -> bool:
        return any(
            error.get("code") == SOURCE_IMPORT_PREFLIGHT_ERROR["code"]
            for error in batch.row_errors
            if isinstance(error, dict)
        )
