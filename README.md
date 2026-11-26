# ibuki

A multi-tenant, multi-project development platform: the org's alternative to GitHub issues and projects. Every unit of work is an ibuki task anchored to a versioned, locked spec. Humans and AI agents propose changes to the spec, work tasks against it, and review the code against it. ibuki records every transition, so the spec, the tasks and the code stay in sync.

## Goals

### Mission

Orchestrate the development of a project, across multiple developers and AI agents, from one place:

- **The spec** says *what is being built*: versioned, locked through a proposal workflow, and released as immutable manifests.
- **Tasks** are *the work that builds it*: issue-like units with a lifecycle, assigned to humans or agents, each traced to the spec version and requirements it implements.
- **The event log** is *what happened*: an append-only record of every proposal, verdict, lock, release and task transition. Current state and flow metrics are derived from it.

Concurrent contributors align on one authoritative spec and one task list, instead of drifting apart across issue threads, boards and side documents.

### Architecture

| Dimension | Decision |
|---|---|
| Deployment | Hosted MCP service (single instance, multi-tenant) |
| Hierarchy | Tenant (one per org, e.g. `weyucou`, `monkut`) → Project (one per product or repository) → specs and tasks |
| Interface | MCP server (Claude-native) for agents. A human UI and REST API are v2 |
| Auth | ibuki-issued tokens, per tenant (decoupled from GitHub OAuth) |
| Spec granularity | One spec per feature, versioned; each locked version can drive many tasks |
| Task store | ibuki-native tasks. GitHub issues are imported once for migration; ibuki is the system of record afterwards |
| State model | Append-only event log; task and spec state are projections of it. No LLM in the write path: LLM verdicts are stored as events and never rewrite a proposal or task |
| Code hosting | Git repositories and pull requests stay on GitHub in v1; tasks link to branches and PRs by URL |

### Primary outcomes

1. **Single source of truth per project.** Every project's locked specs and open tasks live in ibuki, queryable over MCP.
2. **Spec-anchored tasks.** Every task cites the spec version and `requirements[]` IDs it implements, so ibuki can answer "which requirements are covered, in progress, or unstarted?" for any spec version.
3. **Agent-native task orchestration.** Agents create, claim, transition and comment on tasks over MCP. A claim is a lease, so two agents never work the same task.
4. **Role-chunked agent consumption.** Agents fetch role-scoped slices (plan / develop / review) of a spec and of its tasks, never full-document dumps. Context is pulled by the agent, not pushed into its prompt.
5. **Bi-directional code ↔ spec evaluation.** `ibuki check` answers *"does this code match the locked spec?"* and *"does this proposed spec match the current code?"*. The review stage of a task runs it.
6. **Auditable history and flow metrics.** Every change is an immutable event. Cycle time, lead time and throughput are computed from the event log, never reconstructed from a third-party API.
7. **First-class git-style artifacts.** Locked specs are versioned, diffable and retirable; release manifests are immutable once cut.

### Core workflows

**Spec: proposal-driven**

```
Submit  →  Rule check  →  LLM judge  →  Verdict  ↔  Proposer response  →  Lock  →  Release cut
                                       (iterative loop until convergence)
```

1. **Submit**: a human or remote agent issues a change request (new feature or modification) via MCP.
2. **Rule check**: a deterministic engine validates the schema and detects duplicates and conflicts (no duplicate IDs, no overlapping proposals on the same component).
3. **LLM judge**: on a rule pass, an LLM evaluates intent, scope, and consistency with existing locked specs. Verdict: **accept**, **reject**, or **counter-propose** (with a revised draft and reasoning).
4. **Iterative response**: the proposer accepts the verdict, rejects it (escalates), or counter-proposes. The loop continues until convergence.
5. **Lock**: accepted proposals become immutable and are queued for the next release.
6. **Release cut**: a human or designated agent cuts a release manually. Everything locked since the last cut is bundled into a versioned, immutable manifest. The versioning scheme is configurable per tenant (semver / date / sequential).

**Task: spec-anchored**

```
Locked spec version  →  Tasks created (cite requirement IDs)  →  backlog → planned → in-progress → in-review → done
                                                                                         │
                                                                          ibuki check (code ↔ spec)
```

1. **Create**: a human or agent creates tasks against a locked spec version, each citing the requirement IDs it covers.
2. **Plan → claim**: a planned task is claimed by one human or agent (a lease); the claim, every transition and every comment are events.
3. **Review**: moving to `in-review` links the PR and runs `ibuki check` against the task's spec version.
4. **Done**: a done task marks its requirements as implemented for that spec version. A newer locked version flags open tasks whose requirements changed.

### Non-goals

1. **Not a git host in v1.** Repositories, branches and pull requests stay on GitHub; ibuki replaces issues, boards and project tracking.
2. **Not an LLM-distilled memory.** ibuki keeps the raw record (proposals, verdicts, transitions, comments) intact. Summaries are derived views, never the record.
3. **Claude-first, not LLM-agnostic.** The initial target is Claude-family agents via MCP. Cross-vendor portability is a v2 concern.

