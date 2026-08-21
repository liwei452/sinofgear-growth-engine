# Database RLS Phase 2 inventory

## Scope and verification contract

Baseline: `3612756f62d082ba2ee7e9823dc6ff9bc3b15cda`.

The executable source of truth is `backend/apps/common/rls_manifest.py`. It contains one frozen entry for every managed, concrete business model returned by Django with `include_auto_created=True`. The audit deliberately excludes only the built-in Django `admin`, `auth`, `contenttypes`, and `sessions` app labels. `django_migrations` is also explicitly documented as Django infrastructure; it is not represented in the apps registry. No business app is excluded. The `sources` app has adapters and records but no database model at this baseline.

The manifest is review input, not migration input. Future RLS migrations must copy the reviewed table and policy definitions into the migration so historical behavior cannot change when this Python file changes.

`python manage.py audit_rls_coverage` fails if a model/table is missing, duplicated, renamed without updating the manifest, or has invalid organization metadata. It reads model metadata only and never emits rows, secrets, connection strings, or field values.

## Classification inventory

Total business tables: **96**. There are currently no auto-created business M2M tables; the registry audit still includes them so the next one cannot be added silently.

### TENANT_DIRECT — 78

These tables carry an `organization_id` column directly.

```text
ai_airun
ai_organizationaiproviderconfig
assets_assetproductlink
assets_materialasset
assets_productevidencefact
audit_approvalrecord
audit_auditlog
campaigns_campaign
campaigns_campaignproduct
campaigns_contentbrief
campaigns_contentbriefasset
campaigns_contentbriefconceptlink
campaigns_contentbriefplatform
campaigns_contentbriefproduct
catalog_product
catalog_productconceptlink
content_contentrecommendation
content_contentrecommendationoption
content_mastercontent
content_platformcontent
growth_accountfunnelevent
growth_agentrun
growth_agentrunstep
growth_candidateenrichmentsnapshot
growth_channelpackage
growth_contact
growth_crmhandoff
growth_customerserviceturn
growth_discoverycandidate
growth_discoveryprofile
growth_discoveryrun
growth_fieldprovenance
growth_followup
growth_googlemapsdiscoveryconfig
growth_growthevent
growth_growthmission
growth_growthpublishbatch
growth_growthpublishitem
growth_inboundlead
growth_inboundrfq
growth_intentsignal
growth_leadwebsitevisit
growth_marketcountryprofile
growth_metricreceipt
growth_missionentitylink
growth_missionplan
growth_opportunityreview
growth_outreachdraft
growth_outreachmessage
growth_promotionplanapproval
growth_reactivationrecord
growth_salesdeal
growth_targetaccount
growth_tradecompanymatch
growth_tradedatasetsnapshot
growth_tradesyncrun
identity_phaseae2eownership
jobs_job
knowledge_companyfact
knowledge_companyknowledgeprofile
knowledge_icpprofile
knowledge_knowledgecontextsnapshot
knowledge_websitepage
platforms_accountconnectionsession
platforms_connectorcredential
platforms_encryptedoauthcredential
platforms_oauthconnectionattempt
platforms_providerconnection
platforms_providerconnectionevent
platforms_socialaccount
publishing_postmetric
publishing_publishattempt
publishing_publishedpost
publishing_publishreconciliationattempt
publishing_publishtask
tracking_clickevent
tracking_shortlink
tracking_trackinglink
```

### TENANT_PARENT — 5

```text
jobs_jobattempt                         -> job.organization
knowledge_companyfactevidence          -> company_fact.organization
knowledge_icpproductlink               -> icp_profile.organization
knowledge_websitepageconceptlink       -> website_page.organization
knowledge_websitepageproductlink       -> website_page.organization
```

### TENANT_MIXED — 6

The first four have nullable `organization_id` plus legal SYSTEM rows. The two evidence through tables can themselves represent either SYSTEM or organization-scoped graph data and therefore are mixed even though their organization is parent-derived.

```text
knowledge_knowledgealias
knowledge_knowledgeconcept
knowledge_knowledgeevidence
knowledge_knowledgerelation
knowledge_knowledgeconcept_evidence    -> knowledgeconcept.organization
knowledge_knowledgerelation_evidence   -> knowledgerelation.organization
```

