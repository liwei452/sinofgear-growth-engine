"""Centralized path and verification mappings used by ``scripts.verify``."""

from __future__ import annotations


CHECK_ORDER = (
    "diff",
    "ruff",
    "pytest",
    "django-check",
    "migration-drift",
    "openapi-validate",
    "api-check",
    "vitest",
    "typecheck",
    "eslint",
    "build",
    "e2e",
)

CHECK_LABELS = {
    "diff": "Patch hygiene",
    "ruff": "Ruff",
    "pytest": "Pytest",
    "django-check": "Django system check",
    "migration-drift": "Migration drift",
    "openapi-validate": "OpenAPI validation",
    "api-check": "API artifact check",
    "vitest": "Vitest",
    "typecheck": "vue-tsc",
    "eslint": "ESLint",
    "build": "Production build",
    "e2e": "Playwright E2E",
}

BACKEND_CHECKS = (
    "ruff",
    "pytest",
    "django-check",
    "migration-drift",
    "openapi-validate",
)
FRONTEND_CHECKS = ("api-check", "vitest", "typecheck", "eslint", "build")
API_CHECKS = ("api-check", "typecheck")

DOCUMENT_PREFIXES = ("docs/",)
DOCUMENT_SUFFIXES = (
    ".md",
    ".rst",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
)

BACKEND_GLOBAL_PATTERNS = (
    "backend/pyproject.toml",
    "backend/manage.py",
    "backend/config/settings.py",
    "backend/config/test_settings.py",
    "backend/config/e2e_settings.py",
    "backend/apps/common/models.py",
    "backend/apps/common/security.py",
    "backend/apps/common/tenancy.py",
    "backend/apps/common/tenant_tasks.py",
    "backend/apps/common/api.py",
    "backend/apps/common/openapi.py",
    "backend/apps/common/renderers.py",
)
BACKEND_GLOBAL_PREFIXES = ("backend/apps/common/",)

PRODUCTION_PREFIXES = (
    ".github/",
    "backend/",
    "frontend/",
    "infrastructure/",
    "scripts/",
)

FRONTEND_GLOBAL_PATTERNS = (
    "frontend/package.json",
    "frontend/pnpm-lock.yaml",
    "frontend/vite.config.ts",
    "frontend/playwright.config.ts",
    "frontend/eslint.config.js",
    "frontend/tsconfig.json",
    "frontend/tsconfig.app.json",
    "frontend/tsconfig.node.json",
    "frontend/src/main.ts",
)
FRONTEND_GLOBAL_PREFIXES = ("frontend/src/app/", "frontend/src/shared/")

ROOT_GLOBAL_PREFIXES = (".github/workflows/", "infrastructure/")
ROOT_GLOBAL_FILES = ("docker-compose.yml", ".env.example")

MODEL_FILE_NAMES = ("models.py", "context_models.py", "snapshot_models.py")
API_FILE_NAMES = (
    "api.py",
    "agent_views.py",
    "mission_serializers.py",
    "mission_views.py",
    "mission_attribution_views.py",
    "openapi.py",
    "serializers.py",
    "urls.py",
    "views.py",
    "work_item_views.py",
)
API_TEST_PATTERNS = ("test_*api*.py", "test_*schema*.py", "test_openapi*.py")

FRONTEND_SOURCE_SUFFIXES = (".ts", ".tsx", ".js", ".jsx", ".vue")
FRONTEND_TEST_PATTERNS = ("*.test.ts", "*.test.tsx", "*.test.js", "*.test.jsx")

E2E_BY_FRONTEND_MODULE = {
    "assets": ("asset-understanding.spec.ts",),
    "dashboard": ("phase-a-active-growth.spec.ts", "business-outcome-navigation.spec.ts"),
    "growth": ("growth-mission-flow.spec.ts", "phase-a-active-growth.spec.ts"),
    "opportunities": ("business-outcome-navigation.spec.ts",),
    "platformAccounts": ("social-connection-readiness.spec.ts", "social-operations.spec.ts"),
    "publishing": ("social-operations.spec.ts", "business-outcome-navigation.spec.ts"),
    "settings": ("ai-model-settings.spec.ts",),
}

E2E_MAIN_CHAIN_SUFFIXES = ("Page.vue", "Panel.vue", "router.ts", "navigation.ts")
