# Business Outcome Navigation UI Closeout

## Goal

Close the review findings on Draft PR #2 without changing Buffer/Publishing backend behavior. The four core workspaces must read as one light, evidence-led business product at desktop and mobile sizes.

## Decisions

- Results shows only persisted attribution fields. Unsupported discovery and conversion stages are removed rather than rendered as empty placeholders.
- Publishing keeps all seven backend statuses, but presents them under three primary groups: pending, planned, and completed. The original statuses remain secondary filters and card labels.
- Empty states explain the next safe action. Opportunity intake distinguishes task-led discovery from importing a list the organization is authorized to use.
- Opportunity and Results headers use the light medical-blue system. English decorative eyebrows are removed.
- Today uses one grouped decision surface with dividers instead of multiple nested card borders.
- Mobile acceptance is explicit at 360px for publishing navigation. Review screenshots use 1440x900 and 390x844.

## Safety boundaries

- No automatic outreach, scraping, paid API calls, account authorization, production deployment, or D3 work.
- No Buffer/Publishing backend business-logic changes.
- `schema.ts` is generated from the merged `backend/openapi.json`; it is never resolved by choosing a conflict side.
