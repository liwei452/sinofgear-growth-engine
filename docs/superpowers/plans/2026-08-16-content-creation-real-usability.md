# Content Creation Real Usability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing AI content path produce one target-language master and genuinely adapted, evidence-backed LinkedIn, Facebook, Instagram and TikTok versions before human review.

**Architecture:** Extend the existing frozen brief → job → AI run contract with a backward-compatible version-2 content payload. One audited AI call returns the master and exact selected-platform variants; `PlatformContent` selects its generated variant and channel packages copy only approved variant data. The existing recommendation panel becomes the sole ordinary creation entry while legacy content stays readable.

**Tech Stack:** Django 5.2, Django REST Framework, Celery task boundary, JSON Schema 2020-12, Vue 3, TypeScript, Vitest, Pytest, Playwright.

## Global Constraints

- Only modify `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`.
- Keep real publishing, OAuth, production deployment, the independent website, and AI video out of scope.
- Use one publication language per brief; Chinese is internal reference only unless the publication language is Chinese.
- Use only verified facts and approved knowledge; never invent certification, performance, customer, price, lead time, capacity or intent claims.
- Every generated master, platform variant and channel package remains subject to human approval.
- Existing version-1 content remains readable and immutable.

---

### Task 1: Version-2 generation contract and full prompt input

**Files:**
- Modify: `backend/apps/content/payloads.py`
- Modify: `backend/apps/ai/orchestration.py`
- Modify: `backend/integrations/ai/providers.py`
- Modify: `backend/apps/common/management/commands/seed_phase_a.py`
- Create: `backend/apps/ai/migrations/0003_content_generation_prompt_v2.py`
- Test: `backend/apps/ai/tests/test_ai_orchestration.py`
- Test: `backend/apps/campaigns/tests/test_content_generation_input.py`
- Test: `backend/integrations/ai/tests/test_deepseek_provider.py`

**Interfaces:**
- Consumes: `ContentGenerationInput.to_dict()` and the selected platforms/verified facts already frozen in it.
- Produces: `CONTENT_OUTPUT_SCHEMA_V2`, `validate_generated_content_output(output, snapshot)` and a rendered `||INPUT:` JSON prompt containing the complete scrubbed snapshot.

- [ ] **Step 1: Write failing prompt and output-contract tests**

```python
def test_generation_prompt_includes_language_buyer_goal_url_and_prohibited_claims(...):
    run = execute_generation_job(...)
    assert captured_input["language"] == "id"
    assert captured_input["customer_type"] == "Industrial distributor"
    assert captured_input["content_objective"] == "Qualified inquiries"
    assert captured_input["landing_page_url"] == "https://example.com/id/gears"
    assert captured_input["prohibited_claims"] == ["never wears"]

def test_v2_output_rejects_language_or_platform_mismatch(snapshot):
    output = valid_v2_output(snapshot)
    output["platform_variants"][0]["language"] = "en"
    with pytest.raises(ValueError, match="language"):
        validate_generated_content_output(output, snapshot)
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/ai/tests/test_ai_orchestration.py backend/apps/campaigns/tests/test_content_generation_input.py backend/integrations/ai/tests/test_deepseek_provider.py -q`

Expected: failures show the renderer omits the full input and the version-2 validator/schema do not exist.

- [ ] **Step 3: Implement the versioned exact schemas and semantic allow-list validation**

Keep legacy exact payload validation. Add bounded strings/lists, exact selected platform set, target-language equality, verified fact ID subset, approved concept-code subset, TikTok 15–60 second `9:16` structure and no internal translation in platform payloads.

- [ ] **Step 4: Render the fixed instruction plus complete scrubbed JSON input**

The provider-facing string is `template.strip() + "||INPUT:" + compact_json(snapshot)`. Reject over-limit prompts before provider invocation. Update Fake generation to parse this input and deterministically emit distinct channel variants in the target language label without claiming real model work.

- [ ] **Step 5: Add immutable prompt version 2**

Create a data migration with purpose `CONTENT_GENERATE`, version `2`, code `evidence-multichannel-v2`, the fixed behavioral template and version-2 output schema. Update the E2E seed command to use the same contract without mutating version 1.

- [ ] **Step 6: Run focused tests and commit**

Run the command from Step 2 plus `backend\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings`.

Commit: `feat: generate structured target-language content`

---

### Task 2: Generated platform variants and honest TikTok package

**Files:**
- Modify: `backend/apps/content/services.py`
- Modify: `backend/apps/content/serializers.py`
- Modify: `backend/apps/growth/services.py`
- Modify: `backend/apps/growth/manual_export.py`
- Test: `backend/apps/content/tests/test_content_api.py`
- Test: `backend/apps/content/tests/test_content_domain.py`
- Test: `backend/tests/test_growth_workspace_api.py`

**Interfaces:**
- Consumes: approved version-2 `MasterContent.payload["platform_variants"]`.
- Produces: exact version-2 `PlatformContent.payload` and a review-only channel package containing the same approved language, hashtags, evidence references and TikTok structure.

- [ ] **Step 1: Write failing platform adaptation tests**

