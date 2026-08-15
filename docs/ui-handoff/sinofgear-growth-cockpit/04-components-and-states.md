# 04 Components and States

## Shared component layer

Create or consolidate these presentation components:

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

Components receive typed props/slots and emit UI events. They do not fetch business data, duplicate queries, or create business state.

## Required states for every data region

| State | Required treatment |
|---|---|
| Loading | Skeleton preserving final layout; never fake content |
| Empty | Short title, prerequisite explanation, one valid action |
| Error | Error beside failed region, cause when known, retry/recovery action |
| Ready | Real stored records only |
| Blocked | Named prerequisite and link to resolve it |
| Demo/Fake | Excluded from formal views; clearly labelled when intentionally visible in test environments |
| Permission denied | Explain required access; do not show broken/disabled mystery controls |
| Partial success | Show per-item/per-channel status and allow independent retry |
| Archived | Hidden from normal lists; visible in recycle bin with restore action |

## Interaction contracts

- At most one strong blue action per region.
- Disable asynchronous buttons while pending and show progress.
- Show errors near their action/field.
- Drawers/dialogs trap focus, close with Escape, restore focus, and have accessible names.
- Status always includes text; icon is optional; color alone is insufficient.
- Destructive-looking actions are reversible archive actions unless the existing backend explicitly supports more.
- Notifications appear only for real pending/failed records.
- Route changes focus the main heading/content region for assistive technology.

## Charts

- Line: time series with at least four real points.
- Horizontal bar: channel/country/category comparison.
- Funnel/linear stage list: sequential conversion flow with counts and conversion percentages.
- No pie/donut for more than five categories.
- Provide data table or text summary.
- Use line styles, labels, and shapes in addition to color.
- Empty/loading/error chart states are explicit; never draw empty axes as if they were data.

