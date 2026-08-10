import hashlib
import ipaddress
import json
from copy import deepcopy
from contextlib import nullcontext
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, OperationalError, transaction
from django.utils import timezone

from apps.assets.models import MaterialAsset
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
    _evidence_trusted_asset_writes,
    _ingestion_batch_state_writes,
    evidence_service_writes,
    ingestion_row_service_writes,
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


SOURCE_IMPORT_JOB_SCHEMA = "SOURCE_IMPORT_JOB_V1"
SOURCE_IMPORT_PREFLIGHT_ERROR = {
    "row": None,
    "code": "SOURCE_IMPORT_PREFLIGHT_FAILED",
    "recovery_action": "Review the source import configuration and retry.",
}


def prepared_reference_digest(reference) -> str:
    encoded = json.dumps(
        reference,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def source_import_job_snapshot(batch: IngestionBatch) -> dict[str, object]:
    reference = batch.input_reference if isinstance(batch.input_reference, dict) else {}
    return {
        "schema": SOURCE_IMPORT_JOB_SCHEMA,
        "ingestion_batch_id": str(batch.id),
        "source_type": batch.source_type,
        "monitoring_target_id": (
            str(batch.monitoring_target_id) if batch.monitoring_target_id else None
        ),
        "prepared_reference_sha256": prepared_reference_digest(batch.input_reference),
        "import_asset_id": reference.get("import_asset_id"),
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

        monitoring_target = SourceIngestionRequestService._target(
            organization=organization, target_id=monitoring_target_id
        )
        import_asset = SourceIngestionRequestService._asset(
            organization=organization, asset_id=import_asset_id
        )
        safe_reference = deepcopy(prepared_reference)
        if import_asset is not None:
            safe_reference["import_asset_id"] = str(import_asset.id)
            from .importers import validate_prepared_import_reference

            validate_prepared_import_reference(safe_reference, source_type=source_type)
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
            job = Job.objects.get(pk=batch.job_id, organization=organization)
            if not source_import_job_matches_batch(job=job, batch=batch):
                raise SourceIdempotencyConflictError(
                    "The idempotency key is already bound to a different prepared import."
                )
            return batch, job

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
    def _same_request(*, batch, source_type, monitoring_target, safe_reference):
        return (
            batch.source_type == source_type
            and batch.monitoring_target_id
            == (monitoring_target.id if monitoring_target is not None else None)
            and batch.input_reference == safe_reference
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

    @staticmethod
    def _asset(*, organization, asset_id):
        if asset_id is None:
            return None
        try:
            asset = (
                MaterialAsset.objects.select_for_update()
                .filter(
                    pk=asset_id,
                    organization=organization,
                    status=MaterialAsset.Status.ACTIVE,
                )
                .first()
            )
        except (TypeError, ValueError):
            asset = None
        if asset is None:
            raise ValidationError(
                {"import_asset_id": "Import asset is unavailable for this organization."}
            )
        return asset


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
    @transaction.atomic
    def run(*, batch_id, organization, claim_token) -> IngestionBatch:
        from .importers import import_result_from_reference

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
            SourceEvidence.objects.select_related(
                "source_signal", "source_signal__source_content"
            )
            .filter(organization=organization, content_hash=fingerprint)
            .first()
        )
        if existing_evidence is not None:
            with ingestion_row_service_writes():
                IngestionRow.objects.create(
                    organization=organization,
                    batch=batch,
                    row_number=row.row_number,
                    normalized_input=normalized_input,
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
    def _preflight_resources(*, batch, job, organization):
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
        required_asset_ids = set(screenshot_asset_ids)
        if import_asset_id is not None:
            required_asset_ids.add(import_asset_id)
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

        locked_assets = {
            str(asset.id): _LockedAsset.capture(asset)
            for asset in MaterialAsset.objects.select_for_update()
            .filter(pk__in=required_asset_ids)
            .order_by("pk")
        }
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
                assets=MappingProxyType(locked_assets),
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
