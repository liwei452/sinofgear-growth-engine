# SINOF Source / Tool Adapter 接口规范（草案）

Date: 2026-08-19
Status: 草案（供评审，基于 KeeLead / Gosom / Bricks / OpenOutreach 拆解）

## 1. 目标

把“发现客户、研究企业、补全联系人、验证邮箱”统一成一套可注册、可编排、可审计的
Source Adapter 接口，让 Agent 通过白名单工具调用，而不是逐个写死数据源逻辑。

硬约束：**真实性是强字段，不是提示词约定。** 任何合成/演示数据不得进入业务对象。

## 2. 真实性分级（核心）

```python
class SourceAuthenticity(StrEnum):
    REAL = "REAL"            # 真实外部调用，返回可追溯数据
    DERIVED = "DERIVED"      # 由真实源推导（如邮箱猜测），必须低置信度并标注
    SYNTHETIC = "SYNTHETIC"  # 合成/假数据，仅限演示，禁止进入业务链
```

规则：

- 只有 `REAL` 和 `DERIVED` 能写入 `DiscoveryCandidate` / `TargetAccount` / `Contact` /
  `IntentSignal` / `ProductEvidenceFact`。
- `SYNTHETIC` 只能产出预览，不能落库为正式对象；写入入口必须拒绝。
- 每个结果必须携带 `source`、`evidence`（原始出处/URL/摘录）、`confidence`、
  `authenticity`、`observed_at`、`license/usage_rights`。

## 3. 能力分类

```python
class SourceCapability(StrEnum):
    DISCOVER = "DISCOVER"   # 发现企业/联系人
    RESEARCH = "RESEARCH"   # 企业/网站研究
    ENRICH = "ENRICH"       # 补全（邮箱/联系人/事实）
    VERIFY = "VERIFY"       # 验证（邮箱/域名/企业）
```

## 4. 统一接口

```python
@dataclass(frozen=True)
class SourceRecord:
    id: str
    source: str
    capability: SourceCapability
    authenticity: SourceAuthenticity
    confidence: float
    evidence: dict          # source_url / excerpt / observed_at
    payload: dict           # 结构化字段（公司/联系人/邮箱/事实）
    usage_rights: str = ""


class SourceAdapter(Protocol):
    id: str
    category: str
    capability: SourceCapability
    authenticity: SourceAuthenticity
    requires_api_key: bool
    rate_limit: int
    enabled: bool

    def search(self, query: str, options: dict) -> Iterator[SourceRecord]: ...
    def research(self, target: dict) -> Iterator[SourceRecord]: ...
    def enrich(self, target: dict) -> Iterator[SourceRecord]: ...
    def verify(self, target: dict) -> Iterator[SourceRecord]: ...
```

每个 adapter 只实现它支持的方法，其余抛 `NotImplementedError`；编排层按 `capability`
选择调用，而不是假设所有源都有 `search`。

## 5. 注册表

```python
class SourceRegistry:
    def register(self, adapter: SourceAdapter) -> None: ...
    def for_capability(self, capability) -> list[SourceAdapter]: ...
    def real_only(self) -> list[SourceAdapter]: ...
```

Agent 的工具白名单只从 `real_only()`（`REAL` + `DERIVED`）生成；`SYNTHETIC` 只出现在
管理员诊断视图，不进入 Agent 工具。

## 6. 与 SINOF 现有模型的映射

| SourceRecord 能力 | 落库目标 |
|-------------------|----------|
| DISCOVER（企业） | `DiscoveryCandidate` → 审核后 `TargetAccount` |
| RESEARCH | `TargetAccount` / `ProductEvidenceFact` / `FieldProvenance` |
| ENRICH（联系人） | `Contact` / `IntentSignal` |
| ENRICH（邮箱） | `Contact`（verification_status） |
| VERIFY | 更新 `Contact.verification_status` |

所有落库通过 `GrowthMission` / `MissionEntityLink` 关联来源，保证可回答“这个客户从哪里来”。

## 7. 开源项目映射

| 能力 | 采用 | 说明 |
|------|------|------|
| DISCOVER / SEARCH_MAPS | **Gosom**（MIT） | 直接作为底层，包装成 `SourceAdapter` |
| DISCOVER（真实免费源） | KeeLead 真实子集（OpenStreetMap、SEC EDGAR、Companies House、OpenCorporates） | 逐个验证“真实 HTTP”，不搬假数据源 |
| RESEARCH | 现有 website enrichment + ProductEvidenceFact | 沿用 SINOF 现有证据链 |
| ENRICH_EMAIL | 参考 Bricks 思路，自写 | Bricks 无 License，不能 copy |
| VERIFY_EMAIL | KeeLead 真实子集（DNS/MX/SMTP/whois/ssl-cert） | 逐个验证真实实现 |
| OUTREACH | 参考 OpenOutreach email-first 状态机 | GPL-3.0，只参考不 copy |

## 8. 落地步骤（第一期）

1. 在 `backend/apps/growth/` 或新 `apps/sources/` 定义 `SourceAuthenticity` /
   `SourceCapability` / `SourceRecord` / `SourceAdapter` / `SourceRegistry`。
2. 接入 Gosom 作为第一个 `REAL` `DISCOVER` adapter（验证输出字段与去重）。
3. 逐源接入 KeeLead 的真实免费源，每个源补一个“真实 vs 假数据”单测。
4. 在 Agent 工具白名单处强制 `real_only()`，阻断 `SYNTHETIC`。
