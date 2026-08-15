import re


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
ROLE_HINTS = (
    "procurement", "purchasing", "supply chain", "buyer",
    "maintenance manager", "engineering manager", "operations manager",
    "managing director", "plant manager", "maintenance engineer",
    "head of maintenance", "director", "general manager",
)


def infer_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    parts = [part for part in re.split(r"[._\-+]+", local) if part]
    if not parts:
        return email
    cleaned = [re.sub(r"\d+$", "", part) for part in parts]
    cleaned = [part for part in cleaned if part]
    words = cleaned or parts
    return " ".join(word.capitalize() for word in words[:2])


def extract_team_contacts(html: str, base_url: str) -> list[dict]:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    results = []
    seen = set()
    for email in EMAIL_RE.findall(text):
        normalized = email.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        index = text.casefold().find(normalized)
        context = text[max(0, index - 160):index + len(normalized) + 60]
        role = next((hint for hint in ROLE_HINTS if hint in context.casefold()), "")
        results.append({
            "email": normalized,
            "name_hint": infer_name_from_email(normalized),
            "role_hint": role,
            "source_url": base_url,
            "verification_status": "UNVERIFIED",
        })
    return results
