import json
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import SourceAdapterError, maps_governance_for


GOOGLE_PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_TIMEOUT_SECONDS = 15
GOOGLE_PLACES_MAX_RESPONSE_BYTES = 2_000_000
GOOGLE_PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,"
    "places.websiteUri,places.primaryType,places.types,"
    "places.nationalPhoneNumber,places.internationalPhoneNumber"
)


class GooglePlacesTransport(Protocol):
    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        api_key: str,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, object]: ...


class UrllibGooglePlacesTransport:
    def post_json(
        self,
        *,
        url: str,
        payload: dict[str, object],
        api_key: str,
        timeout_seconds: int,
        max_response_bytes: int,
    ) -> dict[str, object]:
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
            },
            method="POST",
        )
        try:
            response: HTTPResponse
            with urlopen(request, timeout=timeout_seconds) as response:
                body = response.read(max_response_bytes + 1)
        except HTTPError as error:
            if error.code == 400:
                raise SourceAdapterError("SOURCE_REJECTED_QUERY") from error
            if error.code in (401, 403):
                raise SourceAdapterError("SOURCE_AUTHENTICATION_FAILED") from error
            if error.code == 429:
                raise SourceAdapterError("SOURCE_RATE_LIMITED") from error
            if error.code >= 500:
                raise SourceAdapterError("SOURCE_UNAVAILABLE") from error
            raise SourceAdapterError("SOURCE_REJECTED_QUERY") from error
        except (TimeoutError, URLError) as error:
            raise SourceAdapterError("SOURCE_UNAVAILABLE") from error
        if len(body) > max_response_bytes:
            raise SourceAdapterError("SOURCE_RESPONSE_TOO_LARGE")
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SourceAdapterError("SOURCE_INVALID_RESPONSE") from error
        if not isinstance(decoded, dict):
            raise SourceAdapterError("SOURCE_INVALID_RESPONSE")
        return decoded


@dataclass(frozen=True)
class MapsQuery:
    text_query: str
    region_code: str
    limit: int = 20

    def __post_init__(self):
        if not isinstance(self.text_query, str) or not (1 <= len(self.text_query.strip()) <= 200):
            raise ValueError("Maps text query must be between 1 and 200 characters.")
        if (
            not isinstance(self.region_code, str)
            or len(self.region_code) != 2
            or not self.region_code.isalpha()
        ):
            raise ValueError("Maps region code must be a two letter country code.")
        if not 1 <= self.limit <= 20:
            raise ValueError("Maps result limit must be between 1 and 20.")


@dataclass(frozen=True)
class MapsPlace:
    place_id: str
    name: str
    address: str
    website: str
    phone: str
    primary_type: str
    types: tuple[str, ...]
    country_code: str
    source_url: str


@dataclass(frozen=True)
class MapsBatch:
    places: tuple[MapsPlace, ...]
    capability_snapshot: dict[str, object]
    skipped_count: int = 0
    total_count: int = 0
    is_demo: bool = False


class GooglePlacesSource:
    source_code = "GOOGLE_MAPS"

    def __init__(
        self,
        *,
        api_key: str,
        transport: GooglePlacesTransport | None = None,
        timeout_seconds: int = GOOGLE_PLACES_TIMEOUT_SECONDS,
        max_response_bytes: int = GOOGLE_PLACES_MAX_RESPONSE_BYTES,
    ):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("Google Maps API key is required.")
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("Google Places timeout must be between 1 and 30 seconds.")
        if not 100_000 <= max_response_bytes <= GOOGLE_PLACES_MAX_RESPONSE_BYTES:
            raise ValueError(
                "Google Places response limit must be between 100000 and 2000000 bytes."
            )
        self.api_key = api_key.strip()
        self.transport = transport or UrllibGooglePlacesTransport()
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes

    def fetch(self, query: MapsQuery) -> MapsBatch:
        payload = {
            "textQuery": query.text_query.strip(),
            "pageSize": query.limit,
            "languageCode": "en",
            "regionCode": query.region_code.upper(),
        }
        decoded = self.transport.post_json(
            url=GOOGLE_PLACES_SEARCH_URL,
            payload=payload,
            api_key=self.api_key,
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
        )
        raw_places = decoded.get("places", [])
        if not isinstance(raw_places, list):
            raise SourceAdapterError("SOURCE_INVALID_RESPONSE")
        places = []
        skipped_count = 0
        for raw in raw_places[: query.limit]:
            place = _normalize_place(raw, region_code=query.region_code.upper())
            if place is None:
                skipped_count += 1
            else:
                places.append(place)
        return MapsBatch(
            places=tuple(places),
            capability_snapshot={
                "source": self.source_code,
                "capture_method": "OFFICIAL_PUBLIC_API",
                "authentication": "API_KEY",
                "result_limit": query.limit,
                "governance": maps_governance_for(self.source_code),
            },
            skipped_count=skipped_count,
            total_count=len(raw_places),
        )


def _normalize_place(raw, *, region_code: str) -> MapsPlace | None:
    if not isinstance(raw, dict):
        return None
    place_id = _bounded_text(raw.get("id"), 200)
    name = _display_text(raw.get("displayName"))
    if not place_id or not name:
        return None
    types = tuple(dict.fromkeys(
        _bounded_text(value, 100)
        for value in (raw.get("types") or [])
        if _bounded_text(value, 100)
    ))
    return MapsPlace(
        place_id=place_id,
        name=name,
        address=_bounded_text(raw.get("formattedAddress"), 400),
        website=_safe_website(raw.get("websiteUri")),
        phone=_bounded_text(
            raw.get("nationalPhoneNumber") or raw.get("internationalPhoneNumber"),
            40,
        ),
        primary_type=_bounded_text(raw.get("primaryType"), 100),
        types=types,
        country_code=region_code,
        source_url=f"https://www.google.com/maps/place/?q=place_id:{place_id}",
    )


def _display_text(value) -> str:
    if not isinstance(value, dict):
        return ""
    return _bounded_text(value.get("text"), 300)


def _safe_website(value) -> str:
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.startswith(("http://", "https://")):
        return text[:2048]
    return ""


def _bounded_text(value, maximum: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ""
    text = str(value).strip()
    return text if len(text) <= maximum else ""
