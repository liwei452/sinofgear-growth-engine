import hashlib
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from integrations.secrets import decrypt_secret
from integrations.sources.base import SourceAdapterError, maps_governance_for
from integrations.sources.google_places import GooglePlacesSource, MapsQuery

from .models import DiscoveryCandidate, GoogleMapsDiscoveryConfig
from .grading import grade_candidate


COUNTRY_NAMES = {
    "VN": "Vietnam",
    "ID": "Indonesia",
    "PH": "Philippines",
    "ZA": "South Africa",
}


class MapsDiscoveryNotEnabled(RuntimeError):
    pass


class MapsDiscoveryMissingKey(RuntimeError):
    pass


def run_maps_discovery(config_id, *, trigger, source_factory=None) -> dict:
    api_key, quota, cities, keywords = _prepared(config_id)
    source = source_factory(api_key) if source_factory else GooglePlacesSource(api_key=api_key)

    places = []
    fetched = 0
    skipped = 0
    reached_quota = False
    try:
        for city in cities:
            for keyword in keywords:
                if len(places) >= quota:
                    reached_quota = True
                    break
                query = MapsQuery(
                    text_query=f"{keyword} {city['name']}",
                    region_code=city["country_code"],
                    limit=20,
                )
                batch = source.fetch(query)
                fetched += batch.total_count or len(batch.places)
                skipped += batch.skipped_count
                for place in batch.places:
                    if len(places) >= quota:
                        reached_quota = True
                        break
                    places.append((place, batch.is_demo))
            if reached_quota:
                break
    except SourceAdapterError as error:
        _record_failure(config_id, error.code)
        raise

    return _ingest_places(
        config_id=config_id,
        places=places,
        fetched=fetched,
        skipped=skipped,
        trigger=trigger,
    )


@transaction.atomic
def _prepared(config_id):
    config = GoogleMapsDiscoveryConfig.objects.select_for_update().get(pk=config_id)
    if not config.enabled:
        raise MapsDiscoveryNotEnabled("Google Maps discovery is disabled.")
    if not config.api_key_ciphertext:
        _record_failure(config_id, "API_KEY_NOT_CONFIGURED")
        raise MapsDiscoveryMissingKey("Google Maps API key is not configured.")
    try:
        api_key = decrypt_secret(config.api_key_ciphertext)
    except ValueError:
        _record_failure(config_id, "API_KEY_DECRYPT_FAILED")
        raise
    return api_key, max(1, config.daily_quota), _normalize_cities(config.cities), _normalize_keywords(config.keywords)


@transaction.atomic
def _ingest_places(*, config_id, places, fetched, skipped, trigger) -> dict:
    config = GoogleMapsDiscoveryConfig.objects.select_for_update().get(pk=config_id)
    created = 0
    duplicates = 0
    for place, is_demo in places:
        record_hash = _record_hash(place.place_id)
        score, grade, score_breakdown = grade_candidate(
            primary_type=place.primary_type,
            types=place.types,
            website=place.website,
            country=place.country_code,
        )
        candidate, was_created = DiscoveryCandidate.objects.get_or_create(
            organization=config.organization,
            record_hash=record_hash,
            defaults={
                "company_name": place.name[:255],
                "country": COUNTRY_NAMES.get(place.country_code, place.country_code),
                "website": place.website or "",
                "industry": place.primary_type or (place.types[0] if place.types else ""),
                "import_format": "GOOGLE_MAPS",
                "source_governance": _governance_payload(place),
                "raw_record": _raw_record(place),
                "is_demo": is_demo,
                "score": score,
                "grade": grade,
                "score_breakdown": score_breakdown,
            },
        )
        if was_created:
            created += 1
        else:
            duplicates += 1
    now = timezone.now()
    config.last_succeeded_at = now
    config.next_run_at = now + timedelta(hours=24)
    config.consecutive_failures = 0
    config.last_error_code = ""
    config.save(update_fields=[
        "last_succeeded_at", "next_run_at", "consecutive_failures",
        "last_error_code", "updated_at",
    ])
    return {
        "config_id": str(config.id),
        "trigger": trigger,
        "fetched_count": fetched,
        "created_count": created,
        "duplicate_count": duplicates,
        "skipped_count": skipped,
    }


@transaction.atomic
def _record_failure(config_id, error_code):
    config = GoogleMapsDiscoveryConfig.objects.select_for_update().get(pk=config_id)
    now = timezone.now()
    failures = min(config.consecutive_failures + 1, 10)
    backoff_hours = min(2 ** (failures - 1), 24)
    config.consecutive_failures = failures
    config.last_error_code = error_code
    config.next_run_at = now + timedelta(hours=backoff_hours)
    config.save(update_fields=[
        "consecutive_failures", "last_error_code", "next_run_at", "updated_at",
    ])


def run_due_maps_configs(*, limit=25, source_factory=None) -> dict:
    now = timezone.now()
    config_ids = list(
        GoogleMapsDiscoveryConfig.objects.filter(enabled=True)
        .filter(Q(next_run_at__isnull=True) | Q(next_run_at__lte=now))
        .order_by("next_run_at", "id")
        .values_list("id", flat=True)[:limit]
    )
    result = {"scanned": len(config_ids), "succeeded": 0, "failed": 0}
    for config_id in config_ids:
        try:
            run_maps_discovery(
                config_id,
                trigger="SCHEDULED",
                source_factory=source_factory,
            )
        except (SourceAdapterError, MapsDiscoveryNotEnabled, MapsDiscoveryMissingKey, ValueError):
            result["failed"] += 1
        else:
            result["succeeded"] += 1
    return result


def _normalize_cities(cities):
    if not isinstance(cities, list):
        return []
    normalized = []
    for city in cities:
        if not isinstance(city, dict):
            continue
        name = str(city.get("name") or "").strip()
        code = str(city.get("country_code") or "").strip().upper()
        if name and len(code) == 2 and code.isalpha():
            normalized.append({"name": name, "country_code": code})
    return normalized


def _normalize_keywords(keywords):
    if not isinstance(keywords, list):
        return []
    return [
        str(keyword).strip()
        for keyword in keywords
        if 1 <= len(str(keyword).strip()) <= 200
    ]


def _record_hash(place_id: str) -> str:
    return hashlib.sha256(f"google-maps:{place_id}".encode("utf-8")).hexdigest()


def _governance_payload(place) -> dict:
    governance = maps_governance_for("GOOGLE_MAPS")
    governance["place_id"] = place.place_id
    governance["source_url"] = place.source_url
    return governance


def _raw_record(place) -> dict:
    return {
        "place_id": place.place_id,
        "name": place.name,
        "address": place.address,
        "website": place.website,
        "phone": place.phone,
        "primary_type": place.primary_type,
        "types": list(place.types),
        "country_code": place.country_code,
        "source_url": place.source_url,
    }
