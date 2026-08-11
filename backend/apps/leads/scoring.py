import re
import unicodedata
from dataclasses import asdict, dataclass


WEIGHTS = {
    "intent": 30,
    "company_fit": 25,
    "specificity": 20,
    "capability_fit": 15,
    "recency": 10,
}


@dataclass(frozen=True, slots=True)
class ScoreDimensions:
    intent: int
    company_fit: int
    specificity: int
    capability_fit: int
    recency: int


@dataclass(frozen=True, slots=True)
class EvidenceGates:
    traceable_source: bool
    explicit_need_or_company_match: bool
    capability_evidence: bool
    audited_run: bool
    ontology_snapshot: bool


@dataclass(frozen=True, slots=True)
class ScoreResult:
    total: int
    band: str
    high_value_eligible: bool


@dataclass(frozen=True, slots=True)
class PublicSignalEvaluation:
    normalized_text: str
    is_explicit_need: bool
    company_match_confidence_class: str
    company_match_confidence: float
    intent_confidence: float
    capability_confidence: float
    dimensions: ScoreDimensions
    gates: EvidenceGates
    score: ScoreResult
    evidence_spans: tuple[str, ...]


_INDUSTRIAL_TERMS = (
    "gear",
    "gearbox",
    "sprocket",
    "shaft",
    "rack and pinion",
    "coupling",
    "machining",
    "heat treatment",
    "齿轮",
    "齿条",
    "链轮",
    "轴",
    "减速箱",
    "齿轮箱",
    "蜗轮",
    "蜗杆",
    "联轴器",
    "机械加工",
    "热处理",
    "磨齿",
)
_EXPLICIT_NEED_TERMS = (
    "rfq",
    "need",
    "needs",
    "seeking",
    "require",
    "requires",
    "wanted",
    "please quote",
    "looking for",
    "seeks",
    "需要采购",
    "急需",
    "正在寻找",
    "询价",
    "要求定制",
    "求购",
    "需要",
    "请报价",
    "寻找",
    "急需加工",
)
_VAGUE_NEED_TERMS = (
    "may upgrade",
    "exploring options",
    "future",
    "considering whether",
    "could be",
    "after the next budget",
    "researching possible",
    "no approved project",
    "可能升级",
    "只是了解",
    "也许",
    "还在研究",
    "正在考虑",
    "没有立项",
    "可能会有",
    "预算评审后",
    "先了解",
    "没有明确",
)
_ENGAGEMENT_TERMS = (
    "excellent video",
    "congratulations",
    "thanks for sharing",
    "looks impressive",
    "enjoyed",
    "拍得很好",
    "祝贺",
    "感谢分享",
    "很棒",
    "很有收获",
)
_ADVERTISEMENT_TERMS = (
    "buy our",
    "now offers",
    "limited promotion",
    "discover our",
    "invite buyers",
    "购买我们的",
    "全球发货",
    "限时促销",
    "欢迎查看我们",
    "诚邀买家",
)
_RECRUITMENT_TERMS = (
    "senior gear design engineer",
    "hiring",
    "vacancy",
    "recruiting apprentices",
    "join our gearbox sales team",
    "招聘",
    "职位空缺",
    "招收",
    "加入我们的",
)
_JOB_SEEKER_TERMS = (
    "position as",
    "available for work",
    "internship",
    "my background",
    "recent graduate",
    "岗位",
    "本人",
    "实习",
    "就业机会",
    "毕业生求职",
)
_SUPPLIER_PITCH_TERMS = (
    "we supply",
    "approved vendor",
    "distribution partners",
    "contact us",
    "as a heat-treatment supplier",
    "overseas agents",
    "供应商",
    "经销伙伴",
    "联系我们",
    "服务贵司",
    "代理商",
)
_ACADEMIC_TERMS = (
    "student project",
    "laboratory paper",
    "thesis",
    "university team",
    "researchers measured",
    "学生项目",
    "实验室论文",
    "毕业论文",
    "大学团队",
    "研究人员",
)
_COMPANY_PAGE_TERMS = (
    " manufactures ",
    "company profile",
    "plant operates",
    "serves packaging",
    "corporate page",
    "制造齿轮",
    "公司简介",
    "工厂拥有",
    "服务于",
    "企业页面",
)
_HIGH_COMPANY_TERMS = (
    "factory",
    "company",
    "plant",
    "oem",
    "gmbh",
    "corporate",
    "our company",
    "our factory",
    "工厂",
    "本厂",
    "我司",
    "公司",
    "企业",
    "制造商",
    "生产线",
)
_MEDIUM_COMPANY_TERMS = ("we ", "our team", "team ", "我们", "团队")


_PROCUREMENT_PATTERNS = (
    re.compile(
        r"\b(?:can anyone|who can)\s+(?:manufacture|make|supply)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:procurement|purchasing)\b[^.?!]{0,40}"
        r"\b(?:requests?|invites?|seeks?)\s+(?:bids?|quotes?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?:采购|采购团队)[^。！？]{0,16}(?:征集|寻求|请求)(?:报价|投标)"),
)
_PERSONNEL_REQUEST_PATTERN = re.compile(
    r"\b(?:need|seeking|require)\s+(?:an?\s+)?[^.?!]{0,32}"
    r"\b(?:engineer|consultant|operator|manager|technician)\b",
    re.IGNORECASE,
)