### GLOBAL_CONTEXT_READ — 3

```text
ai_promptversion
platforms_platform
platforms_platformcapability
```

These are shared prompt/platform dictionaries. Runtime needs them, but a runtime connection with no tenant context must not enumerate them. RLS-2A should allow SELECT only when `app_current_organization_id()` is non-null and should keep runtime writes denied. Owner-managed seed/release workflows remain separate.

### CONTROL_PLANE — 3

- `identity_organization`: root tenant identity. Organization enumeration or a trusted slug lookup is needed before a GUC can exist.
- `identity_membership`: authoritative user-to-organization lookup used by `HasOrganizationPermission` before any tenant query.
- `identity_role`: permission dictionary joined while validating the active Membership before tenant context is established.

These tables are intentionally outside tenant RLS. Their application APIs still enforce authentication and authorization; keeping them outside RLS is not permission to expose their rows.

### GLOBAL — 1

- `knowledge_knowledgegraphlock`: singleton serialization lock for ontology graph mutations. It contains only the global lock identity/name, no tenant or customer data. Applying tenant RLS would prevent SYSTEM and cross-tenant graph serialization and would not protect any customer row.

## Phase ownership

- **RLS-1 already covered — 15:** `knowledge_companyfact`, `knowledge_companyfactevidence`, `knowledge_companyknowledgeprofile`, `knowledge_icpproductlink`, `knowledge_icpprofile`, `knowledge_knowledgealias`, `knowledge_knowledgeconcept`, `knowledge_knowledgeconcept_evidence`, `knowledge_knowledgecontextsnapshot`, `knowledge_knowledgeevidence`, `knowledge_knowledgerelation`, `knowledge_knowledgerelation_evidence`, `knowledge_websitepage`, `knowledge_websitepageconceptlink`, `knowledge_websitepageproductlink`.
- **RLS-2A — 21:** `ai_airun`, `ai_organizationaiproviderconfig`, `ai_promptversion`, `assets_assetproductlink`, `assets_materialasset`, `assets_productevidencefact`, `audit_approvalrecord`, `audit_auditlog`, `catalog_product`, `catalog_productconceptlink`, `jobs_job`, `jobs_jobattempt`, `platforms_accountconnectionsession`, `platforms_connectorcredential`, `platforms_encryptedoauthcredential`, `platforms_oauthconnectionattempt`, `platforms_platform`, `platforms_platformcapability`, `platforms_providerconnection`, `platforms_providerconnectionevent`, `platforms_socialaccount`.
- **RLS-2B — 16:** `campaigns_campaign`, `campaigns_campaignproduct`, `campaigns_contentbrief`, `campaigns_contentbriefasset`, `campaigns_contentbriefconceptlink`, `campaigns_contentbriefplatform`, `campaigns_contentbriefproduct`, `content_contentrecommendation`, `content_contentrecommendationoption`, `content_mastercontent`, `content_platformcontent`, `publishing_postmetric`, `publishing_publishattempt`, `publishing_publishedpost`, `publishing_publishreconciliationattempt`, `publishing_publishtask`.
- **RLS-2C — 40:** all 36 `growth_*` tables, `identity_phaseae2eownership`, and the three `tracking_*` tables.
- **Explicit exemptions — 4:** the three CONTROL_PLANE tables and `knowledge_knowledgegraphlock`.

The requested A/B/C grouping is runnable only if each phase lands its task/service context changes together with its policies. In particular, RLS-2A must repair job and credential workers in the same commit as their table policies, and RLS-2B must repair publish/content workers. The requested outline placed Tracking in RLS-2B but its only public locator is the tenant `ShortLink` row itself; enabling fail-closed RLS there would break redirects until RLS-2C. The manifest therefore moves all three Tracking tables to RLS-2C so the tables and the safe public locator land atomically.

## Sensitive-data markers

The manifest records four independent flags per table: credentials, customer content, publishing data, and audit data. High-risk groups are:

