# 05 Code and Data Boundaries

## Allowed

- Vue templates and presentation structure.
- Shared CSS tokens and component styling.
- Responsive layout and accessible interaction behavior.
- Reuse/recomposition of existing components and routes.
- New presentation-only components.
- UI tests, accessibility tests, browser tests, and screenshots.

## Forbidden without a separate approved task

- Backend model, migration, API, permission, AI, OAuth, publishing, discovery, tracking, CRM, storage, or security changes.
- Independent website changes.
- Real external API calls, account authorization, publication, outreach, paid services, scraping, DNS, or deployment.
- Fake customers, opportunities, contacts, scores, graphs, dates, metrics, readiness, notifications, or AI results.
- Replacing Vue, Vue Router, TanStack Query, current API modules, or the test stack.
- Removing safety checks because they complicate the layout.

## Existing route map

| Primary destination | Route | Existing owner |
|---|---|---|
| Today | `/` | Dashboard module |
| Promotion | `/promotion` | `growth/PromotionPage.vue` |
| Customer Opportunities | `/opportunities` | `growth/OpportunitiesPage.vue` |
| Results | `/analytics` | Analytics/growth results modules |
| My Company | `/company` | `growth/CompanyPage.vue` |

Secondary routes remain unchanged: `/settings`, `/products`, `/knowledge`, `/content-factory`, `/reviews`, `/assets`, `/publishing-calendar`, `/platform-accounts`, and administrator analytics.

## Data integrity rules

- Existing query modules remain the data owners.
- Presentation components may filter, group, or format already loaded records but must not manufacture defaults that look real.
- A missing number is displayed as unavailable/not yet recorded, not `0`, unless the stored value is actually zero.
- AI visibility, intent, confidence, readiness, and completeness require their existing evidence records.
- Source links, timestamps, provider labels, fake/demo labels, and approval states must stay visible.
- Existing permissions determine visibility and actions.
- Refresh and navigation must preserve existing persisted records; UI state may use URL/query or existing local persistence only where already allowed.

## Delivery isolation

Work in a dedicated branch or worktree after the current functional development slice is committed. Each stage is independently reviewable:

1. tokens + shell + shared primitives;
2. Today;
3. Customer Opportunities;
4. Promotion;
5. Results;
6. My Company;
7. responsive/accessibility/full regression.

Do not make one giant CSS rewrite.