def _contains_term(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _normalized_signal_text(text: str) -> str:
    if not isinstance(text, str):
        raise ValueError("public signal text must be a string")
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()
    if not normalized:
        raise ValueError("public signal text must not be blank")
    return normalized


def _evidence_windows(text: str, *, language: str) -> tuple[str, ...]:
    """Return bounded, overlapping excerpts copied exactly from the public text."""
    source = text.strip()
    spans = []
    if language == "en":
        tokens = list(re.finditer(r"[\w]+(?:[-'][\w]+)*", source, re.UNICODE))
        window_size = 6 if len(tokens) > 6 else max(1, len(tokens) - 1)
        stride = max(1, window_size - 3)
        for start in range(0, len(tokens), stride):
            end = min(len(tokens), start + window_size)
            if start >= end:
                continue
            span = source[tokens[start].start() : tokens[end - 1].end()]
            if span != source:
                spans.append(span)
            if end == len(tokens):
                break
    else:
        content_end = len(source.rstrip("。！？.!?"))
        window_size = min(10, max(1, content_end - 1))
        stride = max(1, window_size - 5)
        for start in range(0, content_end, stride):
            end = min(content_end, start + window_size)
            span = source[start:end]
            if span and span != source:
                spans.append(span)
            if end == content_end:
                break
    if not spans:
        spans.append(source[: max(1, len(source) // 2)])
    return tuple(dict.fromkeys(spans))


def evaluate_public_signal(text: str, *, language: str) -> PublicSignalEvaluation:
    """Return an offline, conservative baseline for public industrial signals.

    This deliberately recognizes explicit buying language and rejects common
    recruitment, advertising, supplier-pitch, academic, and social-engagement
    contexts. It is a deterministic quality baseline, not a replacement for the
    audited lead-analysis orchestration.
    """
    if language not in {"en", "zh"}:
        raise ValueError("language must be 'en' or 'zh'")
    normalized = _normalized_signal_text(text)
    folded = normalized.casefold()
    industrial = _contains_term(folded, _INDUSTRIAL_TERMS)
    organization_context = any(
        _contains_term(folded, terms)
        for terms in (
            _ADVERTISEMENT_TERMS,
            _RECRUITMENT_TERMS,
            _SUPPLIER_PITCH_TERMS,
            _COMPANY_PAGE_TERMS,
        )
    )
    excluded = bool(
        organization_context or _PERSONNEL_REQUEST_PATTERN.search(folded)
    ) or any(
        _contains_term(folded, terms)
        for terms in (_ENGAGEMENT_TERMS, _JOB_SEEKER_TERMS, _ACADEMIC_TERMS)
    )
    procurement_request = any(
        pattern.search(normalized) for pattern in _PROCUREMENT_PATTERNS
    )
    explicit = (
        industrial
        and not excluded
        and (_contains_term(folded, _EXPLICIT_NEED_TERMS) or procurement_request)
    )
    vague = (
        industrial
        and not excluded
        and not explicit
        and _contains_term(folded, _VAGUE_NEED_TERMS)
    )

    if organization_context or (
        explicit and _contains_term(folded, _HIGH_COMPANY_TERMS)
    ):
        company_class, company_confidence = "HIGH", 0.9
    elif explicit or (vague and _contains_term(folded, _MEDIUM_COMPANY_TERMS)):
        company_class, company_confidence = "MEDIUM", 0.6
    else:
        company_class, company_confidence = "LOW", 0.25

    if explicit:
        dimensions = ScoreDimensions(28, 20, 18, 14, 9)
        intent_confidence, capability_confidence = 0.95, 0.9
    elif vague:
        dimensions = ScoreDimensions(18, 15, 10, 10, 7)
        intent_confidence, capability_confidence = 0.55, 0.6
    else:
        dimensions = ScoreDimensions(
            2, {"HIGH": 8, "MEDIUM": 5, "LOW": 2}[company_class], 3, 5, 2
        )
        intent_confidence, capability_confidence = 0.1, 0.3
    gates = EvidenceGates(
        traceable_source=True,
        explicit_need_or_company_match=explicit,
        capability_evidence=explicit,
        audited_run=False,
        ontology_snapshot=False,
    )
    return PublicSignalEvaluation(
        normalized_text=normalized,
        is_explicit_need=explicit,
        company_match_confidence_class=company_class,
        company_match_confidence=company_confidence,
        intent_confidence=intent_confidence,
        capability_confidence=capability_confidence,
        dimensions=dimensions,
        gates=gates,
        score=score_lead(dimensions, gates),
        evidence_spans=_evidence_windows(text, language=language),
    )


def score_lead(dimensions: ScoreDimensions, gates: EvidenceGates) -> ScoreResult:
    values = asdict(dimensions)
    for name, value in values.items():
        maximum = WEIGHTS[name]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= maximum
        ):
            raise ValueError(f"{name} must be between 0 and {maximum}")

    gate_values = asdict(gates)
    for name, value in gate_values.items():
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a boolean")

    total = sum(values.values())
    band = (
        "HIGH"
        if total >= 80
        else "WATCH"
        if total >= 60
        else "OBSERVE"
        if total >= 40
        else "LOW"
    )
    return ScoreResult(
        total=total,
        band=band,
        high_value_eligible=band == "HIGH" and all(gate_values.values()),
    )