- Credentials: `ai_organizationaiproviderconfig`, `growth_googlemapsdiscoveryconfig`, `identity_phaseae2eownership`, and the seven organization-scoped platform connection/credential tables.
- Customer content: product/assets, knowledge, campaign/content, tracking, publishing, AI runs/jobs, audit metadata, and all growth operational tables. The manifest is conservative where JSON/metadata can carry customer content.
- Publishing data: content outputs, platform/provider accounts, publishing tasks/attempts/posts/metrics, tracking links/clicks, and growth channel/publish records.
- Audit data: approval/audit logs, run/attempt records, review snapshots, provider connection events, and append-only operational history.

## HTTP request audit

`DATABASES["default"]["ATOMIC_REQUESTS"]` wraps API requests. Every permission in `apps.identity.permissions` derives from `HasOrganizationPermission`: it reads the active `Membership` and related `Organization`/`Role` from the control plane, assigns `request.organization`, then calls transaction-local `set_local_tenant`. Catalog, assets, campaigns, jobs, AI, content, publishing, tracking management, growth, and Knowledge endpoints using those permission classes therefore establish the GUC before their view ORM queries.

| HTTP route group | `HasOrganizationPermission` subclasses used |
|---|---|
| Identity current-user/membership APIs | `CanReadMemberships`, `CanManageMemberships` |
| Catalog | `CanReadProducts`, `CanManageProducts` |
| Assets | `CanReadAssets`, `CanManageAssets` |
| Knowledge | `CanReadKnowledge`, `CanCreateKnowledge`, `CanReviewOrganizationKnowledge`, `CanDeprecateKnowledge` |
| Campaigns | `CanReadCampaigns`, `CanManageCampaigns`, `CanReviewCampaigns` |
| Jobs and AI run APIs | `CanReadJobs`, `CanManageJobs`; AI credential APIs use `CanManageCredentials` |
| Content | `CanReadContent`, `CanManageContent`, `CanReviewContent` |
| Publishing and authenticated Tracking analytics/link APIs | `CanReadPublishing`, `CanManagePublishing`, `CanReadTracking`, `CanManageTracking` |
| Growth, missions, leads, agents, metrics | `CanRead/ManageLeads`, `CanRead/Manage/ReviewMissions`, `CanRun/ApproveAgents`, `CanReadMetrics`, and campaign/publishing permissions where reused |
| Standard platform/social-account APIs | `CanReadMemberships`, `CanManageCredentials`, `CanReadPublishing` |

The table describes route groups rather than trusting URL prefixes: the conclusion was checked from each view's `permission_classes` or `get_permissions` declaration. The four Buffer administrator views are the exception described below.

Pre-context or exceptional paths:

| Entry | Before tenant GUC | Finding |
|---|---|---|
| `auth/login` | Django `auth_user` credential lookup | Expected control plane; no business tenant table. |
| `auth/csrf`, `auth/logout` | Session/auth infrastructure | Expected control plane; no business tenant table. |
| `auth/me`, Membership detail | `Membership -> Organization, Role` in `HasOrganizationPermission` | Expected control plane, then tenant GUC exists. |
| Buffer admin views | `platforms.CanAdministerBuffer` reads Membership/Role and sets `request.organization` only | **RLS-2A risk:** it does not call `set_local_tenant`; its first platform ORM query will fail closed after RLS or could run without isolation before RLS. |
| Platform OAuth callback | `CanManageCredentials` first establishes tenant; `_platform_or_404` then reads global Platform | Safe ordering, but Platform becomes context-gated in RLS-2A. |
| Knowledge APIs | `CanRead/Create/Review/DeprecateKnowledge` | Covered by HTTP tenant transaction and RLS-1.1 lazy-query contract. |
| Health/OpenAPI schema | No business ORM required for health; schema introspects code | Global infrastructure, not tenant data. |

No other non-test permission class assigns `request.organization`; the Buffer permission is the only authenticated exception found by source search.

## Celery task audit

No non-Knowledge task currently calls `tenant_atomic`. Object-ID-only tasks cannot safely query the object first under fail-closed RLS; they need a trusted native `organization_id` task argument (or a separately designed control-plane locator) and must enter `tenant_atomic` before the first tenant ORM query.

