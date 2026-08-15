# Five-Page Growth Cockpit UI Redesign

Date: 2026-08-16

## Goal

Redesign the factory-owner interface as a polished blue-and-white AI growth cockpit while preserving the existing backend, data contracts, audit boundaries, permissions, routes, persistence, and no-fake-data policy. The approved visual reference is the earlier SinoFGear dashboard concept with procurement opportunities as the primary work surface, AI visibility and channel performance as secondary insight surfaces, and a compact professional sidebar.

## Product Experience

The interface should feel professional, credible, calm, and capable. It should communicate AI assistance without looking like a generic AI template, developer console, or analytics administration panel. A factory owner should understand the next useful action within five seconds of opening any primary page.

The product continues to expose five primary destinations:

1. Today
2. Promotion
3. Customer Opportunities
4. Results
5. My Company

Settings, assets, product library, knowledge library, content factory, review center, publishing calendar, platform accounts, and advanced analytics remain available as contextual secondary destinations. They do not become additional primary navigation items.

## Non-Goals

- No backend domain, API, database, AI-provider, OAuth, publishing, discovery, tracking, or CRM behavior changes.
- No invented customers, scores, channel trends, AI visibility records, dates, or performance metrics.
- No modification of the independent external-trade website.
- No real social publication, outreach, scraping, paid API call, account authorization, production deployment, or DNS change.
- No wholesale replacement of Vue, TanStack Query, router, accessibility utilities, or the existing test stack.

## Current Problems to Correct

- The visual language resembles a generic development/admin dashboard rather than a finished growth product.
- Most surfaces use the same white card, border, radius, and visual weight, so primary work and supporting information compete equally.
- Promotion is a very long vertical page that exposes account setup, content review, publishing readiness, packages, evidence, export, and results at the same time.
- Empty states are honest but occupy large blank areas and make the product look unfinished instead of guiding the owner.
- Text initials are used as navigation icons instead of a cohesive SVG icon set.
- Page-level CSS repeats patterns and allows type, spacing, card, state, and action treatments to drift.
- Secondary technical tools are discoverable primarily through settings rather than from the business task that needs them.

## Global Shell

Use a fixed desktop sidebar approximately 216–224 pixels wide and a compact sticky top bar. The main content area may expand to approximately 1440 pixels while preserving comfortable gutters.

The sidebar contains:

- A refined SinoFGear logo lockup and the subtitle “AI Social Growth Engine”.
- Today, Promotion, Customer Opportunities, Results, and My Company.
- A company switcher or company identity block at the bottom.
- Help and Settings as visually quieter utilities.

Use one consistent Lucide-style outline SVG icon per navigation item. Do not use emoji, Chinese character initials, letter avatars as navigation icons, or mixed filled/outline icon families.

The top bar contains the current page title, a short contextual sentence when useful, notifications only when real records exist, and the user menu. Remove the redundant “current location” label. User and organization information should be compact and not visually dominate the task.

On viewports below 860 pixels, the sidebar becomes an accessible drawer with focus trapping, Escape close, backdrop close, and focus restoration. Preserve the existing keyboard behavior.

## Visual System

### Color

- Primary blue: `#1268E3`
- Primary hover: `#0B56C5`
- Primary soft: `#EAF2FF`
- Success: `#18A66A`
- Success soft: `#EAF8F1`
- Warning: `#E99A20`
- Warning soft: `#FFF6E7`
- Destructive: `#C83D4D`
- Canvas: `#F6F8FB`
- Surface: `#FFFFFF`
- Strong text: `#172235`
- Muted text: `#667386`
- Border: `#DDE4ED`
- Focus ring: a visible high-contrast blue/gold treatment meeting accessibility requirements.

The system does not use purple AI styling, neon glow, glassmorphism, heavy gradients, or decorative dark mode in this phase.

### Typography

Use Inter for Latin and numerals with `PingFang SC`, `Microsoft YaHei`, and system sans-serif fallbacks for Chinese. Base body text is at least 14 pixels with approximately 1.5 line height. Use a restrained type scale around 12, 14, 16, 20, and 28 pixels. Primary page headings are approximately 28 pixels; card headings are 16–20 pixels. Avoid all-caps English eyebrow labels except short platform or data labels.

### Shape, Elevation, and Density

- Standard card radius: 12 pixels.
- Control radius: 8 pixels.
- Chips use a pill radius only for short statuses and filters.
- Borders provide most surface separation; shadows are subtle and reserved for floating overlays and primary dashboard panels.
- Desktop density is moderately compact. Repeated records should fit without feeling cramped.
- Use a spacing scale based on 4, 8, 12, 16, 20, 24, and 32 pixels.

### Actions and States

- Each region has at most one visually strong blue primary action.
- Secondary actions use white surfaces and borders; tertiary actions use text buttons.
- Status never relies on color alone; include text and, where helpful, an icon.
- Interactive targets are at least 44 by 44 pixels where practical.
- Hover/focus/pressed/loading transitions last approximately 150–200 milliseconds.
- Respect `prefers-reduced-motion`.

## Page 1: Today

Today is the visual anchor and follows the approved reference layout.

Desktop layout:

- Left column approximately 58 percent: today’s verified procurement opportunities.
- Right column approximately 42 percent: AI brand/search visibility above channel performance.

The header greets the current team or company and explains that AI is helping discover opportunities and improve visibility. It does not use emoji as a permanent interface icon.

Opportunity records show only:

- Company and country.
- Industry and approximate size when verified.
- Need summary.
- Source and observation time.
- Intent label based on stored evidence.
- One primary action such as “Add to follow-up”.

