# Database tenant isolation RLS-1

## Database roles

| Capability | `sinofgear_owner` | `sinofgear_app` |
| --- | --- | --- |
| Intended use | schema migrations, policies, privileged SYSTEM seeds | Web, Celery, ordinary management commands |
| Login | yes; credential supplied by deployment secret store | yes; credential supplied by deployment secret store |
| Inherit | no | no |
| Bypass RLS | yes | no |
| Owns application objects | yes in production | never |
| DDL | yes | no |
| Application DML | migration/repair only | granted on application tables and sequences |
| May `SET ROLE sinofgear_owner` | n/a | no membership; deployment verification must prove failure |

`infrastructure/postgres/bootstrap_rls_roles.sql` is idempotent and contains no password. Run it as a database administrator. It transfers existing tables, partitions, sequences, and the public schema to the migration owner, then establishes runtime and default privileges. Existing development credentials may remain the owner, but production Web and Celery processes must use the separate runtime role.

## Knowledge table ownership

RLS-1 covers every Knowledge tenant table. PostgreSQL enables and forces RLS on each covered table.

### A. Direct organization tables

- `knowledge_companyknowledgeprofile`
- `knowledge_companyfact`
- `knowledge_icpprofile`
- `knowledge_websitepage`
- `knowledge_knowledgecontextsnapshot`

Each has one `FOR ALL` policy requiring `organization_id = app_current_organization_id()` for both `USING` and `WITH CHECK`.

### B. SYSTEM and organization mixed tables

- `knowledge_knowledgeconcept`: shared reads require `scope = SYSTEM` and a null organization.
- `knowledge_knowledgeevidence`
- `knowledge_knowledgealias`
- `knowledge_knowledgerelation`

Each has separate SELECT, INSERT, UPDATE, and DELETE policies. A tenant may read its own rows and explicit null-organization SYSTEM rows. Only current-organization rows satisfy write policies, so runtime cannot create, update, or delete SYSTEM rows.

### C. Parent-derived association tables

- `knowledge_companyfactevidence`
- `knowledge_icpproductlink`
- `knowledge_websitepageproductlink`
- `knowledge_websitepageconceptlink`
- `knowledge_knowledgeconcept_evidence`
- `knowledge_knowledgerelation_evidence`

Policies use indexed foreign-key/primary-key lookups to validate the owning Knowledge parent. Product links also validate `catalog_product.organization_id`; concept/evidence links validate that referenced mixed-scope rows are visible. Write policies require an organization-owned parent and never permit a SYSTEM parent.

### D. Global control table

- `knowledge_knowledgegraphlock` is a single global serialization lock and intentionally has no tenant policy.

Policy names are stable: `rls_<table-without-knowledge-prefix>_<operation>`. Migration reversal drops every policy, disables FORCE and RLS on the covered tables, and removes `app_current_organization_id()`.

## Tenant context entry points

- Django config enables `ATOMIC_REQUESTS`. After authentication, `HasOrganizationPermission` resolves Active Membership from the Identity control plane and calls `set_local_tenant(request.organization.id)`. Client headers, query parameters, and bodies are not read for this purpose.
- `tenant_atomic(UUID)` is the only service/task transaction entry. It issues PostgreSQL `set_config('app.current_organization_id', ..., true)`, rejects non-native UUIDs and nested tenant changes, and always resets its in-process guard. PostgreSQL clears the GUC on commit or rollback.
- `KnowledgeContextBuilder` and Company Profile, Company Fact, ICP, Website Page review/revision services enter `tenant_atomic` before tenant queries. Their organization comes from the already supplied/locked domain boundary, never from an untrusted request field.
- Knowledge has no Celery task in RLS-1. Future Knowledge tasks must accept a trusted native organization UUID and enter `tenant_atomic` before their first Knowledge query.
- `seed_gear_ontology` is a privileged SYSTEM seed, not an ordinary tenant command. Run it only with the owner role. Ordinary runtime commands must use the runtime connection and either require an explicit organization UUID or enumerate Identity organizations first and open one independent `tenant_atomic` per organization.

