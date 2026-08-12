# Growth Director 驾驶舱与编排骨架 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不复制现有业务数据的前提下，建立 Growth Director 提案、合并审批、首页聚合接口和新手前台五入口，让普通用户只处理少量关键决定。

**Architecture:** 新增独立 `director` 领域保存提案与人工决策，它只引用现有产品、内容、潜客和任务，不接管这些领域的状态机。后端提供组织隔离的驾驶舱聚合接口；前端首页只消费这一份面向用户的合同，复杂记录继续留在高级模式。

**Tech Stack:** Django 5.2、Django REST Framework、PostgreSQL、Celery Job 基础设施、Vue 3、TypeScript、TanStack Vue Query、Vitest、Pytest、Playwright。

## Global Constraints

- 普通前台固定为：今天、产品资料、推广、客户机会、效果。
- 管理员后台保留现有高级功能；本批次不删除任何高级路由或业务数据。
- 不保存平台密码，不新增自动抓取、自动发布或陌生人自动私信。
- Growth Director 只生成和管理提案；它不绕过 Content、Lead、Publishing 等现有领域服务。
- 对外发布、CRM 交接、事实冲突和成本超限必须由人批准；本批次不执行尚未实现的后续动作。
- 所有数量、状态、进度和结果来自数据库；禁止前端伪造演示指标。
- 所有查询和变更必须按当前活动组织隔离，权限由后端强制执行。
- 后端变更必须同步 OpenAPI；前端类型必须从已提交的合同或生成类型中获得。
- 不修改与任务无关的 `backend/config/test_settings.py` 本地改动。

---

## File Structure

- `backend/apps/director/`：Growth Director 提案、决策、聚合读取和 API。
- `backend/apps/identity/permissions.py`：新增提案读取与决策权限。
- `backend/apps/identity/migrations/0012_refresh_director_permissions.py`：为内置角色分配权限。
- `backend/config/settings.py`、`backend/config/urls.py`：注册新领域和路由。
- `frontend/src/modules/director/api.ts`：驾驶舱合同与请求。
- `frontend/src/modules/dashboard/DashboardPage.vue`：只呈现面向用户的决定、任务和真实结果。
- `frontend/src/app/AppShell.vue`、`frontend/src/app/router.ts`：固定五入口与管理员入口。
- `frontend/src/modules/director/AgentCenterPage.vue`：管理员查看五个 Agent 的准备状态和边界。
- `frontend/e2e/`：普通模式和管理员模式的浏览器验收。

### Task 1: Growth Director 提案模型与权限

**Files:**
- Create: `backend/apps/director/__init__.py`
- Create: `backend/apps/director/apps.py`
- Create: `backend/apps/director/models.py`
- Create: `backend/apps/director/migrations/__init__.py`
- Create: `backend/apps/director/migrations/0001_initial.py`
- Create: `backend/apps/director/tests/__init__.py`
- Create: `backend/apps/director/tests/test_models.py`
- Modify: `backend/apps/identity/permissions.py`
- Create: `backend/apps/identity/migrations/0012_refresh_director_permissions.py`
- Modify: `backend/config/settings.py`

**Interfaces:**
- Produces: `DirectorProposal`, `DirectorDecision`, `CanReadDirector`, `CanDecideDirector`。
- `DirectorProposal` fields: `id`, `organization`, `proposal_type`, `status`, `priority`, `title_zh`, `summary_zh`, `reason_snapshot`, `action_reference`, `expires_at`, `version`, `created_at`, `updated_at`。
- `DirectorDecision` fields: `id`, `proposal`, `organization`, `action`, `proposal_version`, `actor`, `comment`, `created_at`。
- Proposal types: `PROMOTION_PLAN`, `CONTENT_APPROVAL`, `LEAD_HANDOFF`, `FACT_CONFLICT`, `COST_APPROVAL`。
- Proposal states: `PENDING`, `APPROVED`, `ADJUSTMENT_REQUESTED`, `REJECTED`, `SUPERSEDED`, `EXPIRED`。

