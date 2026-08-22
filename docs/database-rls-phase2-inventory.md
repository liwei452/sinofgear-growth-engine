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

These are shared prompt/platform dictionaries. `ai_promptversion` is restricted to global system prompt templates: tenant-specific company, product, customer, and other business content is forbidden there and the manifest therefore marks `contains_customer_content=False`. Runtime needs these dictionaries, but a runtime connection with no tenant context must not enumerate them. RLS-2A should allow SELECT only when `app_current_organization_id()` is non-null and should keep runtime writes denied. Owner-managed seed/release workflows remain separate.

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
| Buffer admin views | `platforms.CanAdministerBuffer` reads Membership/Role, sets `request.membership` and `request.organization`, then calls `set_local_tenant(membership.organization_id)` | Ready for RLS-2A: the tenant GUC is established before the first Platform/ProviderConnection/SocialAccount view query while the administrator and two-permission checks remain unchanged. |
| Platform OAuth callback | `CanManageCredentials` first establishes tenant; `_platform_or_404` then reads global Platform | Safe ordering, but Platform becomes context-gated in RLS-2A. |
| Knowledge APIs | `CanRead/Create/Review/DeprecateKnowledge` | Covered by HTTP tenant transaction and RLS-1.1 lazy-query contract. |
| Health/OpenAPI schema | No business ORM required for health; schema introspects code | Global infrastructure, not tenant data. |

No other non-test permission class assigns `request.organization`; the former Buffer exception is now aligned with the standard transaction-local tenant boundary.

## Celery task audit

RLS-2A.1 adds `apps.common.tenant_tasks` as the explicit worker boundary. Object tasks accept a UUID-string `organization_id` first, validate it, enter `tenant_atomic`, and re-read the target with both RLS context and an explicit organization predicate. Scanners materialize stable control-plane Organization IDs and process one independent tenant transaction at a time.

| Task | Current arguments | Tenant execution |
|---|---|---|
| `apps.jobs.tasks.execute_ai_job` | `organization_id`, `job_id`, `prompt_version_id` | Explicit tenant object re-read before orchestration. |
| `apps.jobs.tasks.refresh_social_credentials` | none | Coordinator; global total limit 100. |
| `apps.jobs.tasks.reap_stale_jobs` | none | Coordinator; each stale query is organization-filtered. |
| `apps.assets.tasks.run_asset_understanding` | `organization_id`, `job_id` | Explicit tenant Job re-read before understanding. |
| `apps.content.tasks.generate_master_content_job` | `organization_id`, `job_id`, `prompt_version_id` | Explicit tenant Job re-read before orchestration. |
| `apps.content.tasks.generate_platform_variants_job` | `organization_id`, `job_id` | Explicit tenant Job re-read before claim. |
| `apps.content.tasks.generate_content_recommendations_job` | `organization_id`, `job_id`, `prompt_version_id` | Explicit tenant recommendation re-read before generation. |
| `apps.growth.tasks.scan_due_discovery_profiles` | `limit` | Coordinator; supplied limit remains global. |
| `apps.growth.tasks.scan_due_maps_configs` | `limit` | Coordinator; supplied limit remains global. |
| `apps.growth.tasks.run_proactive_acquisition_task` | `organization_id`, `candidate_id`, approvals | Explicit tenant Candidate re-read before execution. |
| `apps.growth.tasks.run_due_proactive_acquisition` | `limit` | Coordinator; supplied limit remains global. |
| `apps.growth.tasks.execute_growth_publish_item` | `organization_id`, `item_id` | Explicit tenant item re-read before execution. |
| `apps.growth.tasks.sync_growth_publish_item_from_task` | `organization_id`, `task_id` | Organization-filtered Growth and Publishing lookups. |
| `apps.growth.tasks.reconcile_delegated_publish_items` | `limit` | Coordinator; supplied limit remains global. |
| `apps.publishing.tasks.run_publish_task` | `organization_id`, `task_id` | Explicit tenant task re-read before execution. |
| `apps.publishing.tasks.queue_due_publish_tasks` | `limit` | Coordinator; supplied limit remains global. |
| `apps.publishing.tasks.sync_post_metrics_hourly` | none | Coordinator; one organization per transaction. |
| `apps.publishing.tasks.reap_stale_publish_tasks_task` | none | Coordinator; each stale query is organization-filtered. |
| `apps.publishing.tasks.reconcile_buffer_publish_task_job` | `organization_id`, `task_id` | Explicit tenant task re-read before reconciliation. |
| `apps.publishing.tasks.reconcile_buffer_publish_tasks` | `limit` | Coordinator; supplied limit remains global and dispatch includes organization. |

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

