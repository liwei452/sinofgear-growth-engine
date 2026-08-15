from .market_pilots import matched_gear_terms


INDUSTRY_HINTS = (
    "industrial",
    "manufactur",
    "machinery",
    "gearbox",
    "conveyor",
    "crusher",
    "mining",
    "cement",
    "agricultur",
    "packaging",
    "engineer",
    "equipment",
    "supplier",
)
TARGET_COUNTRIES = {"VN", "ID", "PH", "ZA"}


def grade_candidate(*, primary_type="", types=(), website="", country="") -> tuple[int, str, dict]:
    text = " ".join(filter(None, [primary_type, *types])).casefold()
    industry_hits = [term for term in INDUSTRY_HINTS if term in text]
    gear_terms = matched_gear_terms(text)
    industry_score = min(35, 12 * len(industry_hits))
    gear_score = 18 if gear_terms else 0
    website_score = 15 if website else 0
    country_score = 15 if country.upper() in TARGET_COUNTRIES else 5
    total = industry_score + gear_score + website_score + country_score
    grade = "A" if total >= 70 else ("B" if total >= 45 else "C")
    return total, grade, {
        "industry_relevance": industry_score,
        "gear_relevance": gear_score,
        "website_signal": website_score,
        "country_fit": country_score,
        "industry_hits": industry_hits,
        "gear_terms": gear_terms,
    }
