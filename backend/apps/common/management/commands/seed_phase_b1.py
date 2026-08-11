import json
from datetime import UTC, datetime

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction

from apps.ai.models import AIRun, PromptVersion
from apps.ai.services import PromptVersionService
from apps.identity.models import Membership, Organization, Role
from apps.jobs.models import Job, JobAttempt
from apps.jobs.services import JobConflictError, JobService
from apps.leads.models import (
    LeadAnalysisBinding,
    LeadCandidate,
    LeadInsight,
    LeadReview,
    lead_history_writes,
)
from apps.leads.orchestration import execute_lead_analysis_job
from apps.leads.schemas import LEAD_ANALYSIS_OUTPUT_SCHEMA, lead_analysis_errors
from apps.leads.scoring import EvidenceGates, ScoreDimensions, score_lead
from apps.leads.services import (
    LeadReviewService,
    LeadService,
    build_analysis_snapshot,
)
from apps.sources.importers import prepare_import_reference
from apps.sources.models import (
    IngestionBatch,
    IngestionRow,
    MonitoringTarget,
    SourceContent,
    SourceEvidence,
    SourceSignal,
    evidence_service_writes,
    prepared_reference_sha256,
)
from apps.sources.services import evidence_fingerprint, source_import_job_snapshot
from apps.sources.tasks import execute_source_import
from integrations.ai.providers import SchemaAwareFakeAIProvider


PROMPT_CODE = "phase-b1-lead-analyze-v1"
PROMPT_TEMPLATE = """Analyze only the frozen public evidence below and return JSON matching the supplied schema.
Do not infer private contact details or send outreach.
INPUT_JSON_BEGIN
{input_json}
INPUT_JSON_END"""
BRIDGE_URL = "https://example.com/phase-b1/public-signal"
BRIDGE_TEXT = (
    "We need 200 replacement helical gears for a packaging machine, DIN 6 if possible."
)
VAGUE_URL = "https://example.com/phase-b1/vague-signal"
VAGUE_TEXT = "Our team is considering whether a different sprocket material might help."
LOW_URL = "https://example.com/phase-b1/ordinary-signal"
LOW_TEXT = "Thanks for sharing this explanation of involute gear geometry."
SEED_BATCH_KEY = "phase-b1-seed-mixed-import"
TARGET_URL = "https://example.com/phase-b1/public-signals"
SEED_CAPTURED_AT = datetime(2026, 1, 1, tzinfo=UTC)