### v1 definition of done

ibuki v1 is done when one weyucou project (ibuki itself) runs end to end inside it without GitHub issues:

- [ ] Deployed to the dev account and reachable over MCP (weyucou/ibuki-backend#14)
- [ ] `Project` model: specs, proposals, releases and tasks are scoped to `(tenant, project)`
- [ ] Task MCP tools: create, get, list, claim (lease), transition, comment
- [ ] Every proposal verdict, lock, release and task transition is an append-only event; state is derived from events
- [ ] Tasks cite spec version and requirement IDs; ibuki reports requirement coverage per spec version
- [ ] `ibuki.check`, `ibuki.lock` and `ibuki.cut_release` are implemented (today they are stubs)
- [ ] Flow metrics are computed from the event log, replacing `ellen-core/kicore/flow_metrics.py` → `weyucou/issue-tracker`
- [ ] GitHub issue import for migration

## Feature Pillars

| # | Pillar | Description |
|---|---|---|
| 1 | Spec schema | Per-feature schema with `requirements[]` traceability; rule-validated |
| 2 | MCP server + tenant auth | Hosted multi-tenant MCP interface; ibuki-issued tokens; per-org routing; tenant → project scoping |
| 3 | Proposal workflow | Submit → rules → LLM judge → accept/reject/counter → lock; iterative response |
| 4 | Release management | Manual release cuts; per-tenant versioning; immutable release manifests |
| 5 | Conformance check | `ibuki check` MCP tool: code↔spec bi-directional evaluation, on agent request and at task review |
| 6 | Agent consumption | Role-chunked spec and task output (plan/develop/review slices) over MCP |
| 7 | Task orchestration | Native issue-like tasks: lifecycle states, claim leases, comments, requirement coverage, GitHub import |
| 8 | Event log + flow metrics | Append-only event store for every spec and task change; state projections; cycle/lead time and throughput |

Pillars 7 and 8 have no design doc yet; their design research is tracked in [weyucou/research-playbook#92](https://github.com/weyucou/research-playbook/issues/92).

The current issues that implement these pillars are tracked on the [Ibuki project board](https://github.com/orgs/weyucou/projects/12).

Per-pillar design docs land under [`docs/pillars/`](docs/pillars/) as each pillar's design is locked:

- Pillar 2 — [MCP server + tenant auth](docs/pillars/02-mcp-server-tenant-auth.md)
- Pillar 4 — [Release management](docs/pillars/04-release-management.md)
- Pillar 6 — [Agent consumption: role-chunked spec output](docs/agent-consumption.md)

## Schema

The feature change-request schema (pillar 1) is the atomic unit of the ibuki workflow.

- Schema: [`schema/v0.2.0/proposal.schema.json`](schema/v0.2.0/proposal.schema.json) (JSON Schema Draft 2020-12)
- Reference payload: [`templates/proposal.example.json`](templates/proposal.example.json)
- Field reference: [`docs/schema.md`](docs/schema.md)
- Role projections (pillar 6): [`schema/v0.2.0/role-projections.json`](schema/v0.2.0/role-projections.json)

Validate a payload locally:

```bash
uvx check-jsonschema --schemafile schema/v0.2.0/proposal.schema.json <your-proposal>.json
```

## Related Repositories

| Repository | Purpose |
|---|---|
| [`weyucou/ibuki`](https://github.com/weyucou/ibuki) | Meta/spec repo (this repo) — schema, design docs, project board |
| [`weyucou/ibuki-backend`](https://github.com/weyucou/ibuki-backend) | Django 5.2 LTS backend + MCP server |
| [`weyucou/ibuki-infra`](https://github.com/weyucou/ibuki-infra) | AWS CloudFormation infrastructure (Postgres + Fargate) |

## Absorbed Projects

ibuki takes over the goals of two dormant org repositories. Migrating their open issues and archiving them are tracked in [#22](https://github.com/weyucou/ibuki/issues/22).

| Repository | What ibuki takes over |
|---|---|
| [`weyucou/task-management`](https://github.com/weyucou/task-management) | Agent task management. Its SQS queue was never deployed; ibuki tasks (pillar 7) replace it |
| [`weyucou/issue-tracker`](https://github.com/weyucou/issue-tracker) | Event store for issue lifecycle transitions, and flow metrics. Replaced by pillar 8 |

## Status

Goals re-scoped on 2026-11-26 ([#22](https://github.com/weyucou/ibuki/issues/22)); this supersedes the 2026-05-18 goals ([#6](https://github.com/weyucou/ibuki/issues/6)).

Pillars 1–6 are in implementation in [`weyucou/ibuki-backend`](https://github.com/weyucou/ibuki-backend):

- **Working MCP tools:** `submit`, `respond`, `list_escalated`, `get_spec`.
- **Stubs:** `check`, `lock`, `cut_release`.
- **Not started:** the `Project` model and pillars 7–8.
- **Not deployed:** the first dev deploy is [weyucou/ibuki-backend#14](https://github.com/weyucou/ibuki-backend/issues/14).