| Task | Current arguments | First ORM access | Risk / target |
|---|---|---|---|
| `apps.jobs.tasks.execute_ai_job` | `job_id`, `prompt_version_id` | `Job.objects.get(job_id)` | Object-ID-only; RLS-2A blocker. |
| `apps.jobs.tasks.refresh_social_credentials` | optional `organization_id` | cross-tenant `SocialAccount` queryset | Optional scope is unsafe; RLS-2A must require/enumerate tenant context. |
| `apps.jobs.tasks.reap_stale_jobs` | none | cross-tenant `Job` stale scan | Beat coordinator risk; RLS-2A. |
| `apps.assets.tasks.run_asset_understanding` | `job_id` | `Job.objects.get(job_id)` | Object-ID-only; RLS-2A blocker. |
| `apps.content.tasks.generate_master_content_job` | `job_id`, `prompt_version_id` | `Job.objects.get(job_id)` through AI orchestration | Object-ID-only; RLS-2A/2B bridge. |
| `apps.content.tasks.generate_platform_variants_job` | `job_id` | `Job.objects.get(job_id)` | Object-ID-only; RLS-2A/2B bridge. |
| `apps.content.tasks.generate_content_recommendations_job` | `job_id`, `prompt_version_id` | `ContentRecommendation.objects.get(job_id)` | Object-ID-only; RLS-2B blocker. |
| `apps.growth.tasks.scan_due_discovery_profiles` | `limit` | cross-tenant `DiscoveryProfile` scan | Beat coordinator risk; RLS-2C. |
| `apps.growth.tasks.scan_due_maps_configs` | `limit` | cross-tenant `GoogleMapsDiscoveryConfig` scan | Beat coordinator risk; RLS-2C. |
| `apps.growth.tasks.run_proactive_acquisition_task` | `organization_id`, `candidate_id`, approvals | control-plane `Organization.objects.get`, then tenant service without `tenant_atomic` | Has trusted tenant parameter but must enter context before candidate access; RLS-2C. |
| `apps.growth.tasks.run_due_proactive_acquisition` | `limit` | cross-tenant `DiscoveryCandidate` scan | Beat coordinator risk; RLS-2C. |
| `apps.growth.tasks.execute_growth_publish_item` | `item_id` | `GrowthPublishItem.objects.get` | Object-ID-only; RLS-2C blocker. |
| `apps.growth.tasks.sync_growth_publish_item_from_task` | `task_id` | `GrowthPublishItem.objects.filter(publish_task_id)` | Object-ID-only across Growth/Publishing; RLS-2B/2C blocker. |
| `apps.growth.tasks.reconcile_delegated_publish_items` | `limit` | cross-tenant `GrowthPublishItem` scan | Beat coordinator risk; RLS-2C. |
| `apps.publishing.tasks.run_publish_task` | `task_id` | `PublishedPost`/`PublishTask` lookup | Object-ID-only; RLS-2B blocker. |
| `apps.publishing.tasks.queue_due_publish_tasks` | `limit` | cross-tenant `PublishTask` scan | Beat coordinator risk; RLS-2B. |
| `apps.publishing.tasks.sync_post_metrics_hourly` | none | control-plane Organization enumeration, then tenant `PublishedPost` without context | Enumeration pattern is appropriate, but each iteration needs `tenant_atomic`; RLS-2B. |
| `apps.publishing.tasks.reap_stale_publish_tasks_task` | none | cross-tenant `PublishTask` stale scan | Beat coordinator risk; RLS-2B. |
| `apps.publishing.tasks.reconcile_buffer_publish_task_job` | `task_id` | `PublishTask.objects.get` | Object-ID-only; RLS-2B blocker. |
| `apps.publishing.tasks.reconcile_buffer_publish_tasks` | `limit` | cross-tenant `PublishTask` reconciliation scan | Beat coordinator risk; RLS-2B. |

KnowledgeContextBuilder and Knowledge review/revision services already self-enter `tenant_atomic` from a trusted Organization. They are not Celery tasks at this baseline.

## Celery Beat / scheduled scans

Nine configured Beat entries scan tenant tables:

1. `growth-discovery-hourly`
2. `growth-maps-discovery-hourly`
3. `growth-proactive-acquisition-daily`
4. `growth-publish-reconciliation-hourly`
5. `publishing-queue-due-minute`
6. `publishing-buffer-reconciliation-minute`
7. `jobs-reap-stale-minute`
8. `publishing-sync-post-metrics-hourly`
9. `publishing-reap-stale-minute`