All nine Beat entries now call a small coordinator that fully materializes only control-plane Organization IDs in stable order, then runs one bounded `tenant_atomic(organization.id)` unit per organization. The same pattern also covers manually invoked `refresh_social_credentials`. It does not use an owner/bypass connection, and an exception closes the current transaction before it can reach another tenant. Bounded scanners retain one global total limit rather than multiplying the limit by the organization count.

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
| `seed_platforms` | Writes global Platform/Capability dictionary | Owner/release seed; PostgreSQL now rejects a non-owner/non-bypass connection before mutation. |
| `audit_duplicate_publish_tasks` | Cross-tenant PublishTask audit with no organization argument | Currently requires owner visibility; replace with control-plane organization enumeration and per-tenant read-only audit before RLS-2B. |
| `reclaim_orphan_buffer_credentials` | Optional control-plane organization resolution, otherwise stable Organization enumeration | Each organization is processed in an independent tenant transaction with organization-filtered candidate and reference rechecks. |
| `rotate_social_oauth_keys` | Optional control-plane organization resolution, otherwise stable Organization enumeration | Dry-run counts and bounded rotation batches execute independently per tenant; output contains counts only. |
| `audit_rls_coverage` | Apps-registry metadata by default; `--database [alias]` inspects PostgreSQL catalogs | Default mode is safe anywhere. Database mode verifies all RLS-1/RLS-2A Policy names, PUBLIC role scope, commands, normalized `qual`/`with_check`, forced RLS, helper execution, and owner/runtime separation without reading business rows. |

## Blocking findings and next phases

All 96 tables have a reliable manifest classification; there is no table-classification blocker and no policy is guessed here. RLS-2A.1 removes object-ID-only Celery payloads, cross-tenant scanner transactions, the Buffer permission gap, and runtime credential-command scans. Runtime tenant location remains unresolved only for these later-phase public entry families:

- public Tracking short codes;
- public lead visit candidate IDs and RFQ lead IDs;

RLS-2A can now land Catalog, Assets, Platforms, Audit, AI, Jobs, and their global-context dictionaries without a worker or credential-command context blocker. RLS-2B must still land Campaigns, Content, and Publishing policies; their task entry points are already context-ready. RLS-2C must land Growth, Tracking, public redirect/RFQ/visit tenant location, `identity_phaseae2eownership`, and the final assertion that every non-exempt manifest entry has an enabled/forced policy.

## Celery signature deployment gate

Old queued messages do not contain the new required `organization_id` argument and must fail rather than fall back to an unsafe object-ID lookup. Deploy in this order:

1. Stop Celery Beat and stop all new task dispatch.
2. Wait for old-format work to complete or safely clear it using the operator's queue procedure; this repository does not automate queue deletion.
3. Deploy the code with the new explicit task signatures.
4. Restart workers, then restart Beat.
5. Confirm newly enqueued object-task payloads contain the server-derived UUID-string `organization_id` as their first argument.
6. Only after that verification, deploy the RLS-2A Policy migrations below.

## RLS-2A Policy deployment

The owner applies these migrations after `knowledge/0008_harden_knowledge_rls_context` and after the Asset Prompt Catalog seed:

1. `ai/0007_asset_understanding_prompt_catalog`
2. `ai/0008_enable_ai_tenant_rls`
3. `assets/0004_enable_assets_tenant_rls`
4. `audit/0004_enable_audit_tenant_rls`
5. `catalog/0004_enable_catalog_tenant_rls`
6. `jobs/0006_enable_jobs_tenant_rls`
7. `platforms/0012_enable_platforms_tenant_rls`

The 17 direct tables use one `FOR ALL` Policy with identical `USING` and `WITH CHECK` expressions: `organization_id = app_current_organization_id()`. `jobs_jobattempt` has separate SELECT, INSERT, UPDATE, and DELETE Policies, each derived through an `EXISTS` check on `jobs_job.organization_id`. The three global-context tables have only a SELECT Policy with `app_current_organization_id() IS NOT NULL`; runtime INSERT, UPDATE, and DELETE therefore remain denied.

Production rollout requires a maintenance window because `ALTER TABLE` takes database locks:

1. Stop Beat and new task dispatch, then drain or safely clear old-signature messages.
2. Stop Web and workers.
3. As the DBA/owner, run `infrastructure/postgres/bootstrap_rls_roles.sql`.
4. Run migrations with the owner connection.
5. Run the bootstrap script again so runtime receives grants on new application objects and the explicit `django_migrations` and frozen-Snapshot revokes are reapplied after the broad grant.
6. Configure Web and Celery with the `sinofgear_app` runtime connection, never the owner URL.
7. Start workers, then Beat, then Web.
8. Run `python manage.py audit_rls_coverage --database` and the PostgreSQL runtime-role suite. The gate must include migration-recorder denial, Snapshot UPDATE/DELETE denial, exact RLS-1/RLS-2A Policy contracts, and cross-tenant checks for AI Job, Asset/Catalog, Platform/Buffer administration, and Job/JobAttempt.

The Asset Prompt Catalog data migration performs an owner preflight before reading or writing Prompt rows. Running migrations with `sinofgear_app` therefore fails before any Prompt catalog mutation, and runtime cannot record the migration because its `django_migrations` write privileges are revoked. Web/Celery must remain stopped until the post-migration bootstrap and PostgreSQL gate both succeed.

Rollback also requires stopping Web, workers, and Beat. The owner reverses the six RLS migrations to their immediately preceding leaves. Reverse operations drop only the Policies owned by these migrations, then set `NO FORCE ROW LEVEL SECURITY` and `DISABLE ROW LEVEL SECURITY` on the 21 Phase 2A tables. They do not delete tenant data, the seeded Prompt, or Knowledge's `app_current_organization_id()` helper. Recheck roles and connection URLs before restoring services.
