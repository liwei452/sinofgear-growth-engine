import hashlib
import ipaddress
from urllib.parse import urlsplit, urlunsplit

from django.core.exceptions import ValidationError
from django.db import DatabaseError, OperationalError, transaction
from django.utils import timezone

from apps.assets.models import MaterialAsset
from apps.jobs.models import Job
from apps.jobs.services import JobService, StaleJobWorkerError

from .models import (
    IngestionBatch,
    IngestionRow,
    SourceContent,
    SourceEvidence,
    SourceSignal,
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
        signal_id = getattr(signal, "pk", None)
        try:
            signal = SourceSignal.objects.select_for_update().filter(
                pk=signal_id, organization=organization
            ).first()
        except (TypeError, ValueError) as error:
            raise ValidationError(
                {"signal": "Source signal is unavailable for this organization."}
            ) from error
        if signal is None:
            raise ValidationError(
                {"signal": "Source signal is unavailable for this organization."}
            )
        screenshot_asset = EvidenceService._locked_asset(
            screenshot_asset, "screenshot_asset", organization
        )
        import_asset = EvidenceService._locked_asset(
            import_asset, "import_asset", organization
        )
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
        with evidence_service_writes():
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


create = EvidenceService.create


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

        now = timezone.now()
        batch.status = IngestionBatch.Status.RUNNING
        batch.started_at = batch.started_at or now
        batch.finished_at = None
        batch.save(update_fields=["status", "started_at", "finished_at", "updated_at"])

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
    def _persist_valid_row(*, batch, organization, row) -> None:
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

        screenshot_asset = None
        if row.screenshot_asset_id is not None:
            screenshot_asset = MaterialAsset.objects.select_for_update().filter(
                pk=row.screenshot_asset_id,
                organization=organization,
                asset_type=MaterialAsset.AssetType.IMAGE,
            ).first()
            if screenshot_asset is None:
                raise ValidationError(
                    {"screenshot_asset": "Screenshot asset is unavailable for this organization."}
                )

        import_asset = IngestionService._import_asset(batch, organization=organization)
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
        evidence = EvidenceService.create(
            organization=organization,
            signal=signal,
            original_text=row.original_text,
            source_url=row.source_url,
            platform=row.platform,
            collection_method=batch.source_type,
            public_published_at=row.published_at,
            created_by=batch.created_by,
            screenshot_asset=screenshot_asset,
            import_asset=import_asset,
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
    def _import_asset(batch, *, organization):
        if batch.source_type not in {
            IngestionBatch.SourceType.CSV,
            IngestionBatch.SourceType.JSON,
        }:
            return None
        if not isinstance(batch.input_reference, dict):
            return None
        asset_id = batch.input_reference.get("import_asset_id")
        if not asset_id:
            return None
        asset = MaterialAsset.objects.select_for_update().filter(
            pk=asset_id, organization=organization
        ).first()
        if asset is None:
            raise ValidationError(
                {"import_asset": "Import asset is unavailable for this organization."}
            )
        return asset

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
        batch.status = status
        batch.received_count = len(outcomes)
        batch.accepted_count = accepted_count
        batch.duplicate_count = duplicate_count
        batch.failed_count = failed_count
        batch.row_errors = row_errors
        batch.finished_at = timezone.now()
        batch.save(
            update_fields=[
                "status",
                "received_count",
                "accepted_count",
                "duplicate_count",
                "failed_count",
                "row_errors",
                "finished_at",
                "updated_at",
            ]
        )
