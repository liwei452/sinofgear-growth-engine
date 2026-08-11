# SinofGear AI Native UI Redesign

**Date:** 2026-08-11  
**Status:** Approved design baseline  
**Audience:** industrial manufacturing owners, foreign-trade beginners, operators, reviewers, and administrators

## 1. Decision

The ordinary experience will use the approved **AI Workbench** visual direction: a calm white and light-gray workspace, SinofGear blue as the only dominant brand color, five plain-language navigation entries, decision cards at the top, live AI activity below, and a compact outcome summary.

The approved screenshot is a visual reference, not a data contract. Its hierarchy, spacing, card composition, navigation structure, and restrained industrial tone should be reproduced. Example statistics, notifications, avatars, CRM success states, and platform results must never be hard-coded as if they were real.

The product remains one system. This redesign changes presentation and navigation; it does not fork the backend, duplicate domain models, or create a second application.

## 2. Product principle

The default interaction is:

> AI proposes an action → the system explains why and shows evidence → the user approves, adjusts, or rejects → the system executes.

If an ordinary foreign-trade beginner must understand an internal data model before completing a task, the UX has failed.

## 3. Goals and non-goals

### Goals

- Make the first useful action obvious within ten seconds.
- Remove English status codes, permission codes, raw UUIDs, and internal object names from ordinary mode.
- Use natural Chinese to explain what happened, why it matters, and what the user can do next.
- Preserve fast operation for experienced users without forcing a wizard on every visit.
- Keep every metric, badge, count, and progress indicator backed by a real API response.
- Preserve all advanced records and administrative capabilities behind an explicit advanced-mode entry.
- Keep the CRM handoff interface without turning this product into a CRM.

### Non-goals

- No CRM pipeline, contact management, sales stages, follow-up calendar, or deal management.
- No fake conversational AI. Until a real model is configured, promotion guidance uses deterministic cards and bounded choices.
- No autonomous third-party login, scraping, outreach, or publishing beyond configured connectors and user-approved actions.
- No decorative “AI universe,” neon glow, excessive gradients, or dashboard clutter.
- No invented analytics or optimistic placeholder percentages in the normal application.

## 4. Information architecture

Ordinary mode exposes exactly five primary entries:

1. **今天** — decisions, active work, and recent outcomes.
2. **推广** — guided promotion planning, content preparation, and approval.
3. **客户机会** — public-signal opportunities, AI explanation, evidence, and human review.
4. **效果** — concise channel/product outcomes and recommended next action.
5. **我的公司** — what AI knows, what evidence is missing, and how to improve company understanding.

The bottom of the navigation contains **高级设置**. Advanced mode may expose products, assets, promotion records, platform accounts, monitoring, AI runs, prompts, jobs, ontology, and audit records. Entering advanced mode is deliberate and its preference persists only after validation.

## 5. Visual system

### Layout

- Desktop navigation width: approximately 220–244 px.
- Main content uses a readable maximum width rather than stretching text edge to edge.
- At wide desktop widths, the three highest-priority decision cards may form a three-column row.
- Below the decision row, AI activity and recent outcomes use a one-third/two-thirds split.
- Between 760 px and 1200 px, cards reflow to two columns or a single priority column.
- Below 760 px, navigation becomes an accessible drawer and all content becomes one column.

### Color and surfaces

- Canvas: white or very light neutral gray.
- Primary ink: dark navy, never pure decorative black.
- Brand action: one SinofGear blue derived from the approved logo color.
- Borders: light cool gray; shadows remain subtle and functional.
- Success, attention, and risk colors are used only to communicate state.
- Gradients are optional only as a faint surface tint, never as the visual identity.

### Shape and density

- Moderate 10–14 px card radii; avoid oversized pill-shaped containers.
- One clear primary action per card.
- Secondary actions use outline or text treatment.
- Tables are reserved for advanced mode or genuinely dense comparisons.
- Ordinary mode favors cards, summaries, evidence blocks, and list-detail layouts.

### Typography

- Chinese-first interface with a system sans-serif stack optimized for Windows and modern browsers.
- Page headings are strong but not oversized.
- Supporting copy is concise, scannable, and written in sentence form.
- Platform names, customer names, product standards, and public source text may remain in their original language.

## 6. Language policy

Ordinary mode is Chinese-first. English is permitted only for:

- brand and platform names such as LinkedIn and YouTube;
- customer/company names;
- standards and product terms where translation would reduce accuracy;
- original public evidence, always paired with a Chinese explanation when available.

Internal terms must be translated before rendering:

| Internal concept | Ordinary-language label |
| --- | --- |
| Campaign | 推广计划 |
| ContentBrief | 推广要求 |
| MasterContent | 内容母稿 |
| PlatformContent | 平台内容 |
| LeadCandidate | 潜在客户 |
| LeadInsight | AI客户判断 |
| SourceSignal | 公开线索 |
| AIRun | AI处理记录 |
| PromptVersion | AI规则版本 |
| Ontology | AI对公司的了解 |
| Job | 后台任务 |
| AIEO | AI搜索曝光 |

Common states must use one shared presentation map. Examples:

| Raw state | Ordinary label |
| --- | --- |
| DRAFT | 草稿 |
| GENERATING / RUNNING | 正在处理 |
| QUEUED / RETRY_QUEUED | 等待处理 |
| IN_REVIEW | 等待确认 |
| APPROVED | 已批准 |
| REJECTED | 已退回 |
| PUBLISHED | 已发布 |
| ARCHIVED | 已归档 |
| DISCOVERED | 新发现 |
| ANALYZING | 正在判断 |
| ANALYZED | 判断完成 |
| REVIEWED | 已人工确认 |
| HIGH | 高意向 |
| WATCH | 值得关注 |
| LOW | 信息不足 |
| FAILED | 处理失败 |
| SUCCEEDED | 已完成 |

