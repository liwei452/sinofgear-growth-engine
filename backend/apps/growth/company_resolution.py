import re

from .models import TargetAccount, TradeCompanyMatch


LEGAL_SUFFIXES = {
    "inc", "llc", "ltd", "co", "corp", "pty", "sdn", "bhd", "gmbh",
    "ag", "sa", "spa", "srl", "bv", "nv", "kk", "pte", "sas",
}


def normalize_company_name(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()
    tokens = [token for token in text.split() if token not in LEGAL_SUFFIXES]
    return " ".join(tokens)


def match_company_by_importer(organization, importer_name, country_code):
    normalized = normalize_company_name(importer_name)
    if not normalized:
        return None, "NO_MATCH", 0.0
    accounts = TargetAccount.objects.filter(organization=organization)
    for account in accounts:
        if normalize_company_name(account.name) == normalized:
            return account, "EXACT_NAME", 1.0
    for account in accounts:
        account_normalized = normalize_company_name(account.name)
        if not account_normalized or len(account_normalized) < 4:
            continue
        if account_normalized in normalized or normalized in account_normalized:
            return account, "PARTIAL_NAME", 0.7
    return None, "NO_MATCH", 0.0


def record_trade_company_match(*, organization, importer_name, country_code):
    account, method, confidence = match_company_by_importer(
        organization, importer_name, country_code,
    )
    match, _ = TradeCompanyMatch.objects.get_or_create(
        organization=organization,
        importer_name=importer_name,
        country_code=country_code,
        defaults={
            "account": account,
            "method": method,
            "confidence": confidence,
        },
    )
    return match
