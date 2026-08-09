import hashlib
from decimal import Decimal
from io import BytesIO
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import BaseCommand, CommandError, call_command
from django.db import transaction

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
from apps.identity.models import Membership, Organization, Role
from apps.knowledge.models import KnowledgeConcept
from apps.platforms.codes import AccountCapability
from apps.platforms.models import ConnectorCredential, Platform, SocialAccount


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
        storage = get_object_storage()
        storage.put(BytesIO(VIDEO_BYTES), storage_key)
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
