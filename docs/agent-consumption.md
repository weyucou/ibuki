# Agent Consumption — Role-Chunked Spec Output

Pillar 6. Agents read a locked spec through the `ibuki.get_spec` MCP tool, asking for the slice their role needs rather than the whole document. Dumping a full spec into an agent's context wastes tokens and degrades performance over a long session — the agent forgets early requirements and hallucinates at the edges. A planner does not need acceptance criteria to draw up a plan; a reviewer does not need the intent prose to check the work against the criteria.

- **Canonical projection map:** [`schema/v0.1.0/role-projections.json`](../schema/v0.1.0/role-projections.json) — machine-readable, vendored into `weyucou/ibuki-backend` and drift-checked in CI.
- **Implementation:** `backend/specs/projections.py` + `backend/mcp_server/tools.py` in [`weyucou/ibuki-backend`](https://github.com/weyucou/ibuki-backend).
- **Spec schema the projections are defined over:** [`docs/schema.md`](schema.md) (v0.1.0).

## Roles

| Role | Who asks | What they get |
|---|---|---|
| `plan` | Planner agents drafting an approach | Why the feature exists and where its edges are — intent plus both sides of scope. |
| `develop` | Developer agents writing the code | What to build and what "done" means — intent, in-scope items, acceptance criteria. Out-of-scope is omitted: a developer acts on what is in scope. |
| `review` | Reviewer agents checking the work | What to verify — acceptance criteria plus the explicit out-of-scope list, so scope creep is visible. Intent prose is omitted so the review anchors on testable criteria. |
| `full` | Escape hatch, and the default for existing callers | The complete locked spec, unchunked. |

## Field mapping

Rows are the fields of a schema v0.1.0 payload. `✓` = present in the response body, `—` = omitted.

| Field | `plan` | `develop` | `review` | `full` |
|---|:---:|:---:|:---:|:---:|
| `schema_version`¹ | — | — | — | ✓ |
| `tenant` | — | — | — | ✓ |
| `project` | — | — | — | ✓ |
| `feature_id` | ✓ | ✓ | ✓ | ✓ |
| `title` | ✓ | ✓ | ✓ | ✓ |
| `intent` | ✓ | ✓ | — | ✓ |
| `scope.in` | ✓ | ✓ | — | ✓ |
| `scope.out` | ✓ | — | ✓ | ✓ |
| `acceptance_criteria` | ✓ | ✓ | ✓ | ✓ |
| `supersedes`² | ✓ | ✓ | ✓ | ✓ |
| `proposer` | — | — | — | ✓ |
| `submitted_at` | — | — | — | ✓ |
| `state` | ✓ | ✓ | ✓ | ✓ |

¹ Omitted from the body for the chunked roles, but always echoed in `_meta.schema_version` — an agent never has to guess which schema version it is reading.
² `supersedes` is optional in the schema. A projection that names a field the stored spec does not carry simply omits it; it is not emitted as `null`.

`full` returns the stored document as-is, including any field not listed above. The chunked roles are strict subsets — projection only ever removes fields, never adds, renames, or summarises them. Agents that need a condensed form summarise it themselves.

Both `scope.in` and `scope.out` project into a `scope` object, so `scope.in` alone yields `{"scope": {"in": [...]}}` — the shape stays recognisable against the schema.

## Tool contract

```jsonc
// Request
{
  "spec_id": 42,          // or "name": "feature-4-agent-consumption" — exactly one
  "version": 3,           // optional; defaults to the latest locked version
  "role": "develop"       // plan | develop | review | full (default: full)
}
```

Tenant is never a parameter. It is pinned from the bearer token for the whole request, which is the tenant-isolation chokepoint (pillar 2).

```jsonc
// Response (success)
{
  "_meta": {
    "spec_id": 42,
    "name": "feature-4-agent-consumption",
    "version": 3,
    "schema_version": "0.1.0",
    "role": "develop",
    "served_at": "2026-08-26T12:34:56Z"
  },
  "feature_id": "feature-4-agent-consumption",
  "title": "Agent consumption MCP tool: role-chunked spec output",
  "intent": "...",
  "scope": { "in": ["..."] },
  "acceptance_criteria": ["..."],
  "state": "locked"
}
```

`_meta` is present on every response, success or error, and is always authoritative — a stored field named `_meta` cannot displace it.

### Errors

```jsonc
// Not found / wrong tenant / no locked version — one shape for all three
{
  "_meta": { "served_at": "2026-08-26T12:34:56Z" },
  "error": {
    "code": "spec_unavailable",
    "message": "No locked spec is available at that id for this tenant."
  }
}

// Unsupported role value
{
  "_meta": { "served_at": "2026-08-26T12:34:56Z" },
  "error": {
    "code": "invalid_role",
    "message": "role must be one of: plan, develop, review, full."
  }
}

// Neither or both of spec_id / name supplied
{
  "_meta": { "served_at": "2026-08-26T12:34:56Z" },
  "error": {
    "code": "invalid_arguments",
    "message": "Address the spec by exactly one of spec_id or name."
  }
}
```

| Code | Meaning |
|---|---|
| `spec_unavailable` | No locked spec is readable at that address for the calling tenant. |
| `invalid_role` | `role` is not one of the four supported values. |
| `invalid_arguments` | Neither or both of `spec_id` / `name` were supplied. |

`spec_unavailable` is deliberately one code for three distinct causes — absent, owned by another tenant, or present but never locked. Distinguishing them would tell a caller that a spec it cannot read exists, which is exactly the cross-tenant existence leak the unified error closes. The server-side audit log still records the tenant mismatch separately.

### Only locked specs are served

`ibuki.get_spec` reads locked spec versions only. Drafts are proposal-workflow state (pillar 3) and are not agent-consumable: an agent acting on an unlocked spec is acting on something that may still change under it. With no version requested, the latest **locked** version is returned — a spec with a locked v1 and a draft v2 serves v1. A `version` that exists but is not locked yields `spec_unavailable`.

## Example invocations

Addressing by `name` throughout; `spec_id` works identically.

```jsonc
// plan — intent and both sides of scope
{"name": "feature-4-agent-consumption", "role": "plan"}
// -> _meta, feature_id, title, intent, scope.in, scope.out, acceptance_criteria, supersedes?, state
```

```jsonc
// develop — what to build, what done means
{"name": "feature-4-agent-consumption", "role": "develop"}
// -> _meta, feature_id, title, intent, scope.in, acceptance_criteria, supersedes?, state
```

```jsonc
// review — what to verify, and what not to flag
{"name": "feature-4-agent-consumption", "role": "review"}
// -> _meta, feature_id, title, scope.out, acceptance_criteria, supersedes?, state
```

```jsonc
// full — the complete locked document, at a pinned version
{"name": "feature-4-agent-consumption", "version": 3, "role": "full"}
// -> _meta, plus every stored field
```

## Keeping the map honest

The projection map exists in three places, chained so drift fails a build rather than misleading an agent:

1. **`schema/v0.1.0/role-projections.json`** (this repo) — canonical.
2. **The table above** — checked against the JSON by `scripts/check_projection_table.py` in this repo's CI.
3. **`ROLE_FIELDS` in `backend/specs/projections.py`** (`ibuki-backend`) — a literal map, asserted equal to the vendored copy of the JSON by a unit test; the vendored copy is diffed against this repo by `scripts/check-schema-drift.sh` in that repo's CI.

Change the JSON first, then the table, then the backend's map and its vendored copy.

## Not in v1

- **Per-tenant role customisation.** The map is static and org-wide.
- **Summarised acceptance criteria for `plan`.** The projection returns the full criterion list; heading-only summarisation was drafted, then dropped as premature — it is a lossy transform to commit to before any agent-usage feedback exists.
- **Session continuity.** The spec store is authoritative; a `_continuity` field carrying last-seen version and session summary was considered and left out. Sessions are managed by the agent, not by ibuki.