Evidence, draft generation, contact routes, and follow-up history open in a right-side detail drawer. They do not expand every record vertically.

AI visibility displays a score only when the required real observation records exist. Otherwise it shows a compact readiness checklist and one next action. Channel performance displays real saved metrics only. Empty states occupy the same structured panel footprint but use concise guidance rather than large dashed boxes.

## Page 2: Promotion

Replace the current long all-at-once layout with a four-step task flow:

1. Select market.
2. Prepare content.
3. Connect accounts.
4. Review and publish.

The top of the page shows the current step, overall progress, market/ICP summary, and the single next action. Only the current step is expanded by default. Completed steps collapse into concise summaries; blocked steps explain the missing prerequisite.

Account readiness, platform-specific packages, verified fact evidence, TikTok script details, manual export, and publish results remain available through step panels, drawers, or secondary detail pages. The UI must not remove their data or safety checks.

The five account channels remain Facebook, Instagram, LinkedIn, TikTok, and YouTube. Publishing remains human-approved and no button claims readiness when configuration, account permission, content approval, or platform review is missing.

## Page 3: Customer Opportunities

Use a master-detail workspace on desktop:

- Left: searchable/filterable opportunity list with company, country, need, source, confidence, and follow-up state.
- Right: selected opportunity detail with evidence, score explanation, company profile, public contact path, enrichment state, timeline, and actions.

The selected opportunity, filters, sort, and open detail section persist across refresh where the existing data and URL model allow it. On mobile, list and detail become separate navigable states with predictable browser Back behavior.

The primary action is “Add to follow-up” or the next valid stage action. Draft generation and copying remain secondary. Evidence source links stay visible and safe.

## Page 4: Results

Organize results into three levels:

1. Real KPI summary: opportunities, followed accounts, published content, clicks/replies/inquiries when recorded.
2. Conversion path: discovery to candidate, review, follow-up, contact draft, publication, response, and inquiry.
3. Channel and account attribution: channel comparison followed by specific attributable records.

Do not show charts with invented zeros or decorative trends. With insufficient data, show the exact missing inputs and a direct link to enter or connect them. Tables and charts must include labels, legends, and text alternatives; color is not the only encoding.

## Page 5: My Company

Turn My Company into the source-of-truth readiness page. The header shows a real completeness summary derived from existing records, not an arbitrary percentage.

Organize the page into:

- Confirmed company facts and facts awaiting review.
- Products and product facts.
- Assets/documents and AI-understanding status.
- Content readiness and gaps.
- Social account readiness summary with a link to the Promotion connection step.

Upload, product editing, fact verification, and knowledge management are contextual actions. Advanced libraries remain secondary pages linked from the relevant section.

## Empty, Loading, Error, and Demo States

- Skeletons preserve layout during loading without presenting fake business content.
- Empty states contain a short title, one sentence explaining the prerequisite, and one primary action.
- Errors remain close to the failed region and include a recovery action.
- Demo/Fake data remains excluded from formal work surfaces. If a test environment intentionally displays fixtures, it must retain a visible Demo/Fake label.
- Refresh never replaces failed real data with demo content.

## Component Boundaries

Create a small reusable visual layer instead of adding more page-specific CSS:

- `AppSidebar`
- `AppTopbar`
- `PageHeader`
- `WorkspacePanel`
- `StatusBadge`
- `EmptyState`
- `MetricCard`
- `StepProgress`
- `DetailDrawer`
- `OpportunityListItem`
- `ChannelCard`

Components expose content and state through typed props/slots. They do not fetch business data or duplicate API calls. Existing query modules remain the data owners.

Centralize tokens for color, typography, radius, spacing, elevation, transitions, and responsive breakpoints. Page-specific CSS may define layout but should not redefine base buttons, cards, badges, focus rings, or typography.

## Accessibility and Responsive Requirements

- Text contrast meets WCAG AA, normally at least 4.5:1.
- Every function is keyboard accessible with a logical tab order and visible focus.
- Provide a skip-to-content link for the persistent sidebar shell.
- Drawers and dialogs trap focus, close with Escape, restore focus, and carry correct accessible names.
- Responsive acceptance covers 375, 768, 1024, and 1440 pixel widths.
- No horizontal page overflow. Intentional table overflow is contained and labelled.
- Status, chart, and validation meaning is never color-only.

## Implementation Sequence

1. Shared design tokens, SVG icon system, shell, and shared primitives.
2. Today.
3. Customer Opportunities.
4. Promotion.
5. Results.
6. My Company.
7. Cross-page responsive, accessibility, visual regression, full tests, and browser acceptance.

Each page is an independently reviewable and reversible commit. Do not attempt one giant CSS rewrite. Existing business tests must remain green, and new tests focus on user-visible behavior rather than CSS implementation details.

## Acceptance

- The five primary destinations are the only primary sidebar destinations.
- The Today layout visually follows the approved SinoFGear reference without reintroducing fake opportunities, scores, or charts.
- Promotion no longer exposes every stage simultaneously.
- Opportunities uses a clear master-detail pattern on desktop and navigable list/detail on mobile.
- Results shows only recorded metrics and explicit missing-data guidance.
- My Company is the clear source-of-truth readiness surface.
- Shared components/tokens replace duplicated page-level treatments.
- SVG icons replace text-character navigation icons.
- Keyboard, focus, reduced-motion, contrast, responsive, persistence, unit, full frontend, build, and browser tests pass.
- No backend behavior, independent website, real external account, live publication, paid API, DNS, or production deployment is changed.
