# Pillar 4 — Release Management

Locked design for release cuts. A human or designated agent calls `ibuki.cut_release`, and every spec version locked since the previous cut is frozen into a single named, versioned, immutable manifest. The versioning scheme is per-tenant configurable (semver / date / sequential).

Pillar 4 also owns the **lock** step that produces those cut-eligible units: `ibuki.lock` turns an `accepted` proposal into a locked `specs.SpecVersion`.

Sourced from [issue #10](https://github.com/weyucou/ibuki/issues/10) and the 2026-05-20 architecture re-scope, then grounded against `weyucou/ibuki-backend@main` (`9ec13c7`) — `tenants/models.py`, `specs/models.py`, `proposals/models.py`, `proposals/states.py`, `mcp_server/{tools,context,auth}.py`, `conformance/schemas.py`, `pyproject.toml`, `.github/workflows/ci.yml`.

## Status

| Item | State |
|---|---|
| [DECISION A — Postgres (RDS) via Django ORM](https://github.com/weyucou/ibuki/issues/8#issuecomment-4495898016) | locked (shared with pillars 2/3) |
| [DECISION B — 3-repo split](https://github.com/weyucou/ibuki/issues/8#issuecomment-4495898161) | locked (shared with pillar 2) |
| Bundled unit is a locked `specs.SpecVersion` (not a `Proposal`) | locked — grounded, see [What grounding changed](#what-grounding-changed) |
| Tenant-only scoping (no `Project`) | locked — grounded |
| Scheme config is a `Tenant` field via Django admin (no MCP setter) | locked — grounded |
| `name=` override must match the tenant's scheme | locked by the issue's own acceptance criteria (`VERSION_MISMATCH`) |
| **DECISION 1 — where `ibuki.lock` gets the accepted content** | **open — blocks child 4 only.** Recommendation (a): [ibuki-backend#18](https://github.com/weyucou/ibuki-backend/issues/18) persists the accepted payload |
| DECISION 3 — date-scheme exhaustion past `-Z` | open — child 2's call. Recommendation: fail with `VERSION_EXHAUSTED` |
| Cut-window watermark (late-committing locks) | open — child 3, see [Open items](#open-items) |

Design (data model, manifest contract, versioning, concurrency, immutability) is **locked**. Children 1–3 are unblocked today; only child 4 waits on DECISION 1.

## What grounding changed

The 2026-05-20 plan targeted an `ibuki/release/` package in this repo with hand-written SQL and `(tenant, project)` scoping. Three facts in the shipped tree changed the design rather than just its file paths:

1. **There is no `Project` model.** `Spec` is unique on `(tenant, name)`, `Proposal` on `(tenant, feature_id)`. `project` is dropped from every signature, model and acceptance criterion.
2. **The cut-eligible unit is a locked `specs.SpecVersion`.** `ProposalState` has no `locked` member — its terminal accept state is `accepted`. `specs/models.py` ships `locked_at` and its module docstring names this issue as the consumer of `(tenant, name, version)`.
3. **The lock step is pillar-4 scope and is the critical path.** The `ibuki.lock` stub is labelled "(pillar 4)" in `mcp_server/tools.py`, and nothing in pillar 3 writes a `SpecVersion`. Without the lock step there is never anything to cut.

| Area | Was (2026-05-20) | Now (grounded) |
|---|---|---|
| Home | `ibuki/release/` in this repo | new Django app `backend/releases/` in `ibuki-backend`, per the `proposals` / `conformance` one-app-per-pillar precedent |
| Scoping | `(tenant, project)` | `tenant` only |
| Bundled unit | `proposals[]` locked since last cut | `items[]` — locked `specs.SpecVersion` rows |
| Storage | hand-written `CREATE TABLE` DDL | Django models + `makemigrations`; Postgres 17 in CI, `pytest-django` |
| Scheme config | `tenant_release_config` table + `ibuki.set_release_scheme` tool | `Tenant.versioning_scheme` field via Django admin, matching shipped `judge_model` / `check_token_budget` — **the tool is dropped** |
| Concurrency | `SERIALIZABLE` + retry | `select_for_update(nowait=True)` on the tenant row inside `transaction.atomic()` |
| Immutability | Postgres role grants, tested by asserting permission denied | application layer, mirroring shipped `ProposalEvent` and `SpecVersion`; grants stay deferred to [ibuki-backend#14](https://github.com/weyucou/ibuki-backend/issues/14) |
| Models | pydantic `frozen=True` as storage | Django models for storage; pydantic only for the MCP wire contract |

## What this pillar delivers

The twelve acceptance criteria in [issue #10](https://github.com/weyucou/ibuki/issues/10). In brief:

- `ibuki.lock` materialises a `specs.SpecVersion` from an `accepted` proposal and sets `locked_at` (one-way), making it cut-eligible.
- `ibuki.cut_release(name?)` bundles every spec version the calling tenant locked between the previous cut and now into one immutable manifest.
- The manifest carries `release_id`, `tenant`, `version`, `scheme`, `cut_at`, `cut_by`, `items[]` (ordered by `locked_at` ASC), `predecessor_release_id`, `manifest_hash`.
- Versioning is per-tenant: `semver`, `date`, or `sequential`. An omitted `name` auto-generates; a supplied `name` is validated against the scheme and a mismatch is rejected with `VERSION_MISMATCH`.
- A manifest is immutable once cut — no edits, no reorders, no late additions. Corrections happen via a new release.
- Nothing locked since the last cut → `EMPTY_RELEASE`. There are no empty releases.
- Two racing cuts for one tenant → exactly one succeeds; the loser gets `CONCURRENT_CUT`.
- Manifests are readable via `ibuki.get_release` and `ibuki.list_releases`.
- A spec version referenced by a cut release cannot be deleted.
- Every tool reads its tenant from `mcp_server.context.current_tenant()`; no release tool accepts a tenant argument.

## Architecture decisions

| Concern | Decision | Rationale |
|---|---|---|
| Module home | `backend/releases/` Django app in `weyucou/ibuki-backend` | One app per pillar, matching `proposals` and `conformance` |
| Public identifier | `Release.release_id` is a `UUIDField` generated in Python **before** insert; the integer pk stays internal for FKs | The manifest contains its own `release_id` and is hashed before the row is written — a DB-assigned id would force an UPDATE, which the append-only guard rejects. A UUID also keeps one tenant's cut volume from being inferred off a shared sequence |
| Manifest storage | `manifest_json` holds the hashed document verbatim, alongside `manifest_hash` | A stored manifest can always be re-hashed and compared; the hash is never recomputed from live rows |
| Scheme storage | `Tenant.versioning_scheme` (`TextChoices`), edited in Django admin | Matches shipped `judge_model` and `check_token_budget`; neither has an MCP setter |
| Scheme freezing | `Release.scheme` copies the tenant's scheme at cut time | A tenant that switches schemes must not retroactively re-describe past releases |
| Versioning functions | Pure `next_version(scheme, previous, now) -> str` / `validate_version(scheme, version, previous)` in `releases/versioning.py` | No ORM, so they test as `SimpleTestCase` and take `hypothesis` property tests |
| Concurrency | `Tenant.objects.select_for_update(nowait=True)` inside `transaction.atomic()` | Django does not manage isolation per transaction and raising it globally is invasive; `nowait` surfaces the race deterministically as a `DatabaseError` to translate into `CONCURRENT_CUT`. `UniqueConstraint(tenant, version)` is the backstop |
| Idempotency | None. `cut_release` is deliberately not client-retry-safe | Two cuts seconds apart yield one release and then `EMPTY_RELEASE`. The row lock, not an idempotency key, prevents double-counting |
| Immutability | Application layer: `save()` on an existing row, queryset `update()`, and `delete()` all raise `ReleaseImmutableError` | Mirrors the shipped `ProposalEvent` append-only and `SpecVersion` lock patterns |
| Retention | `ReleaseItem.spec_version` is `on_delete=PROTECT` | `Spec` → `SpecVersion` is CASCADE, so deleting a referenced `Spec` raises `ProtectedError` instead of orphaning the manifest. Closes the retention gap `specs/models.py` labels pillar-4 scope, with no change to the `specs` app |
| DB grants | Deferred to [ibuki-backend#14](https://github.com/weyucou/ibuki-backend/issues/14) | Same deferral `proposals/models.py` already documents for `ProposalEvent`; distinct DB roles do not exist yet to grant against |
| Wire contract | pydantic models in `releases/schemas.py`; `ReleaseErrorCode` is a `StrEnum` with SCREAMING values | Matches `conformance/schemas.py` and its `CheckErrorCode` |
| `cut_by` | Server-derived `token:<ApiToken.pk>`, bound by `mcp_server.context.current_token()` | Never client-supplied. Never the `token_hash` — that value verifies a bearer token, and the manifest is durable, readable content |
| Tool sync/async | ORM-touching MCP tools MUST be `async`; the transactional cut runs under `sync_to_async(..., thread_sensitive=True)` | FastMCP invokes sync tools in the event loop — a bare sync ORM call raises `SynchronousOnlyOperation`, as the existing `get_spec` docstring records |
| Absent release | `get_release` returns `{"found": false, "release": null}` | An absent record is a well-formed result, per the shipped `specs.loader.spec_payload` precedent |

## Data model

`backend/releases/models.py`

```python
class Release(models.Model):
    release_id = UUIDField(default=uuid4, editable=False, unique=True)   # public handle; in the manifest
    tenant = FK(Tenant, on_delete=CASCADE, related_name="releases")
    version = CharField(max_length=64)
    scheme = CharField(max_length=16, choices=VersioningScheme.choices)  # frozen at cut time
    cut_at = DateTimeField()                                             # explicit: it is manifest content
    cut_by = CharField(max_length=64)                                    # server-derived token identity
    predecessor = FK("self", null=True, on_delete=PROTECT, related_name="successors")
    manifest_hash = CharField(max_length=64)                             # sha256 hex
    manifest_json = JSONField()                                          # the hashed document, verbatim
    lock_watermark = DateTimeField(null=True)                            # max(item.locked_at); child 3 populates — see open item 3
    # UniqueConstraint(tenant, version); Index(tenant, -cut_at)

class ReleaseItem(models.Model):
    release = FK(Release, on_delete=PROTECT, related_name="items")
    spec_version = FK(SpecVersion, on_delete=PROTECT)   # PROTECT is the retention guarantee
    spec_name = SlugField(max_length=128)               # denormalised: the manifest must stay readable
    spec_version_number = PositiveIntegerField()
    locked_at = DateTimeField()
    content_hash = CharField(max_length=64)
    ordinal = PositiveIntegerField()
    # UniqueConstraint(release, spec_version)
```

`backend/tenants/models.py` gains one field, in migration `0004_tenant_versioning_scheme` (the app is at `0003_tenant_check_token_budget`):

```python
versioning_scheme = CharField(max_length=16, choices=VersioningScheme.choices, default=VersioningScheme.SEMVER)
```

`content_hash` is computed at cut time — neither `SpecVersion` nor `Proposal` stores a hash today. It is SHA-256 over the canonical JSON of `SpecVersion.content`.

The item fields are denormalised deliberately. A manifest is an artifact downstream consumers read years later; resolving `spec_name` through a live FK would let a rename rewrite history that is supposed to be frozen.

## The lock step — `ibuki.lock`

Given an `accepted` `proposals.Proposal` owned by the calling tenant:

```python
spec, _ = Spec.objects.get_or_create(tenant=current_tenant(), name=proposal.feature_id)
version = spec.add_version(content)   # content source is DECISION 1
version.lock()                        # sets locked_at; one-way
```

Both `Spec.add_version()` and `SpecVersion.lock()` ship today. `add_version()` wraps its read-then-insert in a transaction guarded by `unique_spec_version`, so two concurrent locks on one spec surface as an `IntegrityError` rather than silently reusing a version number.

Rejections, all structured:

| Condition | Code |
|---|---|
| Proposal in any state other than `accepted` | `PROPOSAL_NOT_ACCEPTED` |
| Proposal owned by another tenant | `TENANT_MISMATCH` |
| The proposal's version is already locked (`SpecLockedError`) | `ALREADY_LOCKED` |

**DECISION 1 gates the `content` argument.** `proposals.Proposal` persists `tenant`, `feature_id`, `supersedes`, `scope_in`, `scope_in_normalised`, `state`, `round` and timestamps — and **no payload**. The submitted payload flows through `rules.run_rules` and `judge.invoke_judge` in memory and is never stored, so an accepted proposal cannot currently be turned back into spec content. This is a gap in the pillar-3 → pillar-1 handoff, not a pillar-4 design choice.

## Versioning — `releases/versioning.py`

```python
class VersioningScheme(models.TextChoices):   # TextChoices: it backs a model field, per ProposalState
    SEMVER = "semver"
    DATE = "date"
    SEQUENTIAL = "sequential"
```

| Scheme | Auto-generated sequence | Notes |
|---|---|---|
| `semver` | `0.1.0`, `0.2.0`, `0.3.0`, … | Bumps **minor**. A major or patch bump requires an explicit `name=` |
| `date` | `2026-05-A`, `2026-05-B`, … `-Z` | Resets on each calendar month (UTC). The 27th cut in a month raises `VERSION_EXHAUSTED` (DECISION 3) |
| `sequential` | `release-1`, `release-2`, … | Monotonic |

`VersioningScheme` lives in `releases/versioning.py` and `tenants/models.py` imports it. That direction is safe: `versioning.py` imports nothing from either app, so it does not close a cycle against `releases/models.py` → `tenants.models`.

`next_version` and `validate_version` are pure functions of `(scheme, previous_version, now_utc)`. Property tests cover monotonicity (`next_version(prev) > prev` under each scheme's ordering) and round-trip (`validate_version(scheme, next_version(scheme, prev, now), prev)` never raises). `hypothesis` is already a dev dependency.

A supplied `name` must match the tenant's scheme — the issue's acceptance criteria mandate `VERSION_MISMATCH` on a mismatch. The scheme is the tenant's contract, and `list_releases` ordering assumes it.

## Manifest hashing — `releases/manifest.py`

`manifest_hash` is the SHA-256 hex of

```python
json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
```

where `document` is every manifest field **except** `manifest_hash`, with datetimes rendered as UTC ISO-8601 `Z`. `sort_keys=True` is what makes the hash independent of field order. The hashed document is stored verbatim in `manifest_json`, so verification is a re-hash of stored bytes rather than a re-derivation from live rows.

## `cut_release` flow — `releases/service.py`

1. `transaction.atomic()`, then `Tenant.objects.select_for_update(nowait=True).get(pk=tenant.pk)`. A concurrent cut fails fast with a `DatabaseError`, translated to `CONCURRENT_CUT`.
2. Load the tenant's `versioning_scheme` and its most recent `Release` — the predecessor.
3. Select the items:
   ```python
   SpecVersion.objects.select_related("spec").filter(
       spec__tenant=tenant,
       locked_at__isnull=False,
       locked_at__gt=predecessor.cut_at,   # omitted when there is no predecessor
   ).order_by("locked_at", "pk")
   ```
   `pk` is the tiebreaker — `locked_at` is not unique.

   **Provisional** — this lower bound is the known defect described in [open item 3](#open-items): a lock that stamps `locked_at` before a cut but commits after it is never bundled. Child 3 replaces `predecessor.cut_at` here with the stored `lock_watermark`; `cut_at` stays the honest wall-clock cut time in the manifest.
4. Empty → `EmptyReleaseError` (`EMPTY_RELEASE`).
5. Resolve the version: validate `name` against the scheme if supplied, else `next_version(...)`.
6. Generate `release_id` (UUID) and `cut_at`, build the manifest document, compute `manifest_hash`, then insert the `Release` and its `ReleaseItem` rows — one write each, no follow-up UPDATE.
7. Commit. `UniqueConstraint(tenant, version)` catches any surviving race as `VERSION_TAKEN`.

## Immutability and retention

Enforcement mirrors what already ships in `proposals` and `specs`:

| Path | Behaviour |
|---|---|
| `Release.save()` on an existing row | raises `ReleaseImmutableError` |
| `Release.objects.filter(...).update(...)` | raises `ReleaseImmutableError` |
| `Release.delete()` / queryset `delete()` | raises `ReleaseImmutableError` |
| `ReleaseItem` — same three paths | raises `ReleaseImmutableError` |
| `Spec.delete()` where a version is in a manifest | raises Django's `ProtectedError` via `ReleaseItem.spec_version` |
| `Release.delete()` where a successor points at it | raises `ProtectedError` via `predecessor` |

Raw SQL, `bulk_update()` and cascade deletes still bypass application-layer guards. The INSERT/SELECT-only DB grants that close those paths are owned by the deployment work ([ibuki-backend#14](https://github.com/weyucou/ibuki-backend/issues/14)) — the same deferral `proposals/models.py` documents for `ProposalEvent`.

## MCP surface

Four tools in the existing `backend/mcp_server/tools.py`, registered in `build_mcp()`. `lock` and `cut_release` replace today's `not_implemented` stubs; `get_release` and `list_releases` are new.

| Tool | Input | Output |
|---|---|---|
| `ibuki.lock` | `{ proposal_id }` | `{ spec_id, name, version, locked_at }` or structured error |
| `ibuki.cut_release` | `{ name? }` | `{ release: ReleaseManifest }` or structured error |
| `ibuki.get_release` | `{ release_id }` | `{ found, release }` — absent is a well-formed result |
| `ibuki.list_releases` | `{ limit?, before_cut_at? }` | `{ releases: [...], next_cursor? }` — newest first, cursor on `cut_at` |

No tool takes a `tenant` or `project` argument. `get_release` and `list_releases` filter on `tenant=current_tenant()`; a `release_id` owned by another tenant returns `{"found": false, "release": null}` — not-found rather than `TENANT_MISMATCH`, so the response does not confirm the id exists — and emits a `tool.tenant_mismatch` warning log, matching the shipped `_get_spec_by_id()` precedent. `mcp_server/auth.py` already resolves the bearer token to an `ApiToken` but binds only `api_token.tenant` into the tenant context; child 4 extends `mcp_server/context.py` with `current_token()` so `cut_by` can never be client-supplied.

`ReleaseErrorCode` (`StrEnum`, SCREAMING values, per `conformance.schemas.CheckErrorCode`):

`EMPTY_RELEASE` · `CONCURRENT_CUT` · `VERSION_MISMATCH` · `VERSION_TAKEN` · `VERSION_EXHAUSTED` · `RELEASE_NOT_FOUND` · `PROPOSAL_NOT_ACCEPTED` · `ALREADY_LOCKED` · `TENANT_MISMATCH`

`ALREADY_LOCKED` is one code more than the epic enumerates. `SpecVersion.lock()` raises `SpecLockedError` on an already-locked row, so that path exists whether or not it is named; leaving it unnamed would surface it as an internal error.

## Logging contract

Every action emits one INFO log per the [Logging Standard](https://github.com/weyucou/sops/blob/main/standards/logging.md), on top of the `tool.invoked` record `_log_invocation()` already emits. Spec content is never logged — only identifiers, counts and hashes.

| Event | Required extra fields |
|---|---|
| `spec.locked` | `spec_id`, `name`, `version`, `proposal_id` |
| `release.cut` | `release_id`, `version`, `scheme`, `item_count`, `predecessor_release_id`, `manifest_hash` |
| `release.cut_refused` | `reason` (`empty` \| `concurrent` \| `version_mismatch` \| `version_taken` \| `version_exhausted`) |

`cut_by` carries `token:<ApiToken.pk>`, so no token material reaches a log record or a manifest.

## Module layout (additive to pillars 2/3)

```
weyucou/ibuki-backend/
├── backend/
│   ├── releases/                       # NEW Django app
│   │   ├── apps.py
│   │   ├── models.py                   # Release + ReleaseItem (+ immutability enforcement)
│   │   ├── versioning.py               # VersioningScheme, next_version(), validate_version()
│   │   ├── manifest.py                 # canonical JSON + SHA-256 hashing
│   │   ├── service.py                  # cut_release() / get_release() / list_releases()
│   │   ├── schemas.py                  # pydantic wire contract + ReleaseErrorCode
│   │   ├── errors.py                   # ReleaseError hierarchy
│   │   ├── admin.py                    # read-only Release / ReleaseItem admin
│   │   ├── migrations/0001_initial.py
│   │   └── tests/{test_models,test_versioning,test_manifest,test_cut_release,
│   │              test_immutability,test_tools}.py
│   ├── tenants/migrations/0004_tenant_versioning_scheme.py
│   └── mcp_server/
│       ├── tools.py                    # EXISTING — real lock + cut_release; new get_release/list_releases
│       └── context.py                  # EXISTING — add current_token() for cut_by
└── docs/release-management.md
```

## Child issue split

The epic stays in `weyucou/ibuki`; the four children land in `weyucou/ibuki-backend` and take the next free numbers (the repo is at **#31**). This mirrors pillar 3 (`#11`/`#12`/`#16`/`#17`/`#18`) and pillar 5 (`#26`–`#29`): one PR-able slice per develop budget, since this epic is `complexity:complex`. All four share the DoD: gitleaks, ruff, pyright, pytest, security checklist.

1. **`releases` app scaffold** (`complexity:medium`) — `Release` + `ReleaseItem`, immutability enforcement, `manifest.py` hashing, `admin.py`, `0001_initial`. No dependencies; can start immediately.
2. **Versioning schemes + `Tenant.versioning_scheme`** (`complexity:medium`) — `versioning.py` pure functions, `hypothesis` property tests, `tenants/0004`. Runs in parallel with child 1.
3. **`cut_release` service** (`complexity:medium`) — selection query, row lock, empty refusal, concurrent-cut path. *Depends on children 1 and 2.*
4. **MCP wiring + docs** (`complexity:medium`) — real `ibuki.lock` + `ibuki.cut_release`, new `ibuki.get_release` / `ibuki.list_releases`, `current_token()` binding for `cut_by`, `docs/release-management.md`. *Depends on child 3, on DECISION 1, and on [ibuki-backend#18](https://github.com/weyucou/ibuki-backend/issues/18).*

## Testing strategy

| AC | Test |
|---|---|
| Lock produces a cut-eligible `SpecVersion` | `releases/tests/test_tools.py::test_lock_accepted_proposal_creates_locked_spec_version` |
| Bundle everything locked since the predecessor | `test_cut_release.py::test_cut_includes_versions_locked_since_predecessor` |
| Manifest fields present | `test_manifest.py::test_required_fields_present` |
| Manifest hash stable under field reordering | `test_manifest.py::test_hash_is_order_independent` |
| Per-tenant scheme | `test_versioning.py::test_next_version_per_scheme` (parametrised) + `hypothesis` monotonicity |
| Auto-version when `name` omitted | `test_cut_release.py::test_auto_version_when_name_omitted` |
| `name` validated against the scheme | `test_cut_release.py::test_name_override_rejected_on_scheme_mismatch` |
| Immutability | `test_immutability.py::test_release_save_rejected`, `::test_release_queryset_update_rejected`, `::test_release_delete_rejected` |
| Referenced spec version cannot be deleted | `test_immutability.py::test_spec_deletion_protected_by_release_item` |
| Empty refusal | `test_cut_release.py::test_empty_release_raises_structured_error` |
| Queryable via MCP | `test_tools.py::test_get_and_list_round_trip` |
| Concurrent cut | `test_cut_release.py::test_concurrent_cut_returns_structured_error` (two connections, `TransactionTestCase`) |
| Tenant isolation | `test_tools.py::test_list_releases_excludes_other_tenant` |
| Cross-tenant `release_id` is not-found | `test_tools.py::test_get_release_excludes_other_tenant` |

The concurrency test needs two real connections, so it is a `TransactionTestCase` against Postgres 17 in CI — `select_for_update(nowait=True)` is unobservable inside a single wrapped transaction.

## Out of scope (v1)

- Automatic / time-based release cuts (deferred per [#6](https://github.com/weyucou/ibuki/issues/6) — v1 is manual only)
- Release rollback or "un-cut" — the answer is a new release; the old one stays immutable
- Changelog rendering — the manifest is the source, rendering is a downstream consumer concern
- Cross-tenant release bundling — one release, one tenant
- Webhook / outbound notification of "release cut" events
- Postgres role grants revoking `UPDATE` / `DELETE` — owned by [ibuki-backend#14](https://github.com/weyucou/ibuki-backend/issues/14)
- An MCP setter for the versioning scheme — Django admin, matching `judge_model` and `check_token_budget`

## Open items

Resolve before or within the child issues named:

1. **DECISION 1 — accepted-payload source for `ibuki.lock`** (blocks child 4). Options, from the epic:
   - **(a) [ibuki-backend#18](https://github.com/weyucou/ibuki-backend/issues/18) persists the accepted payload on `Proposal` — recommended.** #18 already owns the `submit`/`respond` engine that holds the payload and applies counter-proposal merges; it is the only place the final accepted content exists. One `JSONField` + migration there, and `ibuki.lock` reads it.
   - (b) `ibuki.lock` takes the content as a tool argument — re-opens the trust boundary the rule engine closed, and lets a caller lock content the judge never saw. Not recommended.
   - (c) Pillar 4 adds the field to `proposals` itself — cross-pillar model ownership, and #18 would still have to write it.
2. **DECISION 3 — date-scheme exhaustion** (child 2). 27+ cuts in one calendar month: fail with `VERSION_EXHAUSTED` (plan default, recommended) or auto-extend to `-AA`, `-AB`, …? 27 cuts in a month is a signal, not a case to accommodate silently. Trivial to relax later.
3. **Cut-window watermark** (child 3). Selecting on `locked_at > predecessor.cut_at` can drop a lock that committed late: a lock transaction that stamps `locked_at = t0` but commits after a cut whose `cut_at = t2 > t0` is invisible to that cut's selection query, and the next cut's `locked_at > t2` filter excludes it too — so it is never released. Under Postgres' default READ COMMITTED this is reachable whenever a lock and a cut overlap. Recommended fix, for the child-3 author to confirm: derive the window's upper bound from the rows actually selected (store `max(item.locked_at)` as the watermark and filter the next cut against it), keeping `cut_at` as the honest wall-clock cut time in the manifest. A `TransactionTestCase` reproducing the interleave should land with the fix. The nullable `lock_watermark` column is already in the locked data model so child 1 ships it in `0001_initial`; child 3 populates it and switches the selection query to it.
4. **Read-only Django admin** (child 1). `admin.py` must not offer add/change/delete for `Release` or `ReleaseItem` — the model guards raise, so an editable admin form would surface a 500 instead of a disabled control.
