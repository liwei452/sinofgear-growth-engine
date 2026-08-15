import re


def infer_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    parts = [part for part in re.split(r"[._\-+]+", local) if part]
    if not parts:
        return email
    cleaned = [re.sub(r"\d+$", "", part) for part in parts]
    cleaned = [part for part in cleaned if part]
    words = cleaned or parts
    return " ".join(word.capitalize() for word in words[:2])
