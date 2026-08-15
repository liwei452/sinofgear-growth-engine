INDUSTRIAL_BUYING_SIGNALS = (
    ("MINE_EXPANSION", "矿山扩产", ("mine expansion", "mining expansion", "new mine", "矿山扩产")),
    ("NEW_PRODUCTION_LINE", "新生产线", ("new production line", "new assembly line", "新生产线")),
    ("NEW_PLANT", "新工厂", ("new plant", "new factory", "new cement plant", "新工厂", "新水泥厂")),
    ("EQUIPMENT_OVERHAUL", "设备大修", ("equipment overhaul", "设备大修")),
    ("CRUSHER_OVERHAUL", "破碎机大修", ("crusher overhaul", "crusher rebuild", "破碎机大修")),
    ("GEARBOX_REBUILD", "减速机大修", ("gearbox rebuild", "gearbox overhaul", "gearbox repair", "减速机大修", "齿轮箱维修")),
    ("PLANT_SHUTDOWN_MAINTENANCE", "停机检修", ("plant shutdown", "shutdown maintenance", "停机检修")),
    ("SPARE_PARTS_TENDER", "备件招标", ("spare parts tender", "备件招标")),
    ("EQUIPMENT_TENDER", "设备招标", ("equipment tender", "设备招标")),
    ("MRO_CONTRACT", "MRO 合同", ("mro contract", "maintenance contract", "mro 合同", "维护合同")),
    ("FACTORY_UPGRADE", "工厂升级", ("factory upgrade", "plant upgrade", "工厂升级")),
    ("HIRING_MAINTENANCE_ENGINEER", "招聘维修工程师", ("maintenance engineer", "维修工程师")),
)


def detect_buying_signals(text: str) -> list[dict]:
    lowered = text.casefold()
    results = []
    for signal_type, label, keywords in INDUSTRIAL_BUYING_SIGNALS:
        matched = [keyword for keyword in keywords if keyword.casefold() in lowered]
        if matched:
            results.append({
                "signal_type": signal_type,
                "label": label,
                "matched_keywords": matched,
                "evidence_excerpt": _excerpt(text, matched[0]),
            })
    return results


def _excerpt(text: str, keyword: str, *, radius: int = 90) -> str:
    index = text.casefold().find(keyword.casefold())
    if index < 0:
        return text[:180]
    start = max(0, index - radius)
    end = min(len(text), index + len(keyword) + radius)
    return text[start:end].strip()
