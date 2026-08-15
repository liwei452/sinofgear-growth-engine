from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from urllib.parse import urlparse


class PartyRole(StrEnum):
    IMPORTER = "IMPORTER"
    CONSIGNEE = "CONSIGNEE"
    SHIPPER = "SHIPPER"
    NOTIFY_PARTY = "NOTIFY_PARTY"


@dataclass(frozen=True)
class TradeParty:
    role: PartyRole
    raw_name: str
    normalized_name: str
    country_code: str
    entity_match_confidence: int
    freight_forwarder_review: bool


@dataclass(frozen=True)
class EnterpriseTradeRecord:
    external_record_id: str
    shipment_date: date
    hs_code: str
    parties: tuple[TradeParty, ...]
    source_owner: str
    license_contract: str
    allowed_fields: tuple[str, ...]
    retention_days: int
    redistribution_allowed: bool
    source_url: str


def validate_enterprise_trade_record(record: EnterpriseTradeRecord) -> EnterpriseTradeRecord:
    if not record.source_owner.strip():
        raise ValueError("Source owner is required.")
    if not record.license_contract.strip():
        raise ValueError("A verifiable license contract is required.")
    if not record.allowed_fields:
        raise ValueError("Licensed allowed fields are required.")
    if not 1 <= record.retention_days <= 3650:
        raise ValueError("Licensed retention must be between 1 and 3650 days.")
    if not record.parties:
        raise ValueError("At least one shipment party is required.")
    if not record.external_record_id.strip() or len(record.external_record_id) > 255:
        raise ValueError("A bounded external record id is required.")
    if len(record.hs_code) not in {4, 6} or not record.hs_code.isdigit():
        raise ValueError("HS code must contain four or six digits.")
    parsed = urlparse(record.source_url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("A verifiable HTTPS source URL is required.")
    for party in record.parties:
        if party.role not in set(PartyRole):
            raise ValueError("Unsupported shipment party role.")
        if not party.raw_name.strip() or not party.normalized_name.strip():
            raise ValueError("Party raw and normalized entity names are required.")
        if len(party.country_code) != 3 or not party.country_code.isalpha():
            raise ValueError("Party country must use a three-letter code.")
        if not 0 <= party.entity_match_confidence <= 100:
            raise ValueError("Entity match confidence must be between 0 and 100.")
    return record
