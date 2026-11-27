# Pillar 2 — MCP Server + Tenant Auth

Locked design for the multi-tenant MCP service that fronts ibuki. Sourced from the architecture re-scope on 2026-05-20 (see [issue #8](https://github.com/weyucou/ibuki/issues/8)). [Issue #24](https://github.com/weyucou/ibuki/issues/24) extends it with tenant → project scoping, grounded against `weyucou/ibuki-backend@main` (`ca48e0d`).

## Status

| Item | State |
|---|---|
| [DECISION A — Postgres + Django ORM](https://github.com/weyucou/ibuki/issues/8#issuecomment-4495898016) | locked |
| [DECISION B — 3-repo split](https://github.com/weyucou/ibuki/issues/8#issuecomment-4495898161) | locked |
| Tenant → project scoping: [`Project` model](#project-model), [project selection](#project-selection), [migration path](#migration-path) | locked — [#24](https://github.com/weyucou/ibuki/issues/24) |
| MCP hosting shape (ASGI-mount vs separate FastMCP process) | deferred — `needs:decision` before backend child #3 |
| Empty repos `weyucou/ibuki-backend` and `weyucou/ibuki-infra` | tracked under [#12](https://github.com/weyucou/ibuki/issues/12) — blocks all child issues below |

## Repo split

| Repo | Purpose | Scaffold source |
|---|---|---|
| `weyucou/ibuki` (this repo) | Meta / spec / project board [#12](https://github.com/orgs/weyucou/projects/12) | — |
| `weyucou/ibuki-backend` | Django 5.2 LTS + DRF + MCP server | `weyucou/cookiecutter-django52lts-uv` (to be created — see #12) |
| `weyucou/ibuki-infra` | CloudFormation: RDS + ECR + Fargate + ALB | `weyucou/cookiecutter-aws-infra` (to be created — see #12) |

## Architecture decisions

| Concern | Decision | Notes |
|---|---|---|
| Application framework | Django 5.2 LTS + DRF | Mature ORM/migrations/admin; LTS for stability |
| MCP transport | Streamable HTTP via official `mcp` Python SDK | Required for hosted/remote (spec ≥ 2025-03-26) |
| MCP hosting shape | deferred | ASGI-mount inside Django **or** separate FastMCP process |
| ASGI server | uvicorn behind Django ASGI | Required if ASGI-mount is chosen |
| Auth | Bearer token (`Authorization: Bearer ibk_<32B base64url>`) | Django middleware resolves token → user + tenant |
| Token storage | SHA-256 hash (peppered) in `auth_tokens.Token` | Raw token shown once at issuance |
| Data store | Postgres (RDS `db.t4g.micro` dev, multi-AZ for prod) | All entities via Django ORM |
| Hosting | AWS Fargate (ECS) behind ALB | Long-lived HTTP/SSE fits Fargate; Lambda's 15-min ceiling rejected |
| Secrets | AWS Secrets Manager (`TOKEN_PEPPER`, `DJANGO_SECRET_KEY`, `DATABASE_URL`, LLM keys) | Per [Secret Management Policy](https://github.com/weyucou/sops/blob/main/policies/secret-management.md) |
| Logging | `structlog` → JSON to stdout + scrubber | Per [Logging Standard](https://github.com/weyucou/sops/blob/main/standards/logging.md) |
| IaC | CloudFormation in `weyucou/ibuki-infra` | Scaffolded from `cookiecutter-aws-infra` |
| Test DB | pytest-django + `postgres:16-alpine` in CI; docker-compose locally | Replaces moto-only |
| Admin surface | Django admin for Tenant/Project/User/Token CRUD; `manage.py ibuki_bootstrap` for the first tenant + admin token | Replaces the original hand-rolled `ibuki-admin` CLI for most ops |

## Data model (Django ORM, abridged)

`tenants/models.py`

- `Tenant(github_org [unique], display_name, status, created_at)`
- `Project(tenant [FK], name, github_repo_url, versioning_scheme, created_at)` — unique `(tenant, name)`; see [Project model](#project-model)
- `TenantMembership(user [FK to AUTH_USER_MODEL], tenant [FK], role, created_at)`

`auth_tokens/models.py`

- `Token(user [FK], tenant [FK], token_hash [unique SHA-256 hex], label, role, created_at, expires_at, revoked_at)`

Pillar 1 spec model (`specs/`), pillar 3 proposal model (`proposals/`), and pillar 4 release model (`releases/`) live in their own apps and are only stubbed by this pillar. Each of their rows belongs to a project; see [Uniqueness keys](#uniqueness-keys).

### Project model

A project is one product or repository within a tenant (README → Architecture, "Hierarchy"). Specs, proposals and releases belong to a project, and tasks (pillar 7) will too. `tenants/models.py`:

```python
class Project(models.Model):
    tenant = FK(Tenant, on_delete=CASCADE, related_name="projects")
    name = CharField(max_length=100, validators=[RegexValidator(r"^[A-Za-z0-9._-]{1,100}$")])  # = schema `project`
    github_repo_url = URLField(blank=True, default="")
    versioning_scheme = CharField(max_length=16, choices=VersioningScheme.choices, default=VersioningScheme.SEMVER)  # pillar 4; added by ibuki-backend#50
    created_at = DateTimeField(auto_now_add=True)
    # UniqueConstraint(tenant, name); save() case-folds name
```

- `name` takes the proposal schema's `project` pattern, which is the GitHub repo name. `save()` case-folds it, as `AllowedRepository` does for `repo`, so `Ibuki` and `ibuki` cannot become two projects. Lookups fold the requested name the same way.
- Projects are created in Django admin, like tenants and `AllowedRepository` rows. v1 has no MCP tool that creates a project.
- `github_repo_url` is an informational link. It does **not** grant `ibuki.check` access: `AllowedRepository` stays the deny-by-default allow-list.
- `versioning_scheme` is the [pillar 4](04-release-management.md#architecture-decisions) release scheme. It lives on `Project` only, with no tenant default and no inheritance, so a scheme is set in one place.

### Uniqueness keys

| Entity | Was | Now |
|---|---|---|
| `Project` | — | `(tenant, name)` |
| `Spec` | `unique_tenant_spec_name (tenant, name)` | `unique_project_spec_name (tenant, project, name)` |
| `Proposal` `feature_id` claim (rule engine; no DB constraint) | tenant | `(tenant, project)`. `duplicate_feature_id`, the supersedes walk (both CTE terms add `project_id`) and scope-overlap conflicts all filter on project. Scope entries are repo-relative paths, so an overlap only means something within one repo |
| `Release` (pillar 4) | `(tenant, version)` | `(project, version)` |
| `ProposalResponse` idempotency | `(tenant, client_request_id)` | unchanged: the key identifies a request, not data |
| `requirements[].id` | — | resolved within the project. Several specs in one project may cite the same requirement; that is the traceability chain, so there is no DB constraint. The schema's within-payload `uniqueItems` stays the only uniqueness check |

`Spec` and `Proposal` keep their `tenant` FK: every existing query filters on it, and it leads the new `(tenant, project, name)` key. Each gains `project = FK(Project, on_delete=RESTRICT)`. `RESTRICT` blocks deleting a project that still has specs or proposals, yet lets a tenant delete cascade through, because the same cascade deletes the rows it guards; `PROTECT` would block that cascade. `Release.project` is `PROTECT` on purpose: a cut release is retained, so its project cannot be deleted under it ([pillar 4 → Immutability and retention](04-release-management.md#immutability-and-retention)).

## Project selection

Tenant stays token-derived, and no tool accepts a `tenant` argument. A v1 token covers every project in its tenant, so a call that needs a project names it:

- A call that addresses data **by name**, or **lists** it, names its project explicitly.
- A call that addresses a row **by id** takes no `project`. The row already belongs to a project, so a second argument would only add a mismatch case.

| Tool | Project source |
|---|---|
| `ibuki.submit` | `proposal.project`. The schema already requires it ([`docs/schema.md`](../schema.md)), so the payload is the explicit argument |
| `ibuki.respond`, `ibuki.lock`, `ibuki.get_release` | the `proposal_id` / `release_id` row |
| `ibuki.get_spec` | by `spec_id`: the row. By `name`: requires `project` |
| `ibuki.list_escalated`, `ibuki.check`, `ibuki.cut_release`, `ibuki.list_releases` | required `project` argument |
| `ibuki.list_projects` (new, read-only) | none. Lists the tenant's projects so an agent can discover their names |

Every lookup is `Project.objects.get(tenant=current_tenant(), name=…)`, with the name case-folded. An unknown name and another tenant's project are the same miss: both return `project_not_found` (`PROJECT_NOT_FOUND` in the SCREAMING-valued `ReleaseErrorCode` and `CheckErrorCode`), so the response never confirms that a project exists.

`proposal.project` is the one payload field the server resolves; the payload's `tenant` field stays data being validated, never an input. `ibuki.submit` resolves the project before it writes anything, so a payload whose `project` does not resolve gets `project_not_found` and creates no row. A `respond(counter)` payload must name the proposal's own project. One that names another is refused with `project_mismatch` and the proposal stays where it was, so a stored payload always names its row's project.

## Tenant isolation chokepoint

1. Django middleware `tenants.middleware.TenantContextMiddleware` parses `Authorization: Bearer …`, looks up `Token` by `sha256(pepper || token)` (single indexed ORM call), validates `revoked_at` / `expires_at`, binds `request.tenant`, `request.user`, `request.token_role` and `structlog.contextvars`.
2. Every tenant-scoped model uses a `TenantScopedManager` whose default queryset is filtered by `request.tenant`. Bypass requires explicit `Model.objects.unscoped()` (admin-only).
3. MCP tools read `tenants.utils.current_tenant()` (contextvar) — **no MCP tool accepts a tenant parameter**. A project lookup runs inside that tenant filter ([Project selection](#project-selection)), so another tenant's project is not found rather than refused.
4. Defence in depth: `Spec.save()` and `Proposal.save()` raise `CrossTenantError` if `self.project.tenant_id != self.tenant_id`. The guard compares the row with itself, so it also holds in Django admin, where no request tenant is bound.

## Token lifecycle

- **Issuance** — `manage.py issue_token` (or Django admin): generate 32 random bytes → base64url → prefix `ibk_`; compute `sha256(pepper || token)`; write `Token` row; print raw token **once** to stdout, never logged.
- **Verification** — middleware hashes the bearer value and does a single indexed lookup; reject if missing, revoked, or expired.
- **Revocation** — set `revoked_at`; effective on next request (no caching in v1).

## Logging contract

Every tool invocation emits one INFO log with these fields per [Logging Standard](https://github.com/weyucou/sops/blob/main/standards/logging.md):

```json
{
  "timestamp": "2026-05-26T12:34:56Z",
  "level": "info",
  "logger": "ibuki.mcp.dispatch",
  "service": "ibuki",
  "environment": "dev",
  "event": "tool.invoked",
  "tenant_id": "weyucou",
  "project_id": 12,
  "tool": "ibuki.submit",
  "caller_identity": "tok_2k7xa…",
  "latency_ms": 142,
  "outcome": "ok"
}
```

`project_id` is the resolved `Project.pk`. A tool with a `project` argument resolves it before it emits `tool.invoked`, then binds `project_id` into the structlog contextvars, so `tool.invoked` and every later record carry it. A by-id tool binds it once it has loaded the row. `ibuki.list_projects`, and a call refused with `project_not_found`, carry none.

Failures emit `level=warning|error` with `outcome=auth_failed|validation_failed|internal_error` and an `error_class`. The structlog scrubber from [Python Guidelines → Logging](https://github.com/weyucou/sops/blob/main/guidelines/python-guidelines.md#logging) redacts `token`, `secret`, `api_key`, `authorization` as a safety net — the primary defence is never passing the raw token into `bind_contextvars` in the first place.

## Migration path

Rows that exist today are tenant-scoped. Each tenant gets a `default` project, and its rows are backfilled into it in the standard three Django steps: add a nullable FK, backfill it, make it non-null. The data step goes in its own migration file, because Postgres refuses an `ALTER TABLE` while the same transaction has pending trigger events. Migration numbers follow each app's head on `ibuki-backend@main` (`ca48e0d`).

1. `tenants/0006_project`: create `Project`.
2. `tenants/0007_backfill_default_project`: a `RunPython` step creates one `default` project per existing tenant. The reverse deletes any `default` project that nothing references.
3. `specs/0003` → `0005`: add a nullable `project`, backfill it to the tenant's `default` project, make it non-null, then swap `unique_tenant_spec_name` for `unique_project_spec_name`.
4. `proposals/0004` → `0006`: the same three steps. `Index(project, state)` replaces `proposals_tenant_state_idx`.
5. `releases`: the same three steps on top of [ibuki-backend#48](https://github.com/weyucou/ibuki-backend/issues/48)'s `0001_initial`. `(project, version)` and `Index(project, -cut_at)` replace the tenant-keyed constraint and index.

After the backfill, an admin renames `default` to the real repo name in Django admin. Rows reference the project by pk, so a rename moves no data. New tenants get no automatic default project.

The reverse migration restores the tenant-wide constraints. It fails when two projects in one tenant hold the same spec name, which is the correct outcome: a tenant-wide key cannot hold that data. No deployment exists yet ([ibuki-backend#14](https://github.com/weyucou/ibuki-backend/issues/14) is open), so in practice the backfill only runs against dev and test data.

## Module layout (`weyucou/ibuki-backend`)

```
src/ibuki_backend/
├── settings/{base,dev,prod}.py
├── urls.py
├── asgi.py                       # MCP mount happens here (or in a separate process)
├── tenants/                      # Tenant, Project, TenantMembership
├── auth_tokens/                  # Token + middleware
├── specs/                        # Spec model (pillar 1)
├── mcp/                          # MCP server module
│   ├── app.py                    # FastMCP app construction
│   ├── context.py                # request-scoped TenantContext (contextvar)
│   └── tools/
│       ├── submit.py             # stub → pillar 3
│       ├── get_spec.py           # stub → pillar 6
│       ├── check.py              # stub → pillar 5
│       ├── lock.py               # stub → pillar 4
│       └── cut_release.py        # stub → pillar 4
└── logging_config.py
tests/
├── conftest.py                   # pytest-django + factory_boy
├── tenants/
├── auth_tokens/
└── mcp/
    ├── test_tool_dispatch.py
    └── test_tenant_isolation.py
```

## Child issue split

The four child issues land once [#12](https://github.com/weyucou/ibuki/issues/12) unblocks the two new repos:

1. **ibuki-backend #1 — Bootstrap Django project & CI** (`complexity:simple`): scaffold from `cookiecutter-django52lts-uv`; gitleaks CI; `docker compose` for local Postgres; CONTRIBUTING.
2. **ibuki-backend #2 — Tenant + User + Token models** (`complexity:medium`): `tenants` + `auth_tokens` apps; `TenantScopedManager`; Django admin registrations; `manage.py ibuki_bootstrap`; property + integration tests.
3. **ibuki-backend #3 — MCP server skeleton with stub tools** (`complexity:medium`): FastMCP app, middleware wiring, all five tools returning `not_implemented`, full logging contract, **tenant-isolation integration test is the headline acceptance test**. Blocked on the MCP hosting sub-decision.
4. **ibuki-infra #1 — Postgres + Fargate deployment** (`complexity:medium`): `ibuki-stack.yaml` from `cookiecutter-aws-infra`; RDS + ECR + Fargate + ALB; ECR build/push GHA (cross-repo); deploy runbook; first dev deployment verified end-to-end with a real token.

Tenant → project scoping ([#24](https://github.com/weyucou/ibuki/issues/24)) adds four children in `weyucou/ibuki-backend` and re-scopes a fifth:

- **[ibuki-backend#51](https://github.com/weyucou/ibuki-backend/issues/51) — `Project` model, backfill, and `Spec`/`Proposal` FKs** (`complexity:medium`): the [Project model](#project-model) and its admin registration, the model side of [Uniqueness keys](#uniqueness-keys), the `CrossTenantError` guard, [Migration path](#migration-path) steps 1–4, and `resolve_project(tenant, name)`. `ibuki.submit` sets `Proposal.project` from the payload in the same change: it is the one path that writes rows today, so `main` stays green once the FK is non-null. No dependencies.
- **[ibuki-backend#52](https://github.com/weyucou/ibuki-backend/issues/52) — Project-scoped rules and MCP project selection** (`complexity:medium`): project-filtered uniqueness, supersedes and conflict rules, the `respond(counter)` project check, `project` on `get_spec` and `list_escalated`, `ibuki.list_projects`, and the `project_id` log binding. *Depends on #51.*
- **[ibuki-backend#53](https://github.com/weyucou/ibuki-backend/issues/53) — `ibuki.check` project scoping** (`complexity:simple`): `CheckRequest.project`, the spec load by `(project, name)`, and `project_id` in the cache key. *Depends on #51 and [#29](https://github.com/weyucou/ibuki-backend/issues/29).*
- **[ibuki-backend#54](https://github.com/weyucou/ibuki-backend/issues/54) — `Release.project`** (`complexity:simple`): pillar 4's project-scoped release model and [Migration path](#migration-path) step 5. The manifest's `project` field lands with the pillar 4 child that builds the manifest document. *Depends on #51 and [#48](https://github.com/weyucou/ibuki-backend/issues/48).*
- **[ibuki-backend#50](https://github.com/weyucou/ibuki-backend/issues/50)** is re-scoped from `Tenant.versioning_scheme` to `Project.versioning_scheme`. *Depends on #51 and #48.*

## Out of scope (v1)

- Public availability (deployment is for `weyucou` + `monkut` orgs only)
- Federation / cross-instance sync
- REST API (deferred to v2 per [#6](https://github.com/weyucou/ibuki/issues/6))
- Full implementation of `submit` / `get_spec` / `check` / `lock` / `cut_release` — pillar 2 ships **stubs** that exercise the auth/dispatch/logging path; behaviour belongs to pillars 3/4/5/6
- Token rotation UI, audit-log query API, rate limiting
- Per-project token scoping (a v1 token covers every project in its tenant) and an MCP tool that creates projects (Django admin only)

## Deployment target

AWS account `610714125210`, region `us-west-2` (per [`AWS_ACCESS.md`](https://github.com/weyucou/ellen-core/blob/main/AWS_ACCESS.md)). Deploy procedure documented in `weyucou/ibuki-infra` once that repo exists.
