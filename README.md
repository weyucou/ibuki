# ibuki

A multi-tenant, multi-project, version-controlled specification and feature management system for AI agent development — so that human-authored intent and AI-executed implementation stay in sync.

## Goals

### Mission

Provide AI agents (and humans) with a single, queryable source of truth for what a project is building, and a structured workflow for proposing, evaluating, locking, and releasing feature changes.

### Architecture

| Dimension | Decision |
|---|---|
| Deployment | Hosted MCP service (single instance, multi-tenant) |
| Tenant boundary | One tenant per GitHub org (e.g. `weyucou`, `monkut`) |
| Interface | MCP server (Claude-native). REST may follow in v2 |
| Auth | ibuki-issued tokens, per tenant (decoupled from GitHub OAuth) |
| Feature granularity | One spec per GitHub issue / PR |

### Primary outcomes

1. **Single org-wide source of truth** — every project under a tenant has its feature specs in ibuki, queryable over MCP.
2. **Role-chunked agent consumption** — agents fetch role-scoped slices (plan / develop / review) rather than full-document dumps.
3. **Bi-directional code ↔ spec evaluation** — agents call `ibuki check` to ask either direction: *"does this code match the locked spec?"* or *"does this proposed spec match the current code?"*
4. **First-class git-style artifacts** — locked specs are versioned, diffable, retirable; release manifests are immutable once cut.

### Core workflow — proposal-driven

```
Submit  →  Rule check  →  LLM judge  →  Verdict  ↔  Proposer response  →  Lock  →  Release cut
                                       (iterative loop until convergence)
```

1. **Submit** — a human or remote agent issues a change request (new feature or modification) via MCP.
2. **Rule check** — deterministic engine validates schema + uniqueness + conflict detection (no duplicate IDs, no overlapping proposals on the same component).
3. **LLM judge** — on rule pass, an LLM evaluates intent, scope, and consistency with existing locked specs. Verdict: **accept**, **reject**, or **counter-propose** (with revised draft + reasoning).
4. **Iterative response** — proposer can accept the verdict, reject it (escalates), or counter-propose back. Loop continues until convergence.
5. **Lock** — accepted proposals become immutable and queued for the next release.
6. **Release cut** — a human or designated agent manually cuts a release. Locked-since-last-cut proposals bundle into a versioned immutable manifest. Versioning scheme is per-tenant configurable (semver / date / sequential).

### Non-goals

1. **Not replacing GitHub issues** — issues describe the *next change*; ibuki specs describe *what is being built*.
2. **Claude-first, not LLM-agnostic** — initial target is Claude-family agents via MCP. Cross-vendor portability is a v2 concern.

## Feature Pillars

| # | Pillar | Description |
|---|---|---|
| 1 | Spec schema | Per-feature schema (per issue / PR); rule-validated |
| 2 | MCP server + tenant auth | Hosted multi-tenant MCP interface; ibuki-issued tokens; per-org routing |
| 3 | Proposal workflow | Submit → rules → LLM judge → accept/reject/counter → lock; iterative response |
| 4 | Release management | Manual release cuts; per-tenant versioning; immutable release manifests |
| 5 | Conformance check | `ibuki check` MCP tool — code↔spec bi-directional evaluation, on agent request |
| 6 | Agent consumption | Role-chunked spec output (plan/develop/review slices) over MCP |

The current issues that implement these pillars are tracked on the [Ibuki project board](https://github.com/orgs/weyucou/projects/12).

Per-pillar design docs land under [`docs/pillars/`](docs/pillars/) as each pillar's design is locked:

- Pillar 2 — [MCP server + tenant auth](docs/pillars/02-mcp-server-tenant-auth.md)

## Schema

The feature change-request schema (pillar 1) is the atomic unit of the ibuki workflow.

- Schema: [`schema/v0.1.0/proposal.schema.json`](schema/v0.1.0/proposal.schema.json) (JSON Schema Draft 2020-12)
- Reference payload: [`templates/proposal.example.json`](templates/proposal.example.json)
- Field reference: [`docs/schema.md`](docs/schema.md)

Validate a payload locally:

```bash
uvx check-jsonschema --schemafile schema/v0.1.0/proposal.schema.json <your-proposal>.json
```

## Status

Pre-implementation. Goals are locked as of 2026-05-18 (see [#6](https://github.com/weyucou/ibuki/issues/6)). Pillar issues are being re-scoped against the locked vision before implementation work begins.