Identity `Organization`, `Membership`, and `Role` remain control-plane tables without RLS so Active Membership can be resolved before tenant context exists.

## HTTP audit

All views in `apps.knowledge.views` use a `HasOrganizationPermission` subclass. Catalog endpoints that read `KnowledgeConcept` use product organization permissions, also subclasses of `HasOrganizationPermission`. No direct A1/A2/A3 Knowledge endpoint lacks the membership-derived context. Legacy Growth `CompanyFactListView` and `CompanyFactVerifyView` operate on `growth.FieldProvenance`, not `knowledge.CompanyFact`, and are outside this migration.

The broader audit found these non-`HasOrganizationPermission` tenant entry points; RLS-1 intentionally does not change their business logic:

- Four Buffer administration views use `CanAdministerBuffer`, which independently resolves Active Membership but does not install database tenant context. Buffer/Platforms is deferred to RLS-2.
- Growth `LeadVisitView` and `InboundRfqView` are signed public webhooks. They resolve tenant data from a lead/server configuration after signature verification and need a dedicated trusted tenant-context boundary before Growth RLS.
- Tracking `PublicRedirectView` resolves a tenant short link from a public code before a tenant is known. Tracking RLS needs a narrowly scoped public lookup design rather than a client-provided organization.
- Identity login/current-user endpoints operate on the control plane and correctly remain outside tenant RLS.

## SQLite compatibility

SQLite keeps an explicit transaction/context compatibility path so local previews and existing focused tests can run. `set_local_tenant` is a no-op only after verifying an active transaction, and nested tenant switching is still rejected. SQLite does not have RLS and is never an isolation acceptance environment.

## PostgreSQL acceptance settings

Run `apps/knowledge/tests/test_postgres_rls.py` with `DJANGO_SETTINGS_MODULE=config.postgres_rls_test_settings` and secret-provided `RLS_TEST_OWNER_DSN`, `RLS_TEST_RUNTIME_DSN`, and a pre-created disposable `RLS_TEST_DATABASE_NAME`. Optional role-name variables default to `sinofgear_owner` and `sinofgear_app`. The owner applies migrations and fixtures; every isolation assertion and Builder run switches to the real runtime login. Under ordinary SQLite test settings the module is explicitly skipped, never counted as RLS acceptance.

## Safe deployment

1. Stop Web, Celery workers, and Celery beat.
2. As a database administrator, create/configure `sinofgear_owner` and `sinofgear_app`, provision their passwords outside source control, ensure application objects are owned by the migration owner, and run `bootstrap_rls_roles.sql` in the target database.
3. Connect as `sinofgear_owner`, apply Django migrations including `knowledge.0007`, then rerun `bootstrap_rls_roles.sql` so the function EXECUTE grant is narrowed to runtime.
4. Change Web, worker, and beat `DATABASE_URL` secrets to `sinofgear_app`. Keep migration jobs on the owner URL.
5. Start processes and run the PostgreSQL cross-tenant suite. Verify current role is `NOINHERIT/NOBYPASSRLS`, `SET ROLE sinofgear_owner` fails, RLS cannot be disabled, missing context returns no Knowledge rows, and tenant A cannot read or write tenant B.
6. If verification fails, stop application processes before rollback. Restore the owner runtime URL only as a temporary recovery measure, reverse `knowledge.0007`, diagnose grants/context entry, and do not claim RLS active. Reapply the migration and runtime role only after the cross-tenant suite passes.

## Deferred to RLS-2

Identity control-plane tables are intentionally deferred. Tenant tables outside Knowledge are also deferred: Platforms (7), Audit (2), Catalog (2), Assets (3), Campaigns (7), Jobs (1), AI (2), Content (4), Publishing (5), Tracking (3), and Growth (33). Their child/association tables without direct `organization_id` require a separate parent-ownership inventory before RLS-2 policies are written.
