# Task 15 Fix Round 4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail closed when public AI audit strings remain percent-encoded after the fixed decode-work budget.

**Architecture:** Keep the existing strict, bounded three-round decoding loop. After the loop, treat any remaining syntactically valid percent escape as unsafe so deeper encodings redact without adding an unbounded loop or increasing work; stable values with no valid escapes continue through existing credential detection.

**Tech Stack:** Python 3.12, Django REST Framework, pytest, urllib.parse, Ruff.

## Global Constraints

- Modify only Task 15 AI audit sanitization and its real API tests; do not start Task 16.
- Preserve the strict length and decode-work budgets, malformed/invalid fail-closed behavior, allowlists, bounds, truncation, and database immutability.
- Preserve all seven reviewer regressions and safe `token budget` / `password policy` prose.
- Commit exactly as `fix: fail closed on excessive audit encoding`.

---

### Task 1: Excessive percent-encoding fail-closed behavior

**Files:**
- Modify: `backend/apps/ai/tests/test_ai_run_api.py`
- Modify: `backend/apps/ai/serializers.py`
- Create: `docs/superpowers/plans/2026-08-10-task-15-fix-round-4.md`

**Interfaces:**
- Consumes: `_audit_detection_copy(value: str) -> str | None` through the real AI-run detail endpoint.
- Produces: `None` when a valid `%HH` escape remains after `_MAX_PERCENT_DECODE_ROUNDS`, causing whole-string `[REDACTED]` output.

- [ ] **Step 1: Add and verify a failing real-API regression**

  Programmatically construct the four-layer reviewer value from `https://x/?access_ token=DEPTH4-SENTINEL` and an `_MAX_PERCENT_DECODE_ROUNDS + 1`-style deeper value using an explicit test-side budget literal. Assert the constructed inputs have the intended layers, then assert raw inputs, sentinels, and every decoded layer are absent from the JSON response while safe prose survives and stored values remain unchanged.

- [ ] **Step 2: Implement the minimal bounded fail-closed check**

  Add a compiled valid-percent-escape expression and, after the fixed loop, return `None` when the result still contains `%[0-9A-Fa-f]{2}`. Do not add another loop or expand the existing length budget.

- [ ] **Step 3: Verify and commit**

  Run AI API plus orchestration/audit security tests, Ruff, Django check, migration drift, related Review Center frontend smoke, and `git diff --check`; write `task-15-fix-round-4-report.md`, commit the three repository files with the exact required message, and confirm a clean worktree.