The target design is a small coordinator that reads only the control-plane Organization list, closes that control-plane query, then runs one bounded `tenant_atomic(organization.id)` unit per organization. It must not use an owner/bypass connection, and one tenant failure must not leave or reuse another tenant's GUC. `sync_post_metrics_hourly` already enumerates Organization but is missing the per-tenant transaction; the other eight currently scan tenant tables globally.

## Public and signed entry audit

| Entry | Current tenant locator | RLS consequence |
|---|---|---|
| `GET /r/<code>` tracking redirect | Queries tenant `ShortLink` globally by unique public code, then records `ClickEvent` | **Blocking locator:** after RLS the code lookup cannot occur on a tenant table without context. RLS-2C needs a minimal non-secret control-plane locator or a signed tenant-bearing code, then a tenant transaction and consistency recheck. |
| Lead visit webhook | Configured shared-secret header; queries `DiscoveryCandidate` globally by supplied `lead_id` | **Blocking locator:** candidate ID alone cannot establish RLS context. Carry/derive a trusted organization locator, set tenant, then re-read candidate. |
| Inbound RFQ webhook | HMAC; resolves optional `lead_id` through `DiscoveryCandidate`, otherwise `LEAD_WEBSITE_ORGANIZATION_SLUG` through control-plane Organization | Slug fallback is a viable control-plane locator. The lead-ID path is blocking and must not query Candidate before context. Re-read all referenced tenant objects inside the selected tenant. |
| Platform OAuth callback | Authenticated user plus `CanManageCredentials` active Membership | Tenant is already server-derived before platform/attempt queries; no public locator is needed. |

No email-provider or social-provider webhook endpoint was found at this baseline. Buffer operations are authenticated admin APIs and background reconciliation tasks, not inbound provider webhooks.

## Management command audit

| Command | Current access | Required operating mode |
|---|---|---|
| `seed_initial_organization` | Creates auth/control-plane Organization, Role, Membership | Bootstrap owner/admin workflow; it runs before a tenant exists. |
| `seed_phase_a` | Crosses control plane, global dictionaries/SYSTEM Knowledge, and one E2E tenant | E2E-only owner workflow; never a normal runtime command. |
| `seed_gear_ontology` | Writes SYSTEM Knowledge and already checks owner/bypass | Owner-only SYSTEM seed; remains outside tenant runtime. |
| `seed_platforms` | Writes global Platform/Capability dictionary | Owner/release seed; runtime must receive read-only context-gated access later. |
| `audit_duplicate_publish_tasks` | Cross-tenant PublishTask audit with no organization argument | Currently requires owner visibility; replace with control-plane organization enumeration and per-tenant read-only audit before RLS-2B. |
| `reclaim_orphan_buffer_credentials` | Cross-tenant credential scan/write | High-risk; must enumerate organizations then process each under `tenant_atomic` in RLS-2A. |
| `rotate_social_oauth_keys` | Optional organization filter, otherwise cross-tenant credential rotation; never sets GUC | Require explicit organization or per-tenant coordinator and enter `tenant_atomic` before the first credential query in RLS-2A. |
| `audit_rls_coverage` | Apps-registry metadata only | Safe under runtime or CI; no database row access and no owner requirement. |

## Blocking findings and next phases

All 96 tables have a reliable manifest classification; there is no table-classification blocker and no policy is guessed here. Runtime tenant location is not yet reliable for these entry families:

- `job_id`, `task_id`, `item_id`, and similar Celery payloads that identify only a tenant row;
- public Tracking short codes;
- public lead visit candidate IDs and RFQ lead IDs;
- eight cross-tenant Beat scans;
- Buffer admin permission, which resolves Membership but omits `set_local_tenant`.

RLS-2A must land Catalog, Assets, Platforms, Audit, AI, Jobs, their global-context dictionaries, Buffer permission, and job/credential task context together. RLS-2B must land Campaigns, Content, Publishing, and Buffer reconciliation/publish workers. RLS-2C must land Growth, Tracking, public redirect/RFQ/visit tenant location, per-organization Beat coordinators, `identity_phaseae2eownership`, and the final assertion that every non-exempt manifest entry has an enabled/forced policy.

This inventory does not enable policies, grant privileges, change task parameters, or change runtime behavior.
