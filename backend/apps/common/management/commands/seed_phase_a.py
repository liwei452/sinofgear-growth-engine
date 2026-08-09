import hashlib
import hmac
import secrets
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, call_command
from django.db import models, transaction

from apps.ai.models import PromptVersion, ai_audit_writes
from apps.assets.models import AssetProductLink, MaterialAsset
from apps.assets.storage import get_object_storage
from apps.campaigns.models import (
    Campaign,
    CampaignProduct,
    ContentBrief,
    ContentBriefAsset,
    ContentBriefConceptLink,
    ContentBriefPlatform,
    ContentBriefProduct,
)
from apps.campaigns.services import mark_content_brief_ready
from apps.catalog.models import Product, ProductConceptLink
from apps.identity.models import Membership, Organization, PhaseAE2EOwnership, Role
from apps.knowledge.management.commands.seed_gear_ontology import ALIASES, CONCEPTS, RELATIONS
from apps.knowledge.models import (
    KnowledgeAlias, KnowledgeConcept, KnowledgeGraphLock, KnowledgeRelation,
)
from apps.platforms.codes import AccountCapability
from apps.platforms.models import (
    ConnectorCredential, Platform, PlatformCapability, SocialAccount,
)


ORGANIZATION_ID = UUID("10000000-0000-4000-8000-000000000001")
PRODUCT_ID = UUID("10000000-0000-4000-8000-000000000101")
ASSET_ID = UUID("10000000-0000-4000-8000-000000000201")
ASSET_LINK_ID = UUID("10000000-0000-4000-8000-000000000202")
CAMPAIGN_ID = UUID("10000000-0000-4000-8000-000000000301")
CAMPAIGN_PRODUCT_ID = UUID("10000000-0000-4000-8000-000000000302")
BRIEF_ID = UUID("10000000-0000-4000-8000-000000000401")
PROMPT_ID = UUID("10000000-0000-4000-8000-000000000501")
PASSWORD = "PhaseA-E2E-Only!"

USERS = (
    ("phasea_e2e_admin", Role.Code.ADMINISTRATOR),
    ("phasea_e2e_operator", Role.Code.OPERATOR),
    ("phasea_e2e_reviewer", Role.Code.REVIEWER),
    ("phasea_e2e_viewer", Role.Code.READ_ONLY),
)
PLATFORM_CODES = ("FACEBOOK", "INSTAGRAM", "LINKEDIN", "TIKTOK", "YOUTUBE")
PLATFORM_NAMES = {
    "FACEBOOK": "Facebook",
    "INSTAGRAM": "Instagram",
    "LINKEDIN": "LinkedIn",
    "TIKTOK": "TikTok",
    "YOUTUBE": "YouTube",
}
CONCEPT_LINKS = {
    ProductConceptLink.Role.TYPE: "HELICAL_GEAR",
    ProductConceptLink.Role.PROCESS: "GRINDING",
    ProductConceptLink.Role.STANDARD: "DIN",
    ProductConceptLink.Role.APPLICATION: "PACKAGING_MACHINERY",
}
VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42phase-a-e2e-factory-video"
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "body": {"type": "string"},
        "cta": {"type": "string"},
        "concept_codes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "body", "cta", "concept_codes"],
    "additionalProperties": False,
}


def stable_id(number: int) -> UUID:
    return UUID(f"10000000-0000-4000-8000-{number:012d}")