```python
def test_four_platform_contents_use_their_generated_variants(v2_master, platforms):
    rows = [create_platform_content(v2_master, platform=p) for p in platforms]
    assert [row.payload["body"] for row in rows] == [
        "LinkedIn body", "Facebook body", "Instagram body", "TikTok body",
    ]
    assert all(row.payload["language"] == "id" for row in rows)

def test_tiktok_package_copies_reviewed_script_and_subtitles(approved_tiktok):
    package = prepare_channel_package(approved_tiktok)
    assert package.payload["duration_seconds"] == 42
    assert package.payload["shot_list"] == approved_tiktok.payload["shot_list"]
    assert package.payload["voiceover"] == approved_tiktok.payload["voiceover"]
    assert package.payload["subtitles"] == approved_tiktok.payload["subtitles"]
    assert "待人工补充" not in str(package.payload)
```

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/content/tests/test_content_api.py backend/apps/content/tests/test_content_domain.py backend/tests/test_growth_workspace_api.py -q`

Expected: platform bodies are identical and TikTok contains the fixed 30-second/placeholder fields.

- [ ] **Step 3: Select and validate the exact platform variant**

For version 2, reject legacy copying, missing/duplicate variants and wrong platform/language/fact references. Preserve the existing idempotency and immutable provenance. Keep existing version-1 rows readable; require regeneration before creating a new legacy-derived channel record.

- [ ] **Step 4: Build channel packages from approved variant data**

Copy common fields for all four channels. For TikTok copy `duration_seconds`, `aspect_ratio`, `script`, `shot_list`, `voiceover`, `subtitles`, hashtags and UTM inputs. Do not add fixed language content or call any external platform.

- [ ] **Step 5: Run focused tests and commit**

Commit: `feat: preserve generated channel adaptations`

---

### Task 3: One ordinary AI creation path and visible structured result

**Files:**
- Modify: `frontend/src/modules/content/api.ts`
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentRecommendationPanel.vue`
- Modify: `frontend/src/modules/content/ContentReviewDialog.vue`
- Modify: `frontend/src/modules/growth/PromotionPage.vue`
- Test: `frontend/src/modules/content/ContentFactoryPage.test.ts`
- Test: `frontend/src/modules/content/ContentRecommendationPanel.test.ts`
- Test: `frontend/src/modules/content/ReviewCenterPage.test.ts`
- Test: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: versioned master/platform payloads returned by existing endpoints.
- Produces: one visible AI recommendation → selection → generation path plus reviewer-visible language, channel adaptation, hashtags, evidence and TikTok structure.

- [ ] **Step 1: Write failing ordinary-path tests**

```typescript
it("uses AI recommendation as the only ordinary creation action", async () => {
  render(ContentFactoryPage)
  expect(screen.getByRole("button", { name: "让 AI 推荐推广方向" })).toBeVisible()
  expect(screen.queryByRole("button", { name: "创建内容任务" })).not.toBeInTheDocument()
})

it("shows target language and the generated TikTok structure before approval", async () => {
  render(ReviewCenterPage)
  expect(await screen.findByText("发布语言：印尼语"))).toBeVisible()
  expect(screen.getByText("42 秒 · 9:16"))).toBeVisible()
  expect(screen.getByText("目标语言口播"))).toBeVisible()
})
```

- [ ] **Step 2: Run focused frontend tests and confirm RED**

Run: `pnpm vitest run src/modules/content/ContentFactoryPage.test.ts src/modules/content/ContentRecommendationPanel.test.ts src/modules/content/ReviewCenterPage.test.ts src/modules/growth/GrowthWorkspacePages.test.ts`

Expected: the legacy wizard action remains and structured version-2 fields are absent.

- [ ] **Step 3: Remove the competing ordinary wizard entry**

Keep history, revision, archive, job and result recovery controls. Make the recommendation panel the single primary creation entry and use plain Chinese status/error copy.

- [ ] **Step 4: Render the generated result and review evidence**

Show publication language, adapted channel title/body/CTA/hashtags and, for TikTok, duration, shot list, voiceover and subtitles. Label optional Chinese translation as internal-only and never send it to promotion/package views.

- [ ] **Step 5: Run focused tests and commit**

Commit: `feat: simplify evidence-backed content creation`

---

### Task 4: Contracts, regression and browser acceptance

**Files:**
- Modify generated API artifact only through the existing generator: `frontend/src/api/generated/schema.ts`
- Test: `frontend/e2e/` content workflow scenario

**Interfaces:**
- Consumes: all earlier task outputs.
- Produces: a clean, locally runnable and browser-proven slice.

- [ ] **Step 1: Add a browser scenario**

Prove recommendation selection → target-language master → distinct channel details → human review, with no real publish request and refresh persistence.

- [ ] **Step 2: Run backend verification**

Run backend focused tests, full `pytest -q`, Ruff, OpenAPI generation/check, and migration drift check.

- [ ] **Step 3: Run frontend verification**

Run full Vitest, ESLint, Vue typecheck, API artifact check, production build and focused/full E2E once after production code stabilizes.

- [ ] **Step 4: Verify local preview and clean commit**

Confirm ports 3001 and 8000 return 200, `git diff --check` passes, no real provider request was made during automated tests, and the worktree is clean.

Commit: `test: verify real multichannel content workflow`
