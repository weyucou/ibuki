# Pillar 2 — MCP Server + Tenant Auth

Locked design for the multi-tenant MCP service that fronts ibuki. Sourced from the architecture re-scope on 2026-05-20 (see [issue #8](https://github.com/weyucou/ibuki/issues/8)).

## Status

| Item | State |
|---|---|
| [DECISION A — Postgres + Django ORM](https://github.com/weyucou/ibuki/issues/8#issuecomment-4495898016) | locked |
| [DECISION B — 3-repo split](https://github.com/weyucou/ibuki/issues/8#issuecomment-4495898161) | locked |
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

- `Tenant(github_org [unique], display_name, versioning_scheme, status, created_at)`
- `Project(tenant [FK], name, github_repo_url [nullable], created_at)` — unique `(tenant, name)`
- `TenantMembership(user [FK to AUTH_USER_MODEL], tenant [FK], role, created_at)`

`auth_tokens/models.py`

- `Token(user [FK], tenant [FK], token_hash [unique SHA-256 hex], label, role, created_at, expires_at, revoked_at)`

Pillar 1 spec model (`specs/`), pillar 3 proposal model (`proposals/`), and pillar 4 release model (`releases/`) live in their own apps and are only stubbed by this pillar.

## Tenant isolation chokepoint

1. Django middleware `tenants.middleware.TenantContextMiddleware` parses `Authorization: Bearer …`, looks up `Token` by `sha256(pepper || token)` (single indexed ORM call), validates `revoked_at` / `expires_at`, binds `request.tenant`, `request.user`, `request.token_role` and `structlog.contextvars`.
2. Every tenant-scoped model uses a `TenantScopedManager` whose default queryset is filtered by `request.tenant`. Bypass requires explicit `Model.objects.unscoped()` (admin-only).
3. MCP tools read `tenants.utils.current_tenant()` (contextvar) — **no MCP tool accepts a tenant parameter**.
4. Defence in depth: `Spec.save()` raises `CrossTenantError` if `self.project.tenant_id != current_tenant().id`.

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
  "tool": "ibuki.submit",
  "caller_identity": "tok_2k7xa…",
  "latency_ms": 142,
  "outcome": "ok"
}
```

Failures emit `level=warning|error` with `outcome=auth_failed|validation_failed|internal_error` and an `error_class`. The structlog scrubber from [Python Guidelines → Logging](https://github.com/weyucou/sops/blob/main/guidelines/python-guidelines.md#logging) redacts `token`, `secret`, `api_key`, `authorization` as a safety net — the primary defence is never passing the raw token into `bind_contextvars` in the first place.

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

## Out of scope (v1)

- Public availability (deployment is for `weyucou` + `monkut` orgs only)
- Federation / cross-instance sync
- REST API (deferred to v2 per [#6](https://github.com/weyucou/ibuki/issues/6))
- Full implementation of `submit` / `get_spec` / `check` / `lock` / `cut_release` — pillar 2 ships **stubs** that exercise the auth/dispatch/logging path; behaviour belongs to pillars 3/4/5/6
- Token rotation UI, audit-log query API, rate limiting

## Deployment target

AWS account `610714125210`, region `us-west-2` (per [`AWS_ACCESS.md`](https://github.com/weyucou/ellen-core/blob/main/AWS_ACCESS.md)). Deploy procedure documented in `weyucou/ibuki-infra` once that repo exists.