class Command(BaseCommand):
    help = "Seed the isolated Phase A end-to-end acceptance organization."

    def handle(self, *args, **options):
        del args, options
        if not getattr(settings, "PHASE_A_E2E_SEED_ALLOWED", False):
            raise CommandError(
                "seed_phase_a is E2E-only; use the isolated E2E settings and launcher."
            )
        with transaction.atomic():
            self._claim_or_verify_ownership()
            self._preflight()
            self._ensure_asset_blob()
            call_command("seed_gear_ontology", verbosity=0)
            organization = self._organization()
            users = self._users(organization)
            concepts = self._concepts()
            platforms = self._platforms()
            product = self._product(organization, concepts)
            asset = self._asset(organization, users[Role.Code.OPERATOR], product)
            self._campaign_and_brief(
                organization=organization,
                operator=users[Role.Code.OPERATOR],
                reviewer=users[Role.Code.REVIEWER],
                product=product,
                asset=asset,
                concepts=concepts,
                platforms=platforms,
            )
            self._accounts(organization, platforms)
            self._prompt(users[Role.Code.ADMINISTRATOR])
        self.stdout.write(
            self.style.SUCCESS(
                "Phase A E2E seed present (organization phase-a-e2e-only; credentials are test-only)."
            )
        )

    @staticmethod
    def _collision(label):
        raise CommandError(f"Phase A E2E seed ownership collision: {label}.")

    @staticmethod
    def _ownership_config():
        secret = getattr(settings, "PHASE_A_E2E_OWNERSHIP_SECRET", "")
        run_id = getattr(settings, "PHASE_A_E2E_RUN_ID", "")
        if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
            raise CommandError("Phase A E2E ownership secret must be at least 32 bytes.")
        if not isinstance(run_id, str) or not run_id:
            raise CommandError("Phase A E2E run identity is required.")
        return secret, run_id

    @classmethod
    def _ownership_signature(cls, nonce):
        secret, run_id = cls._ownership_config()
        message = f"phase-a-e2e-ownership:v1\0{run_id}\0{ORGANIZATION_ID}\0{nonce}"
        return hmac.new(
            secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    @classmethod
    def _valid_ownership(cls, organization):
        marker = PhaseAE2EOwnership.objects.filter(
            organization=organization
        ).first()
        if marker is None:
            return False
        expected = cls._ownership_signature(marker.nonce)
        return hmac.compare_digest(marker.signature, expected)

    @classmethod
    def _claim_or_verify_ownership(cls):
        cls._ownership_config()
        organization = Organization.objects.select_for_update().filter(
            pk=ORGANIZATION_ID
        ).first()
        slug_owner = Organization.objects.select_for_update().filter(
            slug="phase-a-e2e-only"
        ).first()
        if organization is not None or slug_owner is not None:
            if (
                organization is None
                or slug_owner is None
                or organization.pk != slug_owner.pk
                or not cls._valid_ownership(organization)
            ):
                cls._collision("organization ownership proof")
            return

        organization = Organization.objects.create(
            id=ORGANIZATION_ID,
            name="Phase A E2E Only",
            slug="phase-a-e2e-only",
        )
        nonce = secrets.token_hex(32)
        PhaseAE2EOwnership.objects.create(
            organization=organization,
            nonce=nonce,
            signature=cls._ownership_signature(nonce),
        )

    @classmethod
    def _preflight(cls):
        user_model = get_user_model()
        organization = Organization.objects.filter(pk=ORGANIZATION_ID).first()
        slug_owner = Organization.objects.filter(slug="phase-a-e2e-only").first()
        if (organization is None) != (slug_owner is None) or (
            organization is not None and slug_owner.pk != organization.pk
        ):
            cls._collision("organization id or slug")

        owned = organization is not None and cls._valid_ownership(organization)
        if not owned:
            cls._collision("organization ownership proof")

        for index, (username, role_code) in enumerate(USERS, start=1):
            user = user_model.objects.filter(username=username).first()
            membership = Membership.objects.filter(pk=stable_id(10 + index)).select_related(
                "role"
            ).first()
            if user is None and membership is None:
                continue
            if not owned or user is None or membership is None or any((
                user.email != f"{username}@example.invalid",
                membership.user_id != user.id,
                membership.organization_id != ORGANIZATION_ID,
                membership.role.code != role_code,
            )):
                cls._collision(f"user or membership {username}")

        for code, (name, permissions) in Role.BUILTIN_ROLES.items():
            role = Role.objects.filter(code=code).first()
            if role is not None and (
                role.name != name or role.permissions != list(permissions)
            ):
                cls._collision(f"built-in role {code}")

        phase_objects = (
            (Product, PRODUCT_ID, {"organization_id": ORGANIZATION_ID}),
            (MaterialAsset, ASSET_ID, {"organization_id": ORGANIZATION_ID}),
            (AssetProductLink, ASSET_LINK_ID, {
                "organization_id": ORGANIZATION_ID, "asset_id": ASSET_ID,
                "product_id": PRODUCT_ID,
            }),
            (Campaign, CAMPAIGN_ID, {"organization_id": ORGANIZATION_ID}),
            (CampaignProduct, CAMPAIGN_PRODUCT_ID, {
                "organization_id": ORGANIZATION_ID, "campaign_id": CAMPAIGN_ID,
                "product_id": PRODUCT_ID,
            }),
            (ContentBrief, BRIEF_ID, {
                "organization_id": ORGANIZATION_ID, "campaign_id": CAMPAIGN_ID,
            }),
        )
        for model, object_id, identity in phase_objects:
            row = model.objects.filter(pk=object_id).first()
            if row is not None and (
                not owned or any(getattr(row, field) != value for field, value in identity.items())
            ):
                cls._collision(f"{model.__name__} {object_id}")

        for index, (role, concept_code) in enumerate(CONCEPT_LINKS.items(), start=1):
            link = ProductConceptLink.objects.filter(pk=stable_id(110 + index)).select_related(
                "concept"
            ).first()
            if link is not None and (
                not owned
                or link.organization_id != ORGANIZATION_ID
                or link.product_id != PRODUCT_ID
                or link.role != role
                or link.concept.code != concept_code
                or link.retired_at is not None
            ):
                cls._collision(f"product concept link {role}")

        for index, code in enumerate(PLATFORM_CODES, start=1):
            platform_id = stable_id(600 + index)
            by_id = Platform.objects.filter(pk=platform_id).first()
            by_code = Platform.objects.filter(code=code).first()
            if by_id is not None or by_code is not None:
                if (
                    not owned or by_id is None or by_code is None or by_id.pk != by_code.pk
                    or by_id.code != code or by_id.name != PLATFORM_NAMES[code]
                ):
                    cls._collision(f"platform {code}")
            capability = PlatformCapability.objects.filter(
                platform_id=platform_id, code=AccountCapability.PUBLISH
            ).first()
            if capability is not None and by_id is None:
                cls._collision(f"platform capability {code}")
            credential_id = stable_id(700 + index)
            credential = ConnectorCredential.objects.filter(pk=credential_id).first()
            if credential is not None and (
                not owned or credential.organization_id != ORGANIZATION_ID
                or credential.platform_id != platform_id
            ):
                cls._collision(f"credential {code}")
            account_id = stable_id(800 + index)
            account = SocialAccount.objects.filter(pk=account_id).first()
            natural_account = SocialAccount.objects.filter(
                organization_id=ORGANIZATION_ID,
                platform_id=platform_id,
                external_id=f"phase-a-e2e-{code.lower()}",
            ).first()
            if account is not None or natural_account is not None:
                if (
                    not owned or account is None or natural_account is None
                    or account.pk != natural_account.pk
                    or account.organization_id != ORGANIZATION_ID
                    or account.platform_id != platform_id
                    or account.credential_id != credential_id
                ):
                    cls._collision(f"social account {code}")

        prompt = PromptVersion.objects.filter(pk=PROMPT_ID).first()
        natural_prompt = PromptVersion.objects.filter(
            purpose="CONTENT_GENERATE", version=1
        ).first()
        if prompt is not None or natural_prompt is not None:
            if (
                not owned or prompt is None or natural_prompt is None
                or prompt.pk != natural_prompt.pk or prompt.code != "phase-a-e2e-content-v1"
            ):
                cls._collision("prompt version")

        graph_lock = KnowledgeGraphLock.objects.filter(pk=1).first()
        if graph_lock is not None and graph_lock.name != "is_a_graph":
            cls._collision("knowledge graph lock")
        expected_concepts = {code: concept_type for concept_type, code, _zh, _en in CONCEPTS}
        for concept in KnowledgeConcept.objects.filter(
            scope=KnowledgeConcept.Scope.SYSTEM, code__in=expected_concepts
        ):
            if concept.organization_id is not None or concept.concept_type != expected_concepts[concept.code]:
                cls._collision(f"ontology concept {concept.code}")
        concept_by_code = {
            row.code: row for row in KnowledgeConcept.objects.filter(
                scope=KnowledgeConcept.Scope.SYSTEM, code__in=expected_concepts
            )
        }
        for code, language, alias, _alias_type in ALIASES:
            existing = KnowledgeAlias.objects.filter(
                organization=None, language=language, normalized_alias=alias.casefold()
            ).select_related("concept").first()
            if existing is not None and existing.concept.code != code:
                cls._collision(f"ontology alias {language}:{alias}")
        for subject, predicate, object_code in RELATIONS:
            subject_row = concept_by_code.get(subject)
            object_row = concept_by_code.get(object_code)
            if subject_row is None or object_row is None:
                continue
            relation = KnowledgeRelation.objects.filter(
                organization=None, subject_concept=subject_row,
                predicate=predicate, object_concept=object_row,
            ).first()
            if relation is not None and relation.organization_id is not None:
                cls._collision(f"ontology relation {subject}:{predicate}:{object_code}")

        cls._preflight_relationships(owned)

    @classmethod
    def _preflight_relationships(cls, owned):
        expected = (
            (ContentBriefProduct, stable_id(410), {
                "organization_id": ORGANIZATION_ID, "brief_id": BRIEF_ID,
                "product_id": PRODUCT_ID,
            }),
            (ContentBriefAsset, stable_id(411), {
                "organization_id": ORGANIZATION_ID, "brief_id": BRIEF_ID,
                "asset_id": ASSET_ID,
            }),
        )
        for model, row_id, identity in expected:
            row = model.objects.filter(pk=row_id).first()
            if row is not None and (
                not owned or any(getattr(row, field) != value for field, value in identity.items())
            ):
                cls._collision(f"{model.__name__} {row_id}")
        for index, code in enumerate(PLATFORM_CODES, start=1):
            row_id = stable_id(420 + index)
            row = ContentBriefPlatform.objects.filter(pk=row_id).first()
            if row is not None and (
                not owned or row.organization_id != ORGANIZATION_ID
                or row.brief_id != BRIEF_ID or row.platform_id != stable_id(600 + index)
            ):
                cls._collision(f"brief platform {code}")
        for index, (role, code) in enumerate((
            (ContentBriefConceptLink.Role.TARGET_INDUSTRY, "PACKAGING_MACHINERY"),
            (ContentBriefConceptLink.Role.STANDARD, "DIN"),
        ), start=1):
            row = ContentBriefConceptLink.objects.filter(pk=stable_id(430 + index)).select_related(
                "concept"
            ).first()
            if row is not None and (
                not owned or row.organization_id != ORGANIZATION_ID
                or row.brief_id != BRIEF_ID or row.role != role or row.concept.code != code
            ):
                cls._collision(f"brief concept {code}")

        relationship_ids = {
            CampaignProduct: {CAMPAIGN_PRODUCT_ID},
            ContentBriefProduct: {stable_id(410)},
            ContentBriefAsset: {stable_id(411)},
            ContentBriefPlatform: {stable_id(421 + index) for index in range(5)},
            ContentBriefConceptLink: {stable_id(431), stable_id(432)},
        }
        for model, allowed_ids in relationship_ids.items():
            queryset = model.objects.filter(organization_id=ORGANIZATION_ID)
            if model is CampaignProduct:
                queryset = queryset.filter(campaign_id=CAMPAIGN_ID)
            else:
                queryset = queryset.filter(brief_id=BRIEF_ID)
            if queryset.exclude(pk__in=allowed_ids).exists():
                raise CommandError(
                    f"Phase A E2E unexpected seed relationship in {model.__name__}."
                )

    @staticmethod
    def _ensure_asset_blob():
        checksum = hashlib.sha256(VIDEO_BYTES).hexdigest()
        storage_key = f"organizations/{ORGANIZATION_ID}/assets/{ASSET_ID}/original"
        storage = get_object_storage()
        if storage.put(BytesIO(VIDEO_BYTES), storage_key):
            return
        with storage.open(storage_key) as existing:
            payload = existing.read()
        if len(payload) != len(VIDEO_BYTES) or hashlib.sha256(payload).hexdigest() != checksum:
            raise CommandError("Phase A E2E stored object collision has different bytes.")

    @staticmethod
    def _organization():
        organization, _ = Organization.objects.update_or_create(
            id=ORGANIZATION_ID,
            defaults={"name": "Phase A E2E Only", "slug": "phase-a-e2e-only"},
        )
        return organization

    @staticmethod
    def _users(organization):
        role_factories = {
            Role.Code.ADMINISTRATOR: Role.objects.create_administrator,
            Role.Code.OPERATOR: Role.objects.create_operator,
            Role.Code.REVIEWER: Role.objects.create_reviewer,
            Role.Code.READ_ONLY: Role.objects.create_read_only,
        }
        user_model = get_user_model()
        users = {}
        for index, (username, role_code) in enumerate(USERS, start=1):
            role = role_factories[role_code]()
            user, _ = user_model.objects.update_or_create(
                username=username,
                defaults={
                    "email": f"{username}@example.invalid",
                    "first_name": "Phase A",
                    "last_name": role.name,
                    "is_active": True,
                    "is_staff": role_code == Role.Code.ADMINISTRATOR,
                    "is_superuser": False,
                },
            )
            user.set_password(PASSWORD)
            user.save(update_fields=["password"])
            Membership.objects.update_or_create(
                id=stable_id(10 + index),
                defaults={
                    "user": user,
                    "organization": organization,
                    "role": role,
                    "status": Membership.Status.ACTIVE,
                },
            )
            users[role_code] = user
        return users

    @staticmethod
    def _concepts():
        concepts = {
            concept.code: concept
            for concept in KnowledgeConcept.objects.filter(
                scope=KnowledgeConcept.Scope.SYSTEM,
                code__in=set(CONCEPT_LINKS.values()),
            )
        }
        missing = set(CONCEPT_LINKS.values()) - set(concepts)
        if missing:
            raise CommandError(f"Gear ontology seed is incomplete: {sorted(missing)}")
        if any(concept.status != KnowledgeConcept.Status.APPROVED for concept in concepts.values()):
            raise CommandError("Phase A concepts must be APPROVED.")
        return concepts

    @staticmethod
    def _platforms():
        platforms = {}
        for index, code in enumerate(PLATFORM_CODES, start=1):
            platform, _ = Platform.objects.update_or_create(
                id=stable_id(600 + index),
                defaults={"code": code, "name": PLATFORM_NAMES[code]},
            )
            platform.capability_definitions.update_or_create(code=AccountCapability.PUBLISH)
            platforms[code] = platform
        return platforms

    @staticmethod
    def _product(organization, concepts):
        defaults = {
            "organization": organization,
            "name_zh": "定制斜齿轮",
            "name_en": "Custom Helical Gear",
            "module_min": Decimal("1.0000"),
            "module_max": Decimal("6.0000"),
            "tooth_count_min": 12,
            "tooth_count_max": 120,
            "pressure_angle": Decimal("20.000"),
            "accuracy_grade": "DIN 6",
            "heat_treatment": "Carburized and hardened",
            "surface_treatment": "Ground tooth flanks",
            "manufacturing_capabilities": ["hobbing", "grinding"],
            "inspection_capabilities": ["CMM", "gear inspection center"],
            "moq": 1,
            "lead_time": "4-6 weeks",
            "landing_page_url": "https://example.invalid/custom-helical-gear",
            "status": Product.Status.ACTIVE,
            "internal_notes": "Deterministic Phase A E2E fixture only.",
        }
        product = Product.objects.filter(pk=PRODUCT_ID).first()
        if product is None:
            product = Product.objects.create(id=PRODUCT_ID, **defaults)
        else:
            if product.organization_id != organization.id:
                raise CommandError("Stable Phase A product ID belongs to another organization.")
            changed = []
            for field, value in defaults.items():
                if field == "organization":
                    continue
                if getattr(product, field) != value:
                    setattr(product, field, value)
                    changed.append(field)
            if changed:
                product.save(update_fields=[*changed, "updated_at"])
        for index, (role, code) in enumerate(CONCEPT_LINKS.items(), start=1):
            link = ProductConceptLink.objects.filter(id=stable_id(110 + index)).first()
            if link is None:
                ProductConceptLink.objects.create(
                    id=stable_id(110 + index),
                    organization=organization,
                    product=product,
                    concept=concepts[code],
                    role=role,
                )
            elif (
                link.organization_id != organization.id
                or link.product_id != product.id
                or link.concept_id != concepts[code].id
                or link.role != role
                or link.retired_at is not None
            ):
                raise CommandError("Immutable Phase A product concept link drift was detected.")
        return product

    @staticmethod
    def _asset(organization, creator, product):
        checksum = hashlib.sha256(VIDEO_BYTES).hexdigest()
        storage_key = f"organizations/{organization.id}/assets/{ASSET_ID}/original"
        asset = MaterialAsset.objects.filter(pk=ASSET_ID).first()
        immutable = {
            "organization": organization,
            "asset_type": MaterialAsset.AssetType.VIDEO,
            "storage_key": storage_key,
            "original_filename": "phase-a-factory-floor.mp4",
            "mime_type": "video/mp4",
            "size_bytes": len(VIDEO_BYTES),
            "checksum": checksum,
            "created_by": creator,
        }
        if asset is None:
            asset = MaterialAsset.objects.create(
                id=ASSET_ID,
                language="en",
                status=MaterialAsset.Status.ACTIVE,
                tags=["factory", "helical-gear", "e2e-only"],
                metadata_json={"fixture": "phase-a-e2e", "source": "synthetic"},
                **immutable,
            )
        else:
            if any(getattr(asset, field) != value for field, value in immutable.items()):
                raise CommandError("Immutable Phase A original asset drift was detected.")
            mutable = {
                "language": "en",
                "status": MaterialAsset.Status.ACTIVE,
                "tags": ["factory", "helical-gear", "e2e-only"],
                "metadata_json": {"fixture": "phase-a-e2e", "source": "synthetic"},
            }
            changed = [field for field, value in mutable.items() if getattr(asset, field) != value]
            if changed:
                for field in changed:
                    setattr(asset, field, mutable[field])
                asset.save(update_fields=[*changed, "updated_at"])
        link = AssetProductLink.objects.filter(pk=ASSET_LINK_ID).first()
        if link is None:
            AssetProductLink.objects.create(
                id=ASSET_LINK_ID,
                organization=organization,
                asset=asset,
                product=product,
            )
        elif link.asset_id != asset.id or link.product_id != product.id:
            raise CommandError("Immutable Phase A asset link drift was detected.")
        return asset

    @staticmethod
    def _campaign_and_brief(*, organization, operator, reviewer, product, asset, concepts, platforms):
        campaign = Campaign.objects.filter(pk=CAMPAIGN_ID).first()
        campaign_defaults = {
            "name": "Phase A Helical Gear Growth",
            "description": "Deterministic closed-loop E2E campaign.",
            "status": Campaign.Status.ACTIVE,
        }
        if campaign is None:
            campaign = Campaign.objects.create(
                id=CAMPAIGN_ID, organization=organization, **campaign_defaults
            )
        elif campaign.organization_id != organization.id:
            raise CommandError("Stable Phase A campaign ID belongs to another organization.")
        else:
            changed = [field for field, value in campaign_defaults.items() if getattr(campaign, field) != value]
            if changed:
                for field in changed:
                    setattr(campaign, field, campaign_defaults[field])
                campaign.save(update_fields=[*changed, "updated_at"])
        if not CampaignProduct.objects.filter(pk=CAMPAIGN_PRODUCT_ID).exists():
            CampaignProduct.objects.create(
                id=CAMPAIGN_PRODUCT_ID,
                organization=organization,
                campaign=campaign,
                product=product,
            )

        brief = ContentBrief.objects.filter(pk=BRIEF_ID).first()
        if brief is None:
            brief = ContentBrief.objects.create(
                id=BRIEF_ID,
                organization=organization,
                campaign=campaign,
                status=ContentBrief.Status.DRAFT,
                target_country="Germany",
                customer_type="Packaging machinery OEM",
                content_objective="Generate qualified custom helical gear inquiries",
                cta="Request a manufacturing review",
                landing_page_url="https://example.invalid/custom-helical-gear",
                language="en",
                prohibited_claims=["zero wear", "guaranteed lifetime"],
                selling_points=["DIN 6 grinding", "custom low-volume production"],
                advantages=["factory inspection", "engineering support"],
                keywords=["custom helical gear", "DIN gear grinding"],
                created_by=operator,
            )
            ContentBriefProduct.objects.create(
                id=stable_id(410), organization=organization, brief=brief, product=product
            )
            ContentBriefAsset.objects.create(
                id=stable_id(411), organization=organization, brief=brief, asset=asset
            )
            for index, code in enumerate(PLATFORM_CODES, start=1):
                ContentBriefPlatform.objects.create(
                    id=stable_id(420 + index),
                    organization=organization,
                    brief=brief,
                    platform=platforms[code],
                )
            ContentBriefConceptLink.objects.create(
                id=stable_id(431),
                organization=organization,
                brief=brief,
                concept=concepts["PACKAGING_MACHINERY"],
                role=ContentBriefConceptLink.Role.TARGET_INDUSTRY,
            )
            ContentBriefConceptLink.objects.create(
                id=stable_id(432),
                organization=organization,
                brief=brief,
                concept=concepts["DIN"],
                role=ContentBriefConceptLink.Role.STANDARD,
            )
            brief = mark_content_brief_ready(brief.id, reviewer=reviewer)
        elif (
            brief.organization_id != organization.id
            or brief.campaign_id != campaign.id
            or brief.status != ContentBrief.Status.READY
        ):
            raise CommandError("Immutable READY Phase A brief drift was detected.")
        Command._repair_brief_relationships(
            organization=organization,
            brief=brief,
            product=product,
            asset=asset,
            concepts=concepts,
            platforms=platforms,
        )

    @staticmethod
    def _repair_brief_relationships(*, organization, brief, product, asset, concepts, platforms):
        expected = [
            (ContentBriefProduct, stable_id(410), {
                "organization": organization, "brief": brief, "product": product,
            }),
            (ContentBriefAsset, stable_id(411), {
                "organization": organization, "brief": brief, "asset": asset,
            }),
        ]
        expected.extend(
            (
                ContentBriefPlatform,
                stable_id(420 + index),
                {"organization": organization, "brief": brief, "platform": platforms[code]},
            )
            for index, code in enumerate(PLATFORM_CODES, start=1)
        )
        expected.extend((
            (
                ContentBriefConceptLink,
                stable_id(431),
                {
                    "organization": organization,
                    "brief": brief,
                    "concept": concepts["PACKAGING_MACHINERY"],
                    "role": ContentBriefConceptLink.Role.TARGET_INDUSTRY,
                },
            ),
            (
                ContentBriefConceptLink,
                stable_id(432),
                {
                    "organization": organization,
                    "brief": brief,
                    "concept": concepts["DIN"],
                    "role": ContentBriefConceptLink.Role.STANDARD,
                },
            ),
        ))
        for model, row_id, fields in expected:
            if not model.objects.filter(pk=row_id).exists():
                row = model(id=row_id, **fields)
                models.Model.save(row, force_insert=True)

    @staticmethod
    def _accounts(organization, platforms):
        for index, code in enumerate(PLATFORM_CODES, start=1):
            credential, _ = ConnectorCredential.objects.update_or_create(
                id=stable_id(700 + index),
                defaults={
                    "organization": organization,
                    "platform": platforms[code],
                    "secret_reference": f"e2e-test://phase-a/{code.lower()}",
                    "granted_scopes": [AccountCapability.PUBLISH],
                    "expires_at": None,
                },
            )
            SocialAccount.objects.update_or_create(
                id=stable_id(800 + index),
                defaults={
                    "organization": organization,
                    "platform": platforms[code],
                    "credential": credential,
                    "external_id": f"phase-a-e2e-{code.lower()}",
                    "display_name": f"Phase A {PLATFORM_NAMES[code]} Mock",
                    "publish_mode": SocialAccount.PublishMode.API_AUTO,
                    "status": SocialAccount.Status.ACTIVE,
                    "connector_metadata": {
                        "mock_outcome": "fail_once" if code == "TIKTOK" else "success",
                        "fixture": "phase-a-e2e",
                    },
                },
            )

    @staticmethod
    def _prompt(created_by):
        prompt = PromptVersion.objects.filter(pk=PROMPT_ID).first()
        expected = {
            "purpose": "CONTENT_GENERATE",
            "code": "phase-a-e2e-content-v1",
            "provider": "fake",
            "model": "fake-v1",
            "template": "{product_name}|{target_country}|{target_platform}|{cta}|{concept_codes}",
            "output_schema": OUTPUT_SCHEMA,
            "version": 1,
            "status": PromptVersion.Status.PUBLISHED,
            "created_by": created_by,
        }
        if prompt is None:
            with ai_audit_writes():
                PromptVersion.objects.create(id=PROMPT_ID, **expected)
        elif any(getattr(prompt, field) != value for field, value in expected.items()):
            raise CommandError("Immutable Phase A prompt prerequisite drift was detected.")