- [ ] **Step 1: Write failing model and permission tests**

```python
def test_proposal_is_organization_scoped_and_versioned(organization):
    proposal = DirectorProposal.objects.create(
        organization=organization,
        proposal_type="PROMOTION_PLAN",
        title_zh="建议推广德国包装机械市场",
        summary_zh="依据已确认产品能力生成",
        reason_snapshot={"evidence_count": 3},
        action_reference={"kind": "campaign_draft", "id": "draft-1"},
    )
    assert proposal.status == "PENDING"
    assert proposal.version == 1


def test_one_human_decision_per_proposal_version(proposal, user):
    DirectorDecision.objects.create(
        proposal=proposal, organization=proposal.organization,
        action="APPROVE", proposal_version=1, actor=user,
    )
    with pytest.raises(IntegrityError):
        DirectorDecision.objects.create(
            proposal=proposal, organization=proposal.organization,
            action="REJECT", proposal_version=1, actor=user,
        )
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `python -m pytest apps/director/tests/test_models.py -q` from `backend`.

Expected: FAIL because `apps.director` and its models do not exist.

- [ ] **Step 3: Implement protected proposal and append-only decision models**

```python
class DirectorProposal(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        ADJUSTMENT_REQUESTED = "ADJUSTMENT_REQUESTED", "Adjustment requested"
        REJECTED = "REJECTED", "Rejected"
        SUPERSEDED = "SUPERSEDED", "Superseded"
        EXPIRED = "EXPIRED", "Expired"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey("identity.Organization", on_delete=models.PROTECT)
    proposal_type = models.CharField(max_length=32, choices=ProposalType.choices)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    priority = models.PositiveSmallIntegerField(default=50)
    title_zh = models.CharField(max_length=160)
    summary_zh = models.TextField()
    reason_snapshot = models.JSONField(default=dict)
    action_reference = models.JSONField(default=dict)
    expires_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
```

Add database constraints for priority `1..100`, non-empty titles, decision organization matching through service validation, and unique `(proposal, proposal_version)` decisions. Direct proposal state mutations will be routed through the Task 2 service.

- [ ] **Step 4: Add permissions and role migration**

Add `director.read` to all four built-in roles. Add `director.decide` to `ADMINISTRATOR`, `OPERATOR`, and `REVIEWER`. Define permission classes using the existing `HasOrganizationPermission` pattern.

- [ ] **Step 5: Run tests and migration consistency checks**

Run: `python -m pytest apps/director/tests/test_models.py apps/identity/tests -q`

Run: `python manage.py makemigrations --check --dry-run`

Expected: PASS and “No changes detected”.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/director backend/apps/identity backend/config/settings.py
git commit -m "feat: add Growth Director proposal domain"
```

### Task 2: 提案服务、并发控制与审计

**Files:**
- Create: `backend/apps/director/services.py`
- Create: `backend/apps/director/tests/test_services.py`
- Modify: `backend/apps/audit/models.py`
- Create: `backend/apps/audit/migrations/0004_expand_director_actions.py`

**Interfaces:**
- Consumes: `DirectorProposal`, `DirectorDecision`, existing `record_audit_event` authorization rules。
- Produces:

```python
DirectorService.propose(*, organization, proposal_type, title_zh, summary_zh,
                        reason_snapshot, action_reference, priority=50,
                        expires_at=None, idempotency_key) -> DirectorProposal
DirectorService.decide(*, organization, proposal_id, expected_version,
                       action, actor, comment="") -> DirectorProposal
DirectorService.supersede(*, organization, proposal_id, replacement_id) -> DirectorProposal
```

- [ ] **Step 1: Write failing service tests**

Test exact idempotency, different-payload conflict, cross-organization 404 behavior, stale-version conflict, reject/adjustment comment requirement, expired proposal rejection, one decision per version, and append-only audit creation.

```python
def test_stale_decision_cannot_approve(proposal, reviewer):
    with pytest.raises(DirectorVersionConflict):
        DirectorService.decide(
            organization=proposal.organization,
            proposal_id=proposal.id,
            expected_version=proposal.version + 1,
            action="APPROVE",
            actor=reviewer,
        )
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `python -m pytest apps/director/tests/test_services.py -q`

Expected: FAIL because `DirectorService` does not exist.

- [ ] **Step 3: Implement transactional services**

Use `transaction.atomic()` and `select_for_update()`. Freeze JSON with the existing secret scrubber before persistence. `decide()` must re-check organization, status, expiry, permission and version while locked, append `DirectorDecision`, update the proposal once, and append an audit event in the same transaction.

Approved proposals only record approval in this batch. They do not directly publish, hand off a lead, or call DeepSeek; later batches attach explicit executors to `action_reference.kind`.

- [ ] **Step 4: Expand audit action choices**

Add `REQUEST_ADJUSTMENT` and `SUPERSEDE` to `ReviewAction`; generate and test the migration. Existing audit rows remain valid.

- [ ] **Step 5: Run service and audit tests**

Run: `python -m pytest apps/director/tests/test_services.py apps/audit/tests -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/director backend/apps/audit
git commit -m "feat: add audited Director decisions"
```

### Task 3: 驾驶舱聚合 API

**Files:**
- Create: `backend/apps/director/serializers.py`
- Create: `backend/apps/director/selectors.py`
- Create: `backend/apps/director/views.py`
- Create: `backend/apps/director/urls.py`
- Create: `backend/apps/director/tests/test_api.py`
- Create: `backend/apps/director/tests/test_openapi.py`
- Modify: `backend/config/urls.py`

**Interfaces:**
- Produces `GET /api/v1/director/cockpit`:

```json
{
  "decisions": [{
    "id": "uuid",
    "type": "CONTENT_APPROVAL",
    "title": "5 条内容已准备好",
    "explanation": "内容来自已确认的产品资料",
    "priority": 80,
    "version": 1,
    "actions": ["APPROVE", "REQUEST_ADJUSTMENT", "REJECT"]
  }],
  "active_work": [{
    "job_id": "uuid",
    "label": "正在生成平台内容",
    "status": "RUNNING",
    "progress": 65,
    "progress_is_determinate": true
  }],
  "recent_outcomes": [{
    "kind": "PUBLISHING",
    "label": "内容发布",
    "value": "4",
    "detail": "最近 30 天真实完成记录"
  }],
  "generated_at": "2026-08-12T12:00:00Z"
}
```

- Produces `POST /api/v1/director/proposals/{id}/decisions` with body:

```json
{"action":"APPROVE","expected_version":1,"comment":""}
```

- [ ] **Step 1: Write failing API contract tests**

Cover authentication, `director.read`, `director.decide`, organization isolation, maximum three primary decisions, priority ordering, permission-filtered actions, truthful empty arrays, local absence of analytics permissions, duplicate decision conflict, invalid action, stale version and OpenAPI operations.

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest apps/director/tests/test_api.py apps/director/tests/test_openapi.py -q`

Expected: FAIL because the routes do not exist.

- [ ] **Step 3: Implement read selectors without N+1 queries**

`cockpit_snapshot(organization, permissions, now)` returns no more than three pending proposals, five active jobs, and four outcome summaries. It may aggregate only data the caller can read. Missing permission yields an omitted panel item, not leaked counts or a whole-page 403.

Only return fields needed by ordinary mode. Never expose `reason_snapshot`, raw UUID references, PromptVersion, AIRun input, permission codes, or provider errors.

- [ ] **Step 4: Implement serializers and views**

Use strict serializers that reject unknown fields. Map domain errors to the repository’s recoverable error contract with stable codes: `director_version_conflict`, `director_state_conflict`, `director_expired`, `director_comment_required`.

- [ ] **Step 5: Register routes and regenerate/check OpenAPI**

Run: `python manage.py spectacular --file /tmp/sinofgear-schema.yml --validate` (use a Windows temporary path when executing on Windows).

Run: `pnpm api:generate` from `frontend` and commit the generated schema only if it changed.

- [ ] **Step 6: Run API tests**

Run: `python -m pytest apps/director/tests -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/director backend/config/urls.py frontend/src/api/generated/schema.ts
git commit -m "feat: expose the AI decision cockpit API"
```

### Task 4: 前端驾驶舱 API 与真实决策交互

**Files:**
- Create: `frontend/src/modules/director/api.ts`
- Create: `frontend/src/modules/director/api.test.ts`
- Modify: `frontend/src/modules/dashboard/DashboardPage.vue`
- Modify: `frontend/src/modules/dashboard/DashboardPage.test.ts`
- Modify: `frontend/src/modules/dashboard/components/DecisionCard.vue`
- Modify: `frontend/src/modules/dashboard/components/DecisionCard.test.ts`
- Modify: `frontend/src/shared/presentation/ordinary.ts`
- Modify: `frontend/src/shared/presentation/ordinary.test.ts`

**Interfaces:**
- Consumes: `GET /api/v1/director/cockpit` and `POST /api/v1/director/proposals/{id}/decisions`。
- Produces: `directorKeys.cockpit(organizationId)`, `getCockpit()`, `decideProposal()`。

- [ ] **Step 1: Write failing API adapter tests**

```typescript
it("sends an optimistic version with a Director decision", async () => {
  await decideProposal("proposal-1", { action: "APPROVE", expected_version: 3, comment: "" })
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/director/proposals/proposal-1/decisions",
    expect.objectContaining({ method: "POST" }),
  )
})
```

Test missing/invalid response rejection and AbortSignal forwarding.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `pnpm test --run src/modules/director/api.test.ts`

Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement the typed adapter**

Use generated OpenAPI types where available. Keep domain values in the adapter and expose Chinese presentation labels through `ordinary.ts`; do not copy raw API error details to the page.

- [ ] **Step 4: Replace dashboard fan-out requests with the cockpit query**

Remove direct dashboard calls to jobs, content, leads and analytics. Render:

- a single H1 “今天有 N 件事需要你决定”；
- up to three `DecisionCard` items;
-真实 `active_work` rows, using indeterminate UI when `progress_is_determinate` is false;
- real `recent_outcomes`, or a useful empty state;
- local retry controls so one failed cockpit request does not remove shell navigation.

- [ ] **Step 5: Implement approve, adjust and reject UX**

Approval sends immediately after a confirmation dialog. Adjustment and rejection open a focused modal with a required Chinese reason. During mutation, disable only that proposal. On success invalidate the cockpit query; on `director_version_conflict`, explain that the item changed and refresh it.

- [ ] **Step 6: Run dashboard, accessibility and presentation tests**

Run: `pnpm test --run src/modules/director src/modules/dashboard src/shared/presentation`

Expected: PASS; no raw proposal status, permission code or internal object name appears.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/modules/director frontend/src/modules/dashboard frontend/src/shared/presentation
git commit -m "feat: connect the dashboard to Growth Director"
```

### Task 5: 固定五入口与管理员 Agent 中心

**Files:**
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/app/AppShell.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/main.ts`
- Create: `frontend/src/modules/director/AgentCenterPage.vue`
- Create: `frontend/src/modules/director/AgentCenterPage.test.ts`
- Modify: `frontend/src/app/ordinaryMode.contract.test.ts`

**Interfaces:**
- Ordinary routes: `/`, `/company-profile`, `/promotion`, `/lead-radar`, `/analytics` displayed as 今天、产品资料、推广、客户机会、效果。
- Advanced route: `/agent-center`, permission `director.read`。
- Agent readiness cards: Growth Director, Content Agent, Lead Agent, AIEO Agent, Analytics Agent。

- [ ] **Step 1: Write failing navigation tests**

Assert ordinary mode has exactly five links in the required order, “产品资料” routes to `/company-profile`, no internal page appears in ordinary navigation, and advanced mode includes “AI Agent 中心” only with permission.

- [ ] **Step 2: Write failing Agent Center tests**

The page must show five responsibility cards and honest readiness derived from existing capabilities:

- Growth Director: cockpit endpoint reachable;
- Content Agent: DeepSeek connected plus content permissions;
- Lead Agent: lead/source permissions and AI connection;
- AIEO Agent: labeled “设计已确认，后续批次接入” in this batch;
- Analytics Agent: tracking permission and available records.

No toggle in this batch may imply an unimplemented scheduler is active.

- [ ] **Step 3: Implement shell and route changes**

Keep advanced routes intact. Rename the ordinary company entry to “产品资料”; change its page title without removing the existing company knowledge content. Add lazy-loaded Agent Center route.

- [ ] **Step 4: Implement the Agent Center read-only readiness page**

Use existing provider configuration, current-user permission and cockpit APIs. Each card shows “可用 / 需要配置 / 后续批次接入” and one real next action. Do not show fake running states.

- [ ] **Step 5: Run shell, router and ordinary-mode contract tests**

Run: `pnpm test --run src/app src/modules/director/AgentCenterPage.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/app frontend/src/main.ts frontend/src/modules/director
git commit -m "feat: separate beginner navigation from Agent administration"
```

### Task 6: 全量验证、浏览器验收与文档

**Files:**
- Create: `docs/acceptance/growth-director-cockpit-foundation.md`
- Modify: `README.md`
- Modify: relevant existing `frontend/e2e/*.spec.ts` files discovered during implementation

**Interfaces:**
- Produces a reproducible acceptance record and startup instructions for the implemented batch.

- [ ] **Step 1: Add browser acceptance coverage**

Test desktop and 390×844 mobile:

1. ordinary navigation contains exactly five Chinese entries;
2. homepage shows truthful empty, loading, success and recoverable error states;
3. reviewer can approve one proposal and it disappears after refresh;
4. adjustment/rejection requires a reason;
5. read-only users cannot see decision controls;
6. advanced Agent Center shows five agents without claiming later-batch capabilities are active;
7. keyboard focus enters and exits dialogs correctly.

- [ ] **Step 2: Run backend quality gates**

Run from `backend`:

```powershell
python -m pytest -q
python -m ruff check .
python manage.py makemigrations --check --dry-run
python manage.py spectacular --file "$env:TEMP\sinofgear-openapi.yml" --validate
```

Expected: all PASS.

- [ ] **Step 3: Run frontend quality gates**

Run from `frontend`:

```powershell
pnpm api:check
pnpm lint
pnpm typecheck
pnpm test --run
pnpm build
pnpm test:e2e
```

Expected: all PASS.

- [ ] **Step 4: Perform visual acceptance against the approved reference**

Open the local application and verify desktop plus mobile layout, hierarchy, Chinese copy, card density, focus styles, empty states and absence of fabricated data. Record screenshots only as evidence; do not commit credentials or user data.

- [ ] **Step 5: Document exact delivered and deferred scope**

The acceptance document must state that this batch delivers the cockpit and orchestration skeleton. Product-manual parsing, real five-platform OAuth/publishing, automated interaction monitoring, AIEO execution and complete analytics loop remain the four following approved batches.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/acceptance frontend/e2e
git commit -m "test: verify Growth Director cockpit foundation"
```

- [ ] **Step 7: Push only after clean verification**

Confirm `git status --short` contains no task-owned changes and preserves only the pre-existing `backend/config/test_settings.py` edit. Push the feature branch to the configured GitHub remote; do not merge or shut down the computer without a new explicit completion check.
