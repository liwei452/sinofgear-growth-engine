# 06 Acceptance Checklist

## Navigation and hierarchy

- [ ] Only five primary destinations appear in the primary sidebar.
- [ ] Settings, Help, company identity, and secondary tools are visually subordinate.
- [ ] Active location is obvious with text and visual state.
- [ ] Deep links and browser Back behavior remain correct.

## Visual quality

- [ ] Matches the calm blue-white industrial cockpit direction.
- [ ] Uses approved semantic tokens instead of page-level raw colors.
- [ ] Uses one SVG outline icon family and official platform marks.
- [ ] Avoids emoji icons, purple AI gradients, glassmorphism, heavy shadows, and repeated identical cards.
- [ ] One strong primary action per region.

## Page behavior

- [ ] Today follows the approved 58/42 opportunity-and-insight layout on desktop.
- [ ] Promotion is a four-step progressive flow, not one long expanded page.
- [ ] Opportunities is master-detail on desktop and navigable list/detail on mobile.
- [ ] Results shows only recorded metrics and explicit missing-data guidance.
- [ ] My Company is a real source-of-truth readiness surface.

## Real-data policy

- [ ] No invented customer, score, trend, date, notification, or metric.
- [ ] Missing data never silently becomes zero or demo content.
- [ ] Evidence sources, timestamps, provider/fake labels, approval states, and recovery paths remain visible.
- [ ] Partial success and per-channel failure are represented honestly.

## Accessibility

- [ ] WCAG AA text contrast, normally 4.5:1.
- [ ] Full keyboard operation and visible focus.
- [ ] Skip-to-content link.
- [ ] Drawers/dialogs trap and restore focus and close with Escape.
- [ ] Touch/click targets approximately 44×44px where practical.
- [ ] Status and chart meaning is not color-only.
- [ ] Reduced-motion preference is respected.
- [ ] Charts include text/table alternatives.

## Responsive acceptance

- [ ] 375px, 768px, 1024px, and 1440px screenshots reviewed.
- [ ] No page-level horizontal overflow.
- [ ] Sidebar becomes an accessible drawer below the approved breakpoint.
- [ ] Mobile body text is at least 16px where input zoom/readability matters.
- [ ] Primary content appears before supporting content on small screens.

## Engineering verification

- [ ] Existing backend and business behavior unchanged.
- [ ] Existing unit and integration tests pass.
- [ ] New presentation behavior tests pass.
- [ ] Type checking passes.
- [ ] Production build passes.
- [ ] Browser E2E main flows pass.
- [ ] Worktree is clean and commits are separated by stage.
- [ ] No real external account, API write, publication, outreach, payment, deployment, DNS, or deletion occurred.

## Required handoff evidence

- [ ] Desktop and mobile screenshots for all five primary pages.
- [ ] Loading, empty, error, blocked, and ready states demonstrated.
- [ ] Keyboard/focus demonstration for drawer and dialog.
- [ ] Test/build output summary.
- [ ] File list and commit list.
- [ ] Explicit list of unchanged backend/API files.