class Command(BaseCommand):
    help = "Seed deterministic Phase B1 lead-intelligence demo data for a named membership."

    def add_arguments(self, parser):
        parser.add_argument("--organization-slug", required=True)
        parser.add_argument("--username", required=True)
        parser.add_argument("--organization-name")
        parser.add_argument("--password")
        parser.add_argument("--create-demo-identity", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        del args
        if not getattr(settings, "PHASE_B1_SCHEMA_FAKE_ALLOWED", False):
            raise CommandError(
                "seed_phase_b1 requires the explicit schema-fake safety gate."
            )
        if options["create_demo_identity"]:
            organization, actor = self._create_demo_identity(
                organization_slug=options["organization_slug"],
                organization_name=options["organization_name"],
                username=options["username"],
                password=options["password"],
            )
        else:
            organization, actor = self._identity(
                organization_slug=options["organization_slug"],
                username=options["username"],
            )
        call_command("seed_gear_ontology", verbosity=0)
        prompt = self._prompt(actor)
        target = self._target(organization, actor)
        evidence = self._mixed_import(organization, actor, target)

        bridge = self._candidate(
            organization=organization,
            actor=actor,
            evidence=evidence[BRIDGE_URL],
            company_name="Phase B1 Browser Packaging",
            company_domain="phase-b1-browser.example",
            country_hint="DE",
            expected_status=LeadCandidate.Status.ANALYZED,
        )
        watch = self._candidate(
            organization=organization,
            actor=actor,
            evidence=evidence[VAGUE_URL],
            company_name="Phase B1 Watch Prospect",
            company_domain="phase-b1-watch.example",
            country_hint="",
            expected_status=LeadCandidate.Status.ANALYZED,
        )
        low = self._candidate(
            organization=organization,
            actor=actor,
            evidence=evidence[LOW_URL],
            company_name="Phase B1 Low Signal",
            company_domain="phase-b1-low.example",
            country_hint="",
            expected_status=LeadCandidate.Status.ANALYZED,
        )
        reviewed = self._candidate(
            organization=organization,
            actor=actor,
            evidence=evidence[BRIDGE_URL],
            company_name="Phase B1 Reviewed Opportunity",
            company_domain="phase-b1-reviewed.example",
            country_hint="",
            existing_country_hint="DE",
            expected_status=LeadCandidate.Status.REVIEWED,
        )
        for label, candidate, source_evidence in (
            ("bridge", bridge, evidence[BRIDGE_URL]),
            ("watch", watch, evidence[VAGUE_URL]),
            ("low", low, evidence[LOW_URL]),
            ("reviewed", reviewed, evidence[BRIDGE_URL]),
        ):
            self._analyze(
                organization=organization,
                actor=actor,
                prompt=prompt,
                candidate=candidate,
                evidence=source_evidence,
                label=label,
            )
        self._review_correction(
            organization=organization,
            actor=actor,
            candidate=reviewed,
        )
        self._failed_analysis_job(organization, actor)
        self.stdout.write(
            self.style.SUCCESS(
                f"Phase B1 seed present for {organization.slug} ({actor.username})."
            )
        )

    @staticmethod
    def _identity(*, organization_slug, username):
        organization = Organization.objects.filter(slug=organization_slug).first()
        actor = get_user_model().objects.filter(username=username).first()
        if organization is None or actor is None:
            raise CommandError("The named organization and user must already exist.")
        membership = Membership.objects.filter(
            organization=organization,
            user=actor,
            status=Membership.Status.ACTIVE,
        ).first()
        if membership is None:
            raise CommandError(
                "seed_phase_b1 requires an active membership in the named organization."
            )
        return organization, actor

    @staticmethod
    def _create_demo_identity(
        *, organization_slug, organization_name, username, password
    ):
        if not getattr(settings, "PHASE_A_E2E_SEED_ALLOWED", False):
            raise CommandError(
                "Demo identity creation is allowed only in the isolated E2E environment."
            )
        if not organization_name or not password:
            raise CommandError(
                "--organization-name and --password are required for a demo identity."
            )
        organization, created = Organization.objects.get_or_create(
            slug=organization_slug,
            defaults={"name": organization_name},
        )
        if not created and organization.name != organization_name:
            raise CommandError(
                "The demo organization slug collides with a different name."
            )
        user_model = get_user_model()
        actor, created = user_model.objects.get_or_create(
            username=username,
            defaults={
                "email": f"{username}@example.invalid",
                "first_name": "Phase B1",
                "last_name": "E2E Fixture",
                "is_active": True,
                "is_staff": True,
                "is_superuser": False,
            },
        )
        expected_email = f"{username}@example.invalid"
        if not created and actor.email != expected_email:
            raise CommandError("The demo username collides with a different user.")
        actor.set_password(password)
        actor.save(update_fields=["password"])
        role = Role.objects.create_administrator()
        membership, created = Membership.objects.get_or_create(
            organization=organization,
            user=actor,
            defaults={"role": role, "status": Membership.Status.ACTIVE},
        )
        if not created and (
            membership.role_id != role.id
            or membership.status != Membership.Status.ACTIVE
        ):
            raise CommandError(
                "The demo membership collides with a different role or state."
            )
        return organization, actor

    @staticmethod
    def _prompt(actor):
        existing = list(PromptVersion.objects.filter(code=PROMPT_CODE))
        if len(existing) > 1:
            raise CommandError("The Phase B1 seed prompt code is ambiguous.")
        expected = {
            "purpose": "LEAD_ANALYZE",
            "provider": "schema-fake",
            "model": "schema-fake-v1",
            "template": PROMPT_TEMPLATE,
            "output_schema": LEAD_ANALYSIS_OUTPUT_SCHEMA,
            "status": PromptVersion.Status.PUBLISHED,
        }
        if existing:
            prompt = existing[0]
            if any(
                getattr(prompt, field) != value for field, value in expected.items()
            ):
                raise CommandError(
                    "The Phase B1 seed prompt collides with different content."
                )
            return prompt
        return PromptVersionService.create(
            code=PROMPT_CODE,
            created_by=actor,
            **expected,
        )

    @staticmethod
    def _require_owned_contract(label, instance, expected, *, invariants=None):
        if instance is None:
            raise CommandError(f"The Phase B1 {label} contract is missing.")
        mismatches = [
            field
            for field, expected_value in expected.items()
            if getattr(instance, field) != expected_value
        ]
        if invariants:
            mismatches.extend(
                name for name, satisfied in invariants.items() if not satisfied
            )
        if mismatches:
            fields = ", ".join(sorted(set(mismatches)))
            raise CommandError(f"The Phase B1 {label} contract collides at: {fields}.")
        return instance

    @staticmethod
    def _require_exact_identity_set(label, actual, expected):
        if len(actual) != len(expected) or set(actual) != set(expected):
            raise CommandError(
                f"The Phase B1 {label} contract is missing or ambiguous."
            )

    @staticmethod
    def _target(organization, actor):
        expected = {
            "organization_id": organization.id,
            "target_type": MonitoringTarget.TargetType.POST,
            "collection_mode": MonitoringTarget.CollectionMode.PASTE,
            "platform": "MANUAL",
            "external_reference": "",
            "normalized_url": TARGET_URL,
            "label": "Phase B1 public signal fixtures",
            "schedule": {},
            "enabled": True,
            "capability_snapshot": {},
            "created_by_id": actor.id,
        }
        batches = list(
            IngestionBatch.objects.select_related("monitoring_target").filter(
                organization=organization,
                idempotency_key=SEED_BATCH_KEY,
            )
        )
        if len(batches) > 1:
            raise CommandError("The Phase B1 monitoring target contract is ambiguous.")
        matching = list(
            MonitoringTarget.objects.filter(
                organization=organization,
                normalized_url=TARGET_URL,
            )
        )
        if batches:
            target = batches[0].monitoring_target
            identities = {row.id for row in matching}
            if target is not None:
                identities.add(target.id)
            if len(identities) != 1:
                raise CommandError(
                    "The Phase B1 monitoring target contract is missing or ambiguous."
                )
        else:
            if len(matching) > 1:
                raise CommandError(
                    "The Phase B1 monitoring target contract is ambiguous."
                )
            target = matching[0] if matching else None
            if target is None:
                target = MonitoringTarget.objects.create(
                    organization=organization,
                    normalized_url=TARGET_URL,
                    target_type=MonitoringTarget.TargetType.POST,
                    collection_mode=MonitoringTarget.CollectionMode.PASTE,
                    platform="MANUAL",
                    external_reference="",
                    label="Phase B1 public signal fixtures",
                    schedule={},
                    enabled=True,
                    capability_snapshot={},
                    created_by=actor,
                )
        Command._require_owned_contract("monitoring target", target, expected)
        return target

    @staticmethod
    def _mixed_import(organization, actor, target):
        payload = {
            "text": "\n".join(
                (
                    f"{BRIDGE_URL}\t{BRIDGE_TEXT}",
                    f"{VAGUE_URL}\t{VAGUE_TEXT}",
                    f"{LOW_URL}\t{LOW_TEXT}",
                    "not-a-public-url\tThis invalid row demonstrates partial recovery.",
                )
            )
        }
        reference = prepare_import_reference(
            payload, source_type=IngestionBatch.SourceType.PASTE
        )
        batches = list(
            IngestionBatch.objects.filter(
                organization=organization,
                idempotency_key=SEED_BATCH_KEY,
            )
        )
        if len(batches) > 1:
            raise CommandError("The Phase B1 mixed import contract is ambiguous.")
        created = not batches
        if created:
            batch = IngestionBatch.objects.create(
                organization=organization,
                source_type=IngestionBatch.SourceType.PASTE,
                monitoring_target=target,
                input_reference=reference,
                idempotency_key=SEED_BATCH_KEY,
                created_by=actor,
            )
            try:
                job = JobService.create(
                    organization=organization,
                    job_type=Job.Type.SOURCE_IMPORT,
                    input_snapshot=source_import_job_snapshot(batch),
                    idempotency_key=SEED_BATCH_KEY,
                    created_by=actor,
                )
            except JobConflictError as error:
                raise CommandError(
                    "The Phase B1 mixed import contract collides with an import job."
                ) from error
            batch.job = job
            batch.save(update_fields=["job", "updated_at"])
        else:
            batch = batches[0]
        Command._require_owned_contract(
            "mixed import",
            batch,
            {
                "organization_id": organization.id,
                "source_type": IngestionBatch.SourceType.PASTE,
                "monitoring_target_id": target.id,
                "input_reference": reference,
                "prepared_reference_sha256": prepared_reference_sha256(reference),
                "request_import_asset_id": None,
                "idempotency_key": SEED_BATCH_KEY,
                "created_by_id": actor.id,
            },
            invariants={"job_id": batch.job_id is not None},
        )
        job = Job.objects.filter(pk=batch.job_id).first()
        Command._require_owned_contract(
            "import job",
            job,
            {
                "organization_id": organization.id,
                "type": Job.Type.SOURCE_IMPORT,
                "input_snapshot": source_import_job_snapshot(batch),
                "idempotency_key": SEED_BATCH_KEY,
                "created_by_id": actor.id,
                "max_attempts": 3,
            },
        )
        if created:
            if job.status != Job.Status.QUEUED:
                raise CommandError(
                    "The Phase B1 import job contract did not start queued."
                )
            execute_source_import(str(job.id), str(batch.id))
            Command._freeze_source_capture_contract(batch)
        return Command._validate_source_import_contract(
            organization=organization,
            actor=actor,
            target=target,
            batch=batch,
            reference=reference,
        )

    @staticmethod
    def _freeze_source_capture_contract(batch):
        rows = list(batch.rows.all())
        content_ids = {
            row.source_content_id for row in rows if row.source_content_id is not None
        }
        signal_ids = {
            row.source_signal_id for row in rows if row.source_signal_id is not None
        }
        evidence_ids = {
            row.source_evidence_id for row in rows if row.source_evidence_id is not None
        }
        SourceContent.objects.filter(pk__in=content_ids).update(
            captured_at=SEED_CAPTURED_AT
        )
        SourceSignal.objects.filter(pk__in=signal_ids).update(
            captured_at=SEED_CAPTURED_AT
        )
        with evidence_service_writes():
            SourceEvidence.objects.filter(pk__in=evidence_ids).update(
                captured_at=SEED_CAPTURED_AT
            )

    @staticmethod
    def _validate_source_import_contract(
        *, organization, actor, target, batch, reference
    ):
        batch.refresh_from_db()
        Command._require_owned_contract(
            "mixed import",
            batch,
            {
                "organization_id": organization.id,
                "source_type": IngestionBatch.SourceType.PASTE,
                "status": IngestionBatch.Status.PARTIAL_SUCCESS,
                "monitoring_target_id": target.id,
                "input_reference": reference,
                "prepared_reference_sha256": prepared_reference_sha256(reference),
                "request_import_asset_id": None,
                "received_count": 4,
                "accepted_count": 3,
                "duplicate_count": 0,
                "failed_count": 1,
                "row_errors": reference["errors"],
                "idempotency_key": SEED_BATCH_KEY,
                "created_by_id": actor.id,
            },
            invariants={
                "job_id": batch.job_id is not None,
                "started_at": batch.started_at is not None,
                "finished_at": batch.finished_at is not None,
                "runtime_order": (
                    batch.started_at is not None
                    and batch.finished_at is not None
                    and batch.started_at <= batch.finished_at
                ),
            },
        )
        job = Job.objects.filter(pk=batch.job_id).first()
        expected_result = {"ingestion_batch_id": str(batch.id)}
        Command._require_owned_contract(
            "import job",
            job,
            {
                "organization_id": organization.id,
                "type": Job.Type.SOURCE_IMPORT,
                "status": Job.Status.SUCCEEDED,
                "progress": 100,
                "input_snapshot": source_import_job_snapshot(batch),
                "result_reference": expected_result,
                "error": None,
                "idempotency_key": SEED_BATCH_KEY,
                "attempt": 1,
                "max_attempts": 3,
                "claim_token": None,
                "claimed_by": "source-import-worker",
                "version": 3,
                "created_by_id": actor.id,
            },
            invariants={
                "claimed_at": job is not None and job.claimed_at is not None,
                "started_at": job is not None and job.started_at is not None,
                "finished_at": job is not None and job.finished_at is not None,
                "runtime_order": (
                    job is not None
                    and job.claimed_at is not None
                    and job.started_at is not None
                    and job.finished_at is not None
                    and job.claimed_at == job.started_at
                    and job.started_at <= job.finished_at
                ),
            },
        )
        attempts = list(JobAttempt.objects.filter(job=job))
        if len(attempts) != 1:
            raise CommandError(
                "The Phase B1 import job attempt contract is missing or ambiguous."
            )
        attempt = attempts[0]
        Command._require_owned_contract(
            "import job attempt",
            attempt,
            {
                "job_id": job.id,
                "number": 1,
                "worker_id": "source-import-worker",
                "status": JobAttempt.Status.SUCCEEDED,
                "error": None,
                "result_reference": expected_result,
            },
            invariants={
                "claim_token": attempt.claim_token is not None,
                "started_at": attempt.started_at == job.started_at,
                "finished_at": attempt.finished_at == job.finished_at,
            },
        )

        ingestion_rows = list(
            IngestionRow.objects.select_related(
                "source_content",
                "source_signal",
                "source_evidence",
            ).filter(batch=batch)
        )
        by_number = {row.row_number: row for row in ingestion_rows}
        Command._require_exact_identity_set(
            "ingestion row",
            [row.row_number for row in ingestion_rows],
            [1, 2, 3, 4],
        )
        expected_rows = {row["row_number"]: row for row in reference["rows"]}
        content_ids = []
        signal_ids = []
        evidence_ids = []
        evidence_by_url = {}
        for row_number, expected_row in expected_rows.items():
            row = by_number[row_number]
            if any(
                related is None
                for related in (
                    row.source_content,
                    row.source_signal,
                    row.source_evidence,
                )
            ):
                raise CommandError(
                    "The Phase B1 ingestion row contract is missing source provenance."
                )
            fingerprint = evidence_fingerprint(
                original_text=expected_row["original_text"],
                source_url=expected_row["source_url"],
                platform=expected_row["platform"],
            )
            content = Command._require_owned_contract(
                "source content",
                row.source_content,
                {
                    "organization_id": organization.id,
                    "monitoring_target_id": target.id,
                    "platform": expected_row["platform"],
                    "external_id": "",
                    "canonical_url": expected_row["source_url"],
                    "author_public_name": expected_row["author_name"],
                    "title": "",
                    "original_text": expected_row["original_text"],
                    "public_published_at": None,
                    "language": "",
                    "captured_at": SEED_CAPTURED_AT,
                    "content_hash": fingerprint,
                    "created_by_id": actor.id,
                },
            )
            signal = Command._require_owned_contract(
                "source signal",
                row.source_signal,
                {
                    "organization_id": organization.id,
                    "monitoring_target_id": target.id,
                    "source_content_id": content.id,
                    "signal_type": expected_row["signal_type"],
                    "platform": expected_row["platform"],
                    "external_id": "",
                    "captured_at": SEED_CAPTURED_AT,
                    "created_by_id": actor.id,
                },
            )
            source_evidence = row.source_evidence
            evidence = Command._require_owned_contract(
                "source evidence",
                source_evidence,
                {
                    "organization_id": organization.id,
                    "source_signal_id": signal.id,
                    "evidence_type": SourceEvidence.EvidenceType.PUBLIC_TEXT,
                    "original_text": expected_row["original_text"],
                    "translated_text": "",
                    "translated_language": "",
                    "source_url": expected_row["source_url"],
                    "platform": expected_row["platform"],
                    "public_published_at": None,
                    "captured_at": SEED_CAPTURED_AT,
                    "collection_method": SourceEvidence.CollectionMethod.PASTE,
                    "language": "",
                    "screenshot_asset_id": None,
                    "import_asset_id": None,
                    "content_hash": fingerprint,
                    "availability": SourceEvidence.Availability.AVAILABLE,
                    "created_by_id": actor.id,
                },
                invariants={
                    "retention_class": (
                        source_evidence.retention_class
                        in SourceEvidence.RetentionClass.values
                    ),
                },
            )
            normalized_input = dict(expected_row)
            normalized_input.pop("row_number")
            Command._require_owned_contract(
                "ingestion row",
                row,
                {
                    "organization_id": organization.id,
                    "batch_id": batch.id,
                    "row_number": row_number,
                    "normalized_input": normalized_input,
                    "request_screenshot_asset_id": None,
                    "request_screenshot_identity_unproven": False,
                    "outcome": IngestionRow.Outcome.ACCEPTED,
                    "error": None,
                    "source_content_id": content.id,
                    "source_signal_id": signal.id,
                    "source_evidence_id": evidence.id,
                },
            )
            content_ids.append(content.id)
            signal_ids.append(signal.id)
            evidence_ids.append(evidence.id)
            evidence_by_url[evidence.source_url] = evidence

        failed_row = by_number[4]
        Command._require_owned_contract(
            "ingestion row",
            failed_row,
            {
                "organization_id": organization.id,
                "batch_id": batch.id,
                "row_number": 4,
                "normalized_input": {"row_number": 4},
                "request_screenshot_asset_id": None,
                "request_screenshot_identity_unproven": False,
                "outcome": IngestionRow.Outcome.FAILED,
                "error": reference["errors"][0],
                "source_content_id": None,
                "source_signal_id": None,
                "source_evidence_id": None,
            },
        )
        expected_urls = {BRIDGE_URL, VAGUE_URL, LOW_URL}
        Command._require_exact_identity_set(
            "source content",
            list(
                SourceContent.objects.filter(
                    organization=organization,
                    canonical_url__in=expected_urls,
                ).values_list("id", flat=True)
            ),
            content_ids,
        )
        Command._require_exact_identity_set(
            "source signal",
            list(
                SourceSignal.objects.filter(
                    organization=organization,
                    monitoring_target=target,
                    source_content_id__in=content_ids,
                ).values_list("id", flat=True)
            ),
            signal_ids,
        )
        Command._require_exact_identity_set(
            "source evidence",
            list(
                SourceEvidence.objects.filter(
                    organization=organization,
                    source_url__in=expected_urls,
                ).values_list("id", flat=True)
            ),
            evidence_ids,
        )
        if set(evidence_by_url) != expected_urls:
            raise CommandError(
                "The Phase B1 source evidence contract is missing or ambiguous."
            )
        return evidence_by_url

    @staticmethod
    def _candidate(
        *,
        organization,
        actor,
        evidence,
        company_name,
        company_domain,
        country_hint,
        expected_status,
        existing_country_hint=None,
    ):
        matches = list(
            LeadCandidate.objects.filter(
                organization=organization,
                company_name=company_name,
            )
        )
        if not matches:
            return LeadService.create_candidate(
                organization=organization,
                creator=actor,
                company_name=company_name,
                company_domain=company_domain,
                country_hint=country_hint,
                evidence_ids=[evidence.id],
            )
        if len(matches) != 1:
            raise CommandError(f"The Phase B1 candidate '{company_name}' is ambiguous.")
        candidate = matches[0]
        expected_country_hint = (
            country_hint if existing_country_hint is None else existing_country_hint
        )
        linked = set(candidate.evidence_links.values_list("evidence_id", flat=True))
        if any(
            (
                candidate.company_domain != company_domain,
                candidate.country_hint != expected_country_hint,
                candidate.created_by_id != actor.id,
                candidate.source_signal_id != evidence.source_signal_id,
                candidate.status != expected_status,
                candidate.latest_insight_id is None,
                candidate.analysis_lease_token is not None,
                linked != {evidence.id},
            )
        ):
            raise CommandError(
                f"The Phase B1 candidate '{company_name}' collides with data."
            )
        return candidate

    @staticmethod
    def _analyze(*, organization, actor, prompt, candidate, evidence, label):
        candidate.refresh_from_db()
        if candidate.latest_insight_id is not None:
            return Command._validate_analysis_contract(
                organization=organization,
                actor=actor,
                prompt=prompt,
                candidate=candidate,
                evidence=evidence,
                label=label,
            )
        snapshot = build_analysis_snapshot(
            candidate=candidate,
            evidence_ids=[evidence.id],
            actor=actor,
        )
        try:
            job = JobService.create(
                organization=organization,
                job_type=Job.Type.LEAD_ANALYZE,
                input_snapshot=snapshot,
                idempotency_key=f"phase-b1-seed-analysis-{label}",
                created_by=actor,
            )
        except JobConflictError as error:
            raise CommandError(
                f"The Phase B1 {label} analysis job collides with different input."
            ) from error
        with lead_history_writes():
            LeadAnalysisBinding.objects.create(
                organization=organization,
                job=job,
                candidate=candidate,
                prompt_version=prompt,
                requested_by=actor,
            )
        run = execute_lead_analysis_job(job.id, prompt.id)
        if run.status != "SUCCEEDED":
            raise CommandError(f"The Phase B1 {label} analysis did not succeed.")
        return Command._validate_analysis_contract(
            organization=organization,
            actor=actor,
            prompt=prompt,
            candidate=candidate,
            evidence=evidence,
            label=label,
        )

    @staticmethod
    def _validate_analysis_contract(
        *, organization, actor, prompt, candidate, evidence, label
    ):
        candidate.refresh_from_db()
        jobs = list(
            Job.objects.filter(
                organization=organization,
                type=Job.Type.LEAD_ANALYZE,
                idempotency_key=f"phase-b1-seed-analysis-{label}",
            )
        )
        if len(jobs) != 1:
            raise CommandError(
                f"The Phase B1 {label} analysis job is missing or ambiguous."
            )
        job = jobs[0]
        snapshot = job.input_snapshot
        bindings = list(
            LeadAnalysisBinding.objects.filter(
                organization=organization,
                job=job,
            )
        )
        runs = list(AIRun.objects.filter(organization=organization, job=job))
        frozen_country_hint = "" if label == "reviewed" else candidate.country_hint
        frozen_evidence_ids = (
            {
                row.get("id")
                for row in snapshot.get("evidence", [])
                if isinstance(row, dict)
            }
            if isinstance(snapshot, dict)
            else set()
        )
        if (
            job.status != Job.Status.SUCCEEDED
            or job.created_by_id != actor.id
            or job.max_attempts != 3
            or job.error is not None
            or not isinstance(snapshot, dict)
            or snapshot.get("organization_id") != str(organization.id)
            or snapshot.get("lead_candidate_id") != str(candidate.id)
            or snapshot.get("candidate")
            != {
                "company_name": candidate.company_name,
                "company_domain": candidate.company_domain,
                "country_hint": frozen_country_hint,
            }
            or frozen_evidence_ids != {str(evidence.id)}
            or len(bindings) != 1
            or bindings[0].candidate_id != candidate.id
            or bindings[0].prompt_version_id != prompt.id
            or bindings[0].requested_by_id != actor.id
            or len(runs) != 1
        ):
            raise CommandError(f"The Phase B1 {label} analysis provenance collides.")
        run = runs[0]
        rendered = prompt.template.format(
            input_json=json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
        )
        expected_output = SchemaAwareFakeAIProvider().generate(
            prompt=rendered,
            schema=prompt.output_schema,
        )
        insights = list(
            LeadInsight.objects.filter(
                organization=organization,
                candidate=candidate,
                ai_run=run,
                origin=LeadInsight.Origin.AI,
            )
        )
        if (
            run.status != AIRun.Status.SUCCEEDED
            or run.prompt_version_id != prompt.id
            or run.provider != prompt.provider
            or run.model != prompt.model
            or run.input_snapshot != snapshot
            or run.output_json != expected_output
            or run.error is not None
            or lead_analysis_errors(run.output_json, snapshot=snapshot)
            or len(insights) != 1
        ):
            raise CommandError(f"The Phase B1 {label} analysis output collides.")
        insight = insights[0]
        dimensions = expected_output["dimensions"]
        expected_explanation = {
            "company_name": expected_output["company_name"],
            "company_domain": expected_output.get("company_domain", ""),
            "country_hint": expected_output.get("country_hint", ""),
            "need_summary_zh": expected_output["need_summary_zh"],
            "need_summary_en": expected_output["need_summary_en"],
            "insufficient_evidence": expected_output["insufficient_evidence"],
            "reasons": expected_output["reasons"],
        }
        expected_values = [
            {
                "type": row["type"],
                "value": row["value"],
                "unit": row["unit"],
                "evidence_ids": row["evidence_ids"],
            }
            for row in expected_output["requirements"]
        ]
        expected_requirements = sorted(
            (
                row["type"],
                source_id,
                row["value"],
                row["unit"],
            )
            for row in expected_output["requirements"]
            for source_id in row["evidence_ids"]
        )
        actual_requirements = sorted(
            (
                row.requirement_concept.code,
                str(row.source_evidence_id),
                row.extracted_value,
                row.unit,
            )
            for row in insight.requirements.select_related("requirement_concept")
        )
        matches = expected_output["capability_matches"]
        expected_capability_gate = bool(matches and expected_requirements)
        actual_dimensions = {
            "intent": insight.intent_score,
            "company_fit": insight.company_fit_score,
            "specificity": insight.specificity_score,
            "capability_fit": insight.capability_fit_score,
            "recency": insight.recency_score,
        }
        expected_gates = EvidenceGates(
            traceable_source=True,
            explicit_need_or_company_match=not expected_output["insufficient_evidence"],
            capability_evidence=expected_capability_gate,
            audited_run=True,
            ontology_snapshot=True,
        )
        expected_score = score_lead(
            ScoreDimensions(**dimensions),
            expected_gates,
        )
        if any(
            (
                insight.source_insight_id is not None,
                insight.human_correction is not None,
                insight.reviewed_by_id is not None,
                bool(insight.review_reason),
                insight.version != 1,
                actual_dimensions != dimensions,
                insight.score != expected_score.total,
                insight.score_band != expected_score.band,
                insight.high_value_eligible is not expected_score.high_value_eligible,
                insight.explanation != expected_explanation,
                insight.extracted_requirement_values != expected_values,
                float(insight.evidence_confidence)
                != expected_output["confidence"]["intent"],
                float(insight.company_match_confidence)
                != expected_output["confidence"]["company_fit"],
                float(insight.ai_confidence)
                != expected_output["confidence"]["capability"],
                insight.traceable_source is not True,
                insight.explicit_need_or_company_match
                is not (not expected_output["insufficient_evidence"]),
                insight.capability_evidence is not expected_capability_gate,
                insight.audited_run is not True,
                insight.ontology_snapshot_complete is not True,
                insight.ontology_snapshot != snapshot["ontology_snapshot"],
                set(insight.evidence_links.values_list("evidence_id", flat=True))
                != {evidence.id},
                actual_requirements != expected_requirements,
            )
        ):
            raise CommandError(f"The Phase B1 {label} analysis insight collides.")
        if label != "reviewed" and candidate.latest_insight_id != insight.id:
            raise CommandError(
                f"The Phase B1 {label} latest analysis insight collides."
            )
        return insight

    @staticmethod
    def _review_correction(*, organization, actor, candidate):
        candidate.refresh_from_db()
        existing = LeadReview.objects.filter(
            organization=organization,
            reviewer=actor,
            idempotency_key="phase-b1-seed-reviewed-correction",
        ).first()
        if existing is not None:
            corrected = existing.insight
            source = corrected.source_insight if corrected is not None else None
            expected_reason = "Seeded reviewer correction for acceptance testing."
            expected_correction = {"country_hint": "DE"}
            if corrected is None or source is None:
                raise CommandError("The Phase B1 review collides with different data.")
            if any(
                (
                    existing.organization_id != organization.id,
                    existing.candidate_id != candidate.id,
                    existing.action != LeadReview.Action.CORRECT,
                    existing.reason != expected_reason,
                    existing.correction != expected_correction,
                    existing.reviewer_id != actor.id,
                    candidate.latest_insight_id != existing.insight_id,
                    candidate.status != LeadCandidate.Status.REVIEWED,
                    existing.candidate_status != candidate.status,
                    existing.candidate_version != candidate.version,
                    corrected.origin != LeadInsight.Origin.HUMAN_CORRECTION,
                    corrected.human_correction != expected_correction,
                    corrected.reviewed_by_id != actor.id,
                    corrected.review_reason != expected_reason,
                    corrected.candidate_id != candidate.id,
                    corrected.ai_run_id != source.ai_run_id,
                    corrected.explanation != source.explanation,
                    corrected.extracted_requirement_values
                    != source.extracted_requirement_values,
                    corrected.ontology_snapshot != source.ontology_snapshot,
                )
            ):
                raise CommandError("The Phase B1 review collides with different data.")
            return existing
        return LeadReviewService.apply(
            organization=organization,
            candidate=candidate,
            action=LeadReview.Action.CORRECT,
            expected_version=candidate.version,
            reason="Seeded reviewer correction for acceptance testing.",
            correction={"country_hint": "DE"},
            reviewer=actor,
            idempotency_key="phase-b1-seed-reviewed-correction",
        ).review

    @staticmethod
    def _failed_analysis_job(organization, actor):
        expected_input = {
            "schema": "PHASE_B1_SEED_FAILURE_V1",
            "reason": "Synthetic recoverable analysis failure",
        }
        try:
            job = JobService.create(
                organization=organization,
                job_type=Job.Type.LEAD_ANALYZE,
                input_snapshot=expected_input,
                idempotency_key="phase-b1-seed-failed-analysis",
                created_by=actor,
                max_attempts=1,
            )
        except JobConflictError as error:
            raise CommandError(
                "The Phase B1 failed job collides with different input."
            ) from error
        if job.status == Job.Status.QUEUED:
            claimed = JobService.claim(
                worker_id="phase-b1-seed-failure",
                job_id=job.id,
            )
            JobService.fail(
                claimed.id,
                claim_token=claimed.claim_token,
                error={
                    "code": "seeded_analysis_failure",
                    "message": "Synthetic recoverable analysis failure.",
                },
            )
            job.refresh_from_db()
        expected_error = {
            "code": "job_error",
            "message": "Job execution failed.",
        }
        if any(
            (
                job.organization_id != organization.id,
                job.type != Job.Type.LEAD_ANALYZE,
                job.status != Job.Status.FAILED,
                job.input_snapshot != expected_input,
                job.created_by_id != actor.id,
                job.max_attempts != 1,
                job.attempt != 1,
                job.progress != 0,
                job.error != expected_error,
                job.result_reference is not None,
                job.claim_token is not None,
                job.claimed_by != "phase-b1-seed-failure",
                job.finished_at is None,
            )
        ):
            raise CommandError("The Phase B1 failed job collides with different data.")
        return job
