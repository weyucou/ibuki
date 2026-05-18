# Feature Change-Request Schema

The proposal schema is the atomic unit of the ibuki workflow. Humans and remote agents submit a payload conforming to this schema via MCP; the rule engine validates it before any LLM judge is invoked.

- **Schema:** [`schema/v0.1.0/proposal.schema.json`](../schema/v0.1.0/proposal.schema.json)
- **Reference template:** [`templates/proposal.example.json`](../templates/proposal.example.json)
- **JSON Schema dialect:** Draft 2020-12

## Versioning

`schema_version` is a semver string and the directory under `schema/` matches it byte-for-byte. Once a version is published, the file under `schema/vX.Y.Z/` is immutable. Breaking changes ship a new directory; payloads carry their `schema_version` so the validator can route to the matching schema.

## Field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string (const `"0.1.0"`) | yes | Schema version this payload conforms to. |
| `tenant` | string | yes | GitHub org slug (one tenant per org). Lowercase letters, digits, hyphens; max 39 chars. |
| `project` | string | yes | GitHub repo name within the tenant org. Up to 100 chars; `A–Z`, `a–z`, `0–9`, `.`, `_`, `-`. |
| `feature_id` | string | yes | Kebab-case slug, unique within `(tenant, project)`. Convention: `feature-NNN-short-description`. 2–64 chars. |
| `title` | string | yes | Short human-readable title (≤ 200 chars). |
| `intent` | string | yes | Why the feature exists — the outcome or problem it addresses. Free-form prose. |
| `scope` | object | yes | `{ "in": [...], "out": [...] }`. `in` has at least one item; `out` may be empty. |
| `acceptance_criteria` | array of strings | yes | At least one testable criterion. Prefer EARS notation (see below). |
| `supersedes` | string | no | Optional `feature_id` this proposal replaces. On lock, the superseded feature transitions to `state=superseded`. |
| `proposer` | object | yes | `{ "type": "human"|"agent", "id": "...", "name": "..." }`. `id` is a stable identifier; `name` is optional. |
| `submitted_at` | string (date-time) | yes | RFC 3339 timestamp. UTC (`Z`) or explicit offset. |
| `state` | string | yes | One of `proposed`, `locked`, `superseded`, `retired`. New submissions start as `proposed`. |

`additionalProperties` is forbidden at every object level. Unknown fields cause validation to fail.

## EARS-compatible acceptance criteria

`acceptance_criteria` is a string array. Each entry should follow one of the EARS templates:

| Pattern | Template |
|---|---|
| Ubiquitous | `The <system> SHALL <action>.` |
| Event-driven | `WHEN <trigger> THEN the <system> SHALL <response>.` |
| State-driven | `WHILE <state> the <system> SHALL <response>.` |
| Unwanted | `IF <unwanted condition> THEN the <system> SHALL <response>.` |
| Optional | `WHERE <feature included> the <system> SHALL <response>.` |

EARS is a guideline, not a regex — the schema accepts any non-empty string. Reviewers flag entries that aren't testable.

## Lifecycle states

| State | Meaning |
|---|---|
| `proposed` | Submitted; awaiting rule check, judge, and (if needed) iteration. |
| `locked` | Accepted by the proposal workflow. Immutable. Queues for the next release cut. |
| `superseded` | Replaced by another locked feature whose `supersedes` references this one. |
| `retired` | Removed from the active spec set (deprecation). Retained for history. |

The schema only carries the state field; transitions are enforced by the proposal workflow (pillar 3) and release manager (pillar 4).

## Identifier conventions

- `feature_id` is unique within `(tenant, project)`. Two different projects under the same tenant may both use `feature-1`; the tuple disambiguates.
- `supersedes` references a `feature_id` in the same `(tenant, project)`. Cross-project supersession is not supported in v0.1.
- `proposer.id` is a free-form stable identifier: GitHub username (`ellen-goc`), bot handle (`askcc-agent`), or service account name.

## Validation

The schema and template are checked in CI on every push:

```bash
uvx check-jsonschema --check-metaschema schema/v0.1.0/proposal.schema.json
uvx check-jsonschema --schemafile schema/v0.1.0/proposal.schema.json templates/proposal.example.json
```

A pre-commit hook (`.pre-commit-config.yaml`) runs the same checks locally. An intentionally-broken fixture at `tests/fixtures/proposal.invalid.json` is used in CI to confirm the validator still rejects malformed payloads.
