# Task 15 Fix Round 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close percent-encoded and standalone Basic/Bearer bypasses in public AI audit values without changing persistence, allowlists, or bounds.

**Architecture:** Extend the existing per-string detection copy only: NFKC-normalize, boundedly percent-decode up to three rounds with strict UTF-8 and fail-closed handling, then casefold and apply sensitive assignment and authorization-scheme detection. Exercise the behavior through the real AI-run detail API so every allowlisted serializer path is covered.

**Tech Stack:** Python 3.12, Django REST Framework, pytest, urllib.parse, Ruff.

## Global Constraints

- Modify only Task 15 AI public audit sanitization and its tests; do not start Task 16.
- Preserve database values, schema allowlists, string/value bounds, truncation behavior, and safe prose such as `token budget` and `password policy`.
- Decode at most three rounds and cap the detection copy before/after decoding.
- Malformed percent escapes or invalid UTF-8 must not produce a 500 and must fail closed when safety cannot be established.
- Commit exactly as `fix: close encoded audit credential bypasses`.

---

### Task 1: Encoded audit credential detection

**Files:**
- Modify: `backend/apps/ai/tests/test_ai_run_api.py`
- Modify: `backend/apps/ai/serializers.py`
- Create: `docs/superpowers/plans/2026-08-10-task-15-fix-round-3.md`

**Interfaces:**
- Consumes: `_redact_and_bound_string(value: str) -> str` via `AIRunSerializer` and `GET /api/v1/ai-runs/{run_id}`.
- Produces: bounded detection-copy decoding plus fail-closed `[REDACTED]` results; stored `AIRun` JSON remains unchanged.

- [ ] **Step 1: Write the failing real-API regression test**

  Add reviewer-provided standalone Basic/Bearer, encoded query/fragment names, double-encoded names, Unicode separators, malformed percent input, invalid UTF-8, unique sentinels, and safe prose across `input_snapshot`, `output_json`, and `human_correction`. Assert status 200, no raw/encoded sentinel or Basic payload in serialized JSON, safe prose retained, and stored fields unchanged.

- [ ] **Step 2: Run the focused test and verify RED**

  Run: `.venv/Scripts/python.exe -m pytest apps/ai/tests/test_ai_run_api.py -q`

  Expected: the new assertion fails because standalone schemes and encoded parameter names survive the current detection copy.

- [ ] **Step 3: Implement the minimal bounded detection-copy decoder**

  In `backend/apps/ai/serializers.py`, add a helper using `urllib.parse.unquote_to_bytes`, strict UTF-8, at most three rounds, and a finite detection-copy length. Detect trimmed standalone `basic`/`bearer` followed by space or tab, retain Authorization-prefixed matching, and return `[REDACTED]` on unsafe decoding.

- [ ] **Step 4: Verify GREEN and related security behavior**

  Run the AI API tests, AI orchestration/security-related tests, Ruff, Django check, migration drift check, and a reasonable existing frontend focused/full test because no frontend source changes are planned.

- [ ] **Step 5: Review, report, and commit**

  Run `git diff --check`, write `task-15-fix-round-3-report.md` in the Phase A SDD report directory, stage only round-three files, commit with the exact required message, and confirm a clean worktree.
