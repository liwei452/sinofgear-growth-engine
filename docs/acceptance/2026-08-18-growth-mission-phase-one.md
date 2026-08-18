# Growth Mission Phase One Acceptance Notes

Date: 2026-08-18

This phase introduces the "Growth Mission" vertical slice. The top-level business
object is now `GrowthMission`; `AgentRun`, `Campaign`, `ChannelPackage`, and
`PublishTask` remain internal execution objects.

## New API routes

- `GET/POST /api/v1/growth/missions`
- `GET/PATCH /api/v1/growth/missions/<mission_id>`
- `POST /api/v1/growth/missions/<mission_id>/generate-plan`
- `POST /api/v1/growth/missions/<mission_id>/approve-plan`
- `POST /api/v1/growth/missions/<mission_id>/status`
- `GET /api/v1/growth/missions/<mission_id>/timeline`
- `POST /api/v1/growth/missions/<mission_id>/candidates/<candidate_id>/start-outreach`
- `POST /api/v1/growth/missions/<mission_id>/start-content-strategy`
- `GET /api/v1/growth/work-items`
- `GET /api/v1/growth/attribution?mission=<mission_id>`

## Role mapping

- `missions.read` — operators, reviewers, and read-only executives.
- `missions.manage` — administrators only.
- `missions.review` — administrators only (mission-level plan approval).
- Ordinary reviewers approve generated emails and content through their existing
  `agents.approve` / `content.review` / `publishing.manage` permissions.

## Mission lifecycle

`DRAFT -> PENDING_APPROVAL -> RUNNING -> PAUSED -> COMPLETED/TERMINATED`.
Generating a plan moves a `DRAFT` mission to `PENDING_APPROVAL`; approving a plan
moves it to `RUNNING` and supersedes other plans.

## Work-item projection rules

- Waiting Agent run with a blocked `send_email` step and connected email ->
  `OUTREACH_REVIEW` / `APPROVE_AGENT_RUN`.
- Waiting Agent run with a blocked `send_email` step and unconnected email ->
  `CONFIGURATION_BLOCK` / `OPEN_SETTINGS` ("等待管理员连接邮箱").
- Other waiting Agent runs -> `AGENT_REVIEW`.
- Non-demo `ChannelPackage` with `AWAITING_REVIEW`, grouped by master content ->
  `SOCIAL_REVIEW` / `APPROVE_CHANNEL_PACKAGE_GROUP`.
- Non-demo failed `GrowthPublishItem` -> `EXECUTION_FAILURE` / `RETRY_PUBLISH_BATCH`.
- `InboundLead.route == MANUAL_REVIEW` or human escalation -> `CUSTOMER_REPLY`.

## Attribution confidence rules

- `CONFIRMED` — mission-linked account plus a persisted reply, RFQ, quote, or won deal.
- `ASSISTED` — mission-linked metric receipt or manually linked company visit.
- `UNATTRIBUTED` — anonymous impressions and clicks; diagnostic only.
- Unconnected channels report `None` plus an availability reason; never zero.

## Legacy redirects

- `/analytics` -> `/attribution`
- `/agent-approvals` -> `/?view=approvals`
- `/agent-workspace`, `/reviews`, `/promotion`, `/publishing-calendar`, and
  `/platform-accounts` remain routable for bookmarks and administrator diagnostics
  but are removed from primary navigation.

## Known unconnected channels

Real email and official social connectors are intentionally out of scope for this
phase. Demo/Fake connectors cannot create formal `SENT` or `PUBLISHED` state.

## Rollback behavior

Legacy domain objects and routes are preserved during migration. The new mission
models are additive; dropping the new routes and navigation restores the prior
module-first workspace without losing existing discovery, outreach, content, or
publishing data.
