from urllib.parse import urlencode


INDUSTRY_TAXONOMY = {
    "mining": {"label": "Mining", "keywords": ("mining", "mine", "crusher", "mineral")},
    "cement": {"label": "Cement", "keywords": ("cement",)},
    "packaging": {"label": "Packaging Machinery", "keywords": ("packaging",)},
    "agriculture": {"label": "Agricultural Machinery", "keywords": ("agricultur", "farm", "harvester")},
    "automation": {"label": "Automation Equipment", "keywords": ("automation", "robot", "actuator")},
    "material_handling": {"label": "Material Handling", "keywords": ("material handling", "conveyor")},
    "pumps": {"label": "Pumps & Actuators", "keywords": ("pump", "hydraulic")},
    "industrial_machinery": {"label": "Industrial Machinery", "keywords": ("industrial machinery", "machinery", "equipment")},
    "gearbox_repair": {"label": "Gearbox Repair", "keywords": ("gearbox", "transmission repair")},
    "mro": {"label": "MRO / Maintenance", "keywords": ("mro", "maintenance")},
}

NEED_TAXONOMY = {
    "oem_production": {"label": "OEM Production", "keywords": ("oem", "production", "manufactur", "assembly")},
    "replacement": {"label": "Replacement", "keywords": ("replacement", "spare part", "repair", "rebuilt")},
    "reverse_engineering": {"label": "Reverse Engineering", "keywords": ("reverse engineering", "no drawing", "sample", "reverse engineer")},
}

PRODUCT_TAXONOMY = {
    "helical_gears": "helical-gears",
    "spur_gears": "spur-gears",
    "bevel_gears": "bevel-gears",
    "worm_gears": "worm-gears",
    "gear_racks": "gear-racks",
    "custom_gears": "custom-gears",
    "timing_pulleys": "timing-pulleys",
}

CAPABILITY_TAXONOMY = ("gear_grinding", "heat_treatment", "inspection", "reverse_engineering")


def classify_industry(text: str) -> str:
    lowered = text.casefold()
    for slug, config in INDUSTRY_TAXONOMY.items():
        if any(keyword in lowered for keyword in config["keywords"]):
            return slug
    return "industrial_machinery"


def classify_need(text: str) -> str:
    lowered = text.casefold()
    if any(keyword in lowered for keyword in NEED_TAXONOMY["reverse_engineering"]["keywords"]):
        return "reverse_engineering"
    if any(keyword in lowered for keyword in NEED_TAXONOMY["replacement"]["keywords"]):
        return "replacement"
    if any(keyword in lowered for keyword in NEED_TAXONOMY["oem_production"]["keywords"]):
        return "oem_production"
    return "oem_production"


def landing_page_path(industry: str, need: str) -> str:
    need_slug = {
        "oem_production": "custom-gears",
        "replacement": "replacement-gears",
        "reverse_engineering": "reverse-engineering-gears",
    }.get(need, "custom-gears")
    return f"/industries/{industry}/{need_slug}/"


def landing_page_url(industry: str, need: str) -> str:
    return f"https://sinfogear.com{landing_page_path(industry, need)}"


def tracked_landing_url(
    path: str,
    lead_id: str,
    *,
    source: str = "google_maps",
    medium: str = "email",
    campaign: str = "auto_discovery",
) -> str:
    query = urlencode({
        "utm_source": source,
        "utm_medium": medium,
        "utm_campaign": campaign,
        "lead_id": str(lead_id),
    })
    return f"https://sinfogear.com{path}?{query}"
