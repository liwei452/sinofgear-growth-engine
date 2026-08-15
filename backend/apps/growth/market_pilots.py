from collections.abc import Iterable
from datetime import date


def _country(
    country_code, country_label, status, route, route_label, recommended_wave,
    source_types, recommendation_reasons, hold_reasons,
):
    return {
        "country_code": country_code,
        "country_label": country_label,
        "status": status,
        "route": route,
        "route_label": route_label,
        "recommended_wave": recommended_wave,
        "source_types": source_types,
        "last_updated_at": "2026-08-15",
        "scores": {
            "data_availability": None,
            "demand_strength": None,
            "purchase_intent": None,
            "company_reachability": None,
            "commercial_execution": None,
            "weighted_total": None,
        },
        "sample_quality": {
            "raw_sample_count": 0,
            "named_buyer_rate": None,
            "active_entity_match_rate": None,
            "duplicate_rate": None,
            "evidence_company_count": 0,
            "evidence_company_threshold": 20,
        },
        "recommendation_reasons": recommendation_reasons,
        "hold_reasons": hold_reasons,
    }


MARKETS = (
    _country("IDN", "印度尼西亚", "ACTIVE_MARKET", "STRONG_CUSTOMS_DATA", "强海关数据路线", "当前试点", ["DIRECT_CUSTOMS", "CARRIER_BOL", "COMPANY_WEB"], ["验证企业级交易数据能否提高有效销售对话率"], ["付费数据接入前仍需核验 200 条样本和合同许可"]),
    _country("ZAF", "南非", "ACTIVE_MARKET", "MIXED_SIGNALS", "混合信号路线", "当前试点", ["AGGREGATE_TRADE", "TENDER", "COMPANY_WEB"], ["官方招投标和矿业、工业维修场景适合混合信号验证"], ["宏观贸易只能作为市场背景，不能冒充公司采购证据"]),
    _country("CHL", "智利", "DATA_VALIDATION", "TRADE_TENDER_WEB", "交易数据 + 招投标 + 官网", "下一优先", ["CARRIER_BOL", "TENDER", "COMPANY_WEB"], ["矿业 MRO、企业交易数据和 ChileCompra 开放采购信号结构完整"], ["先完成 200 条样本与 20 家独立证据客户门槛"]),
    _country("VNM", "越南", "DATA_VALIDATION", "SECOND_PHASE", "第二阶段", "第二阶段", ["CARRIER_BOL", "COMPANY_WEB"], ["制造业需求潜力高"], ["公开样例新鲜度和字段覆盖仍需核验"]),
    _country("PHL", "菲律宾", "DATA_VALIDATION", "SECOND_PHASE", "第二阶段", "第二阶段", ["DIRECT_CUSTOMS", "COMPANY_WEB"], ["供应商声称有企业级报关记录"], ["必须先核验原始样本、更新频率和许可范围"]),
    _country("PER", "秘鲁", "OBSERVATION_POOL", "LATAM_REPLICATION", "拉美复制", "第四波", ["CARRIER_BOL", "TENDER", "COMPANY_WEB"], ["可复用智利的西班牙语词库和实体清洗规则"], ["等待智利路线验证"]),
    _country("COL", "哥伦比亚", "OBSERVATION_POOL", "LATAM_REPLICATION", "拉美复制", "第四波", ["CARRIER_BOL", "TENDER", "COMPANY_WEB"], ["SECOP II 提供开放采购数据"], ["等待智利路线验证"]),
    _country("MEX", "墨西哥", "OBSERVATION_POOL", "LATER_SCALE", "后续规模市场", "第五波", ["AGGREGATE_TRADE", "TENDER", "COMPANY_WEB"], ["大型制造业市场潜力高"], ["税务、竞争与本地执行更复杂"]),
    _country("BRA", "巴西", "OBSERVATION_POOL", "LATER_SCALE", "后续规模市场", "第五波", ["AGGREGATE_TRADE", "TENDER", "COMPANY_WEB"], ["矿业、糖业和 PNCP 开放采购具备潜力"], ["葡萄牙语、税务和本地执行成本较高"]),
    _country("IND", "印度", "OBSERVATION_POOL", "CONDITIONAL_TENDER_WEB", "条件市场", "条件观察", ["TENDER", "COMPANY_WEB"], ["需求规模与官方招投标价值高"], ["只有供应商提交可核验授权与合同许可后才能使用主体报关数据"]),
    _country("TUR", "土耳其", "OBSERVATION_POOL", "CONDITIONAL", "条件市场", "条件观察", ["MIRROR_TRADE", "TENDER", "COMPANY_WEB"], ["贸易与招标信号可评估"], ["先检查数据新鲜度、付款风险和经销商模式"]),
    _country("PAK", "巴基斯坦", "OBSERVATION_POOL", "CONDITIONAL", "条件市场", "条件观察", ["MIRROR_TRADE", "TENDER", "COMPANY_WEB"], ["存在工业设备需求信号"], ["先检查付款风险、数据质量和商业执行性"]),
    _country("MAR", "摩洛哥", "OBSERVATION_POOL", "TENDER_EXPERIMENT", "招投标实验", "实验波次", ["TENDER", "COMPANY_WEB"], ["适合验证招投标与企业目录组合"], ["尚未验证企业级直接海关数据"]),
    _country("SAU", "沙特", "OBSERVATION_POOL", "TENDER_EXPERIMENT", "招投标实验", "实验波次", ["TENDER", "COMPANY_WEB"], ["官方采购与工业项目可形成意向信号"], ["尚未验证企业级直接海关数据"]),
    _country("GHA", "加纳", "OBSERVATION_POOL", "TENDER_EXPERIMENT", "招投标实验", "实验波次", ["TENDER", "COMPANY_WEB"], ["适合小规模混合信号实验"], ["尚未验证企业级直接海关数据"]),
)