Permission identifiers such as `tracking.read` are never shown in ordinary copy. The user sees an actionable explanation such as “你目前没有查看效果数据的权限，请联系管理员。”

## 7. Page designs

### 7.1 Today

The header contains a time-appropriate greeting, one sentence explaining the assistant’s role, organization switcher, optional real notification state, and the current user.

The first section answers: **What needs my decision today?** It contains at most three primary cards before “view all.” Priority is determined from real unresolved actions, not a fixed display order.

Each decision card contains:

- a sequence or priority marker;
- a natural-language title;
- a short explanation of the evidence or reason;
- a truthful category badge;
- one primary action and no more than two secondary actions.

The next section shows **AI正在帮你工作** using real jobs. Determinate progress is shown only when the backend provides meaningful progress; otherwise use a short state description without a fake percentage.

The outcome section shows only available real metrics. Empty analytics produce an explanatory empty state and a next action, not zero-filled success cards.

### 7.2 Promotion

Promotion remains a guided experience. It asks one decision at a time using conversational copy and choice cards:

1. What do you want to promote?
2. Where do you want to sell it?
3. Which customer type matters?
4. What does the system recommend and why?
5. Approve, adjust, or save as a draft.

Until a real model is configured, the interface must not claim to be free-form AI chat. It uses the existing deterministic workflow and real product, asset, ontology, campaign, and historical inputs. Advanced records remain recoverable.

### 7.3 Customer opportunities

Use a responsive list-detail layout:

- left: opportunity cards with company, country/industry, need summary, source, and a human label;
- right: why it may be valuable, what information is missing, original public evidence, Chinese explanation, and available actions.

The page never displays LeadCandidate, LeadInsight, SourceSignal, raw confidence JSON, or internal IDs in ordinary mode.

The main review actions are **确认值得跟进**, **暂不处理**, and **查看原始来源**. Analysis and review remain permission-controlled and evidence-bound.

### 7.4 Results

Lead with conclusions:

- which platform is working;
- which product or market is working;
- what changed compared with the prior period;
- what the user should do next.

Raw UTM fields, publishing IDs, and detailed tables are advanced information. Charts appear only when the underlying data is sufficient and should not compete with the recommendation.

### 7.5 My company

Translate the knowledge layer into:

- **AI已经了解**;
- **AI还不清楚**;
- **需要补充的证明**;
- **建议下一步**.

Do not use “Ontology” in ordinary mode. Every claim about a capability must remain linked to company evidence.

## 8. CRM handoff boundary

The **交给CRM** interface remains visible where the user has confirmed a valuable opportunity.

- When a connector is configured, the action creates a handoff request and reports real success, failure, and retry state.
- When no connector is configured, the action opens a guided choice: configure a CRM connector or export a structured JSON/CSV handoff package.
- The handoff package includes candidate identity, AI judgment, human review, need summary, and public source evidence.
- A CRM failure does not remove or mutate the reviewed opportunity.
- The system does not add CRM sales-management features.

Until the Phase B CRM connector endpoint exists, the UI must not simulate successful delivery. It may expose the stable affordance with an honest “尚未配置CRM” state and a real export path.

## 9. Data truth and error handling

- No decision, count, score, comparison, trend, notification badge, or progress value may be invented by the frontend.
- A unavailable subsystem fails locally; one failed panel does not blank the whole page.
- Each failure message states what failed and offers one safe recovery action.
- Stale asynchronous results remain invalid after organization, membership, or permission continuity changes.
- Organization isolation and permission checks remain enforced by the backend; hiding a control is never the security boundary.
- Empty states explain why there is no data and what the user can do next.

## 10. Accessibility and responsive behavior

- Navigation, drawers, dialogs, disclosures, and list-detail selection are fully keyboard accessible.
- Focus moves into opened dialogs/details and returns to the invoking control on close.
- Color is never the only indicator of status.
- Touch targets are at least 40 px in ordinary mode.
- The mobile drawer supports focus containment and Escape close.
- Original-language evidence and its Chinese explanation have clear labels.
- Reduced-motion preferences disable decorative transitions.

## 11. Implementation boundaries

The redesign should introduce shared presentation components rather than page-local mappings:

- ordinary status/term presentation map;
- decision card;
- AI activity row;
- metric result card;
- evidence summary;
- localized empty/error state;
- ordinary/advanced disclosure;
- responsive application shell.

Existing domain API types remain unchanged. Presentation maps are exhaustive and tested so new raw enum values cannot silently leak into ordinary mode.

## 12. Acceptance criteria

- Ordinary navigation contains exactly five primary Chinese entries plus advanced settings.
- No known raw status, permission code, or internal model name appears in ordinary-mode browser acceptance.
- Today, Promotion, Customer Opportunities, Results, and My Company each render useful empty, loading, success, and local-error states.
- All displayed counts and metrics are traceable to API data.
- CRM handoff is visible but never claims success without a real connector or export result.
- Desktop, tablet, and 390×844 mobile acceptance passes.
- Advanced routes and validated preference persistence remain intact.
- Existing backend, OpenAPI, unit, type, lint, build, and browser suites remain green.

## 13. Deliberate follow-on work

- Real free-form assistant behavior follows real model-provider integration and separate prompt/safety design.
- Live CRM delivery follows a dedicated LeadHandoff connector plan; this redesign preserves the interface and export fallback.
- AI search exposure remains a later AIEO phase, but its ordinary-language entry and visual pattern are reserved here.
