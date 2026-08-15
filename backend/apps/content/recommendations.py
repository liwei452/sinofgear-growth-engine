from dataclasses import asdict, dataclass
from uuid import UUID

from django.db.models import Q
from django.db import transaction
from jsonschema import ValidationError as JSONSchemaValidationError
from jsonschema.validators import validator_for

from apps.assets.models import ProductEvidenceFact
from apps.catalog.models import Product
from apps.growth.models import MarketCountryProfile
from apps.platforms.models import Platform

from .models import ContentRecommendation, ContentRecommendationOption


MAX_RECOMMENDATION_TEXT = 2_000
DEFAULT_MARKET_LANGUAGES = {
    "CA": "en", "EG": "ar", "GB": "en", "ID": "id", "KE": "en",
    "MA": "fr", "NG": "en", "PH": "en", "US": "en", "VN": "vi", "ZA": "en",
}

OPTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "product_id", "market_code", "language", "customer_profile",
        "channel_codes", "theme", "rationale", "fact_ids", "missing_information",
    ],
    "properties": {
        "product_id": {"type": "string", "format": "uuid", "maxLength": 36},
        "market_code": {"type": "string", "minLength": 2, "maxLength": 3},
        "language": {"type": "string", "minLength": 2, "maxLength": 16},
        "customer_profile": {"type": "string", "minLength": 1, "maxLength": 255},
        "channel_codes": {
            "type": "array", "minItems": 1, "maxItems": 5, "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 64},
        },
        "theme": {"type": "string", "minLength": 1, "maxLength": 500},
        "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
        "fact_ids": {
            "type": "array", "minItems": 1, "maxItems": 20, "uniqueItems": True,
            "items": {"type": "string", "format": "uuid", "maxLength": 36},
        },
        "missing_information": {
            "type": "array", "maxItems": 20, "uniqueItems": True,
            "items": {"type": "string", "minLength": 1, "maxLength": 500},
        },
    },
}

RECOMMENDATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["options"],
    "properties": {
        "options": {
            "type": "array", "minItems": 3, "maxItems": 3,
            "items": OPTION_SCHEMA,
        }
    },
}


class ContentRecommendationError(ValueError):
    pass


@dataclass(frozen=True)
class RecommendationInput:
    organization_id: str
    products: tuple[dict, ...]
    facts: tuple[dict, ...]
    markets: tuple[dict, ...]
    channels: tuple[str, ...]
    languages: tuple[str, ...]

    @property
    def product_ids(self):
        return tuple(item["id"] for item in self.products)

    @property
    def fact_ids(self):
        return tuple(item["id"] for item in self.facts)

    def to_dict(self):
        return asdict(self)


def build_recommendation_input(organization_id: UUID) -> RecommendationInput:
    products = tuple(
        {
            "id": str(product.id),
            "name": product.name_en,
            "manufacturing_capabilities": product.manufacturing_capabilities,
            "inspection_capabilities": product.inspection_capabilities,
        }
        for product in Product.objects.filter(
            organization_id=organization_id, status=Product.Status.ACTIVE
        ).order_by("name_en", "id")
    )
    if not products:
        raise ContentRecommendationError("At least one active product is required.")
    product_ids = {item["id"] for item in products}
    facts = tuple(
        {
            "id": str(fact.id),
            "product_id": str(fact.product_id),
            "field": fact.field_name,
            "value": fact.value,
            "category": fact.category,
            "source_asset_id": str(fact.asset_id),
            "source_page": fact.source_page,
            "source_excerpt": fact.source_excerpt,
            "is_demo": fact.is_demo,
        }
        for fact in ProductEvidenceFact.objects.filter(
            organization_id=organization_id,
            product_id__in=product_ids,
            review_status=ProductEvidenceFact.ReviewStatus.VERIFIED,
        ).order_by("product_id", "source_page", "id")
    )
    if not facts:
        raise ContentRecommendationError(
            "At least one verified product facts record is required."
        )
    markets = tuple(
        {
            "code": market.country_code.upper(),
            "label": market.country_label,
            "status": market.status,
            "path_family": market.path_family,
            "suitable_industries": market.suitable_industries,
            "recommendation_reasons": market.recommendation_reasons,
            "is_demo": market.is_demo,
        }
        for market in MarketCountryProfile.objects.filter(
            organization_id=organization_id,
        ).filter(
            Q(is_watched=True)
            | Q(status__in=[
                MarketCountryProfile.Status.SMALL_PILOT,
                MarketCountryProfile.Status.ACTIVE_MARKET,
            ])
        ).exclude(status=MarketCountryProfile.Status.PAUSED).order_by(
            "priority_order", "country_code"
        )[:20]
    )
    if not markets:
        raise ContentRecommendationError("At least one selected market is required.")
    channels = tuple(
        Platform.objects.order_by("code").values_list("code", flat=True)
    )
    if not channels:
        raise ContentRecommendationError("At least one content channel is required.")
    languages = tuple(sorted({
        DEFAULT_MARKET_LANGUAGES.get(market["code"], "en") for market in markets
    }))
    return RecommendationInput(
        organization_id=str(organization_id),
        products=products,
        facts=facts,
        markets=markets,
        channels=channels,
        languages=languages,
    )