SCORE_WEIGHTS = {
    "data_availability": 25,
    "demand_strength": 25,
    "purchase_intent": 20,
    "company_reachability": 15,
    "commercial_execution": 15,
}

QUALITY_GATE = {
    "minimum_raw_samples": 200,
    "minimum_named_buyer_rate": 80,
    "minimum_active_entity_match_rate": 70,
    "maximum_median_record_age_days": 90,
    "maximum_duplicate_rate": 10,
    "license_required": True,
}

SEARCH_POLICY = {
    "hs_codes": ["848340", "848390"],
    "include_terms": [
        "gear shaft", "ring gear", "spur gear", "helical gear", "bevel gear",
        "pinion", "worm wheel", "custom gear", "transmission gear",
    ],
    "exclude_terms": [
        "complete gearbox", "ball screw", "roller screw",
        "generic automotive parts", "unrelated machinery",
    ],
}

VALIDATION_GOALS = {
    "reviewed_valid_companies": 50,
    "sales_conversations": 15,
    "positive_intent_signals": 5,
    "progressed_opportunities": 2,
    "weeks": 8,
}

COMPANY_EVIDENCE_SOURCE_TYPES = {
    "DIRECT_CUSTOMS", "CARRIER_BOL", "MIRROR_TRADE", "TENDER", "COMPANY_WEB",
}


def validate_company_evidence_source(source_type: str) -> None:
    if source_type == "AGGREGATE_TRADE":
        raise ValueError("AGGREGATE_TRADE is market context only")
    if source_type not in COMPANY_EVIDENCE_SOURCE_TYPES:
        raise ValueError("Unsupported company evidence source type")


def matched_gear_terms(text: str) -> list[str]:
    lowered = text.casefold()
    matches = [term for term in SEARCH_POLICY["include_terms"] if term in lowered]
    if not matches and "gear" in lowered:
        return ["gear"]
    return matches


def market_profiles_for(organization):
    from .models import MarketCountryProfile

    for priority_order, market in enumerate(MARKETS):
        MarketCountryProfile.objects.get_or_create(
            organization=organization,
            country_code=market["country_code"],
            defaults={
                "country_label": market["country_label"],
                "status": market["status"],
                "route": market["route"],
                "route_label": market["route_label"],
                "recommended_wave": market["recommended_wave"],
                "priority_order": priority_order,
                "source_types": market["source_types"],
                "last_researched_at": date.fromisoformat(market["last_updated_at"]),
                "scores": market["scores"],
                "sample_quality": market["sample_quality"],
                "recommendation_reasons": market["recommendation_reasons"],
                "hold_reasons": market["hold_reasons"],
            },
        )
    return list(MarketCountryProfile.objects.filter(organization=organization))


def _market_payload(market):
    if isinstance(market, dict):
        return market
    return {
        "country_code": market.country_code,
        "country_label": market.country_label,
        "status": market.status,
        "route": market.route,
        "route_label": market.route_label,
        "recommended_wave": market.recommended_wave,
        "source_types": market.source_types,
        "last_updated_at": market.last_researched_at.isoformat(),
        "scores": market.scores,
        "sample_quality": market.sample_quality,
        "recommendation_reasons": market.recommendation_reasons,
        "hold_reasons": market.hold_reasons,
    }


def market_pilot_summary(*, signals: Iterable, accounts: Iterable, profiles=None) -> dict:
    account_countries = {str(account.id): account.country for account in accounts}
    metrics = {
        market["country_code"]: {
            "effective_customer_rate": None,
            "positive_reply_rate": None,
            "source_cost_micros": 0,
            "raw_sample_count": 0,
        }
        for market in MARKETS
    }
    aliases = {
        "Indonesia": "IDN", "IDN": "IDN",
        "South Africa": "ZAF", "ZAF": "ZAF",
        "Vietnam": "VNM", "VNM": "VNM",
        "Philippines": "PHL", "PHL": "PHL",
    }
    for signal in signals:
        country_code = aliases.get(account_countries.get(str(signal.account_id), ""))
        if not country_code:
            continue
        market_metrics = metrics[country_code]
        market_metrics["raw_sample_count"] += 1
        market_metrics["source_cost_micros"] += int(
            (signal.evidence_envelope or {}).get("source_cost_micros", 0)
        )
    markets = [_market_payload(market) for market in (profiles or MARKETS)]
    return {
        "markets": [{**market, "metrics": metrics[market["country_code"]]} for market in markets],
        "score_weights": SCORE_WEIGHTS,
        "quality_gate": QUALITY_GATE,
        "search_policy": SEARCH_POLICY,
        "validation_goals": VALIDATION_GOALS,
    }