def _allowed_values(allowed_input, key):
    if isinstance(allowed_input, RecommendationInput):
        if key == "product_ids":
            return set(allowed_input.product_ids)
        if key == "fact_ids":
            return set(allowed_input.fact_ids)
        if key == "market_codes":
            return {item["code"] for item in allowed_input.markets}
        if key == "channel_codes":
            return set(allowed_input.channels)
        if key == "languages":
            return set(allowed_input.languages)
    return {str(value) for value in allowed_input.get(key, [])}


def validate_recommendation_output(payload, allowed_input):
    try:
        validator_class = validator_for(RECOMMENDATION_SCHEMA)
        validator_class.check_schema(RECOMMENDATION_SCHEMA)
        validator_class(RECOMMENDATION_SCHEMA).validate(payload)
    except (JSONSchemaValidationError, ValueError, TypeError) as exc:
        raise ContentRecommendationError(
            "Recommendation output does not match the required schema."
        ) from exc
    allowed_products = _allowed_values(allowed_input, "product_ids")
    allowed_facts = _allowed_values(allowed_input, "fact_ids")
    allowed_markets = _allowed_values(allowed_input, "market_codes")
    allowed_channels = _allowed_values(allowed_input, "channel_codes")
    allowed_languages = _allowed_values(allowed_input, "languages")
    normalized = []
    identities = set()
    for position, raw in enumerate(payload["options"], start=1):
        product_id = str(raw["product_id"])
        market_code = raw["market_code"].strip().upper()
        language = raw["language"].strip().lower()
        fact_ids = [str(value) for value in raw["fact_ids"]]
        channel_codes = [value.strip().upper() for value in raw["channel_codes"]]
        if product_id not in allowed_products:
            raise ContentRecommendationError("Recommendation referenced an unknown product.")
        if any(fact_id not in allowed_facts for fact_id in fact_ids):
            raise ContentRecommendationError("Recommendation referenced an unknown fact.")
        if market_code not in allowed_markets:
            raise ContentRecommendationError("Recommendation referenced an unknown market.")
        if language not in allowed_languages:
            raise ContentRecommendationError("Recommendation referenced an unknown language.")
        if any(channel not in allowed_channels for channel in channel_codes):
            raise ContentRecommendationError("Recommendation referenced an unknown channel.")
        identity = (
            product_id, market_code, language, raw["customer_profile"].strip(), raw["theme"].strip()
        )
        if identity in identities:
            raise ContentRecommendationError("Recommendation options must be meaningfully different.")
        identities.add(identity)
        normalized.append({
            "position": position,
            "product_id": product_id,
            "market_code": market_code,
            "language": language,
            "customer_profile": raw["customer_profile"].strip(),
            "channel_codes": channel_codes,
            "theme": raw["theme"].strip(),
            "rationale": raw["rationale"].strip(),
            "evidence": [{"fact_id": fact_id} for fact_id in fact_ids],
            "missing_information": [value.strip() for value in raw["missing_information"]],
        })
    return normalized


def validate_recommendation_snapshot(snapshot, *, organization_id):
    if not isinstance(snapshot, dict) or snapshot.get("organization_id") != str(organization_id):
        raise ContentRecommendationError("Recommendation input organization is invalid.")
    required_lists = ("products", "facts", "markets", "channels", "languages")
    if any(not isinstance(snapshot.get(key), (list, tuple)) or not snapshot[key] for key in required_lists):
        raise ContentRecommendationError("Recommendation input is incomplete.")
    allowed = {
        "product_ids": [row.get("id") for row in snapshot["products"] if isinstance(row, dict)],
        "fact_ids": [row.get("id") for row in snapshot["facts"] if isinstance(row, dict)],
        "market_codes": [row.get("code") for row in snapshot["markets"] if isinstance(row, dict)],
        "channel_codes": snapshot["channels"],
        "languages": snapshot["languages"],
    }
    if any(not values or any(not isinstance(value, str) or not value for value in values) for values in allowed.values()):
        raise ContentRecommendationError("Recommendation input is incomplete.")
    return allowed


@transaction.atomic
def finalize_recommendation_result(run, output):
    recommendation = ContentRecommendation.objects.select_for_update().get(
        job=run.job, organization=run.organization
    )
    allowed = validate_recommendation_snapshot(
        run.input_snapshot, organization_id=run.organization_id
    )
    options = validate_recommendation_output(output, allowed)
    if recommendation.options.exists():
        if recommendation.status != ContentRecommendation.Status.READY:
            raise ContentRecommendationError("Existing recommendation options are inconsistent.")
        return {"type": "content_recommendation", "id": str(recommendation.id)}
    rows = []
    for option in options:
        row = ContentRecommendationOption(
            organization=recommendation.organization,
            recommendation=recommendation,
            **option,
        )
        row.full_clean()
        rows.append(row)
    ContentRecommendationOption.objects.bulk_create(rows)
    recommendation.status = ContentRecommendation.Status.READY
    recommendation.save(update_fields=["status", "updated_at"])
    return {"type": "content_recommendation", "id": str(recommendation.id)}
