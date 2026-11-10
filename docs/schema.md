# Feature Change-Request Schema

The proposal schema is the atomic unit of the ibuki workflow. Humans and remote agents submit a payload conforming to this schema via MCP; the rule engine validates it before any LLM judge is invoked.

- **Schema:** [`schema/v0.2.0/proposal.schema.json`](../schema/v0.2.0/proposal.schema.json) (current; earlier versions under [Versioning](#versioning))
- **Reference template:** [`templates/proposal.example.json`](../templates/proposal.example.json)
- **JSON Schema dialect:** Draft 2020-12

## Versioning

`schema_version` is a semver string and the directory under `schema/` matches it byte-for-byte. Once a version is published, the file under `schema/vX.Y.Z/` is immutable. Breaking changes ship a new directory; payloads carry their `schema_version` so the validator can route to the matching schema.

| Version | Change |
|---|---|
| [`0.2.0`](../schema/v0.2.0/proposal.schema.json) | Adds the optional `requirements` field. Nothing else changed. |
| [`0.1.0`](../schema/v0.1.0/proposal.schema.json) | Initial schema. |

A v0.1.0 payload keeps validating against `schema/v0.1.0/`; the v0.2.0 schema rejects it, because `schema_version` is a `const`. The backend routes each payload to the schema named by its `schema_version`. New proposals target the current version.

## Field reference

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | string (const `"0.2.0"`) | yes | Schema version this payload conforms to. |
| `tenant` | string | yes | GitHub org slug (one tenant per org). Lowercase letters, digits, hyphens; max 39 chars. |
| `project` | string | yes | GitHub repo name within the tenant org. Up to 100 chars; `A–Z`, `a–z`, `0–9`, `.`, `_`, `-`. |
| `feature_id` | string | yes | Kebab-case slug, unique within `(tenant, project)`. Convention: `feature-NNN-short-description`. 2–64 chars. |
| `title` | string | yes | Short human-readable title (≤ 200 chars). |
| `intent` | string | yes | Why the feature exists — the outcome or problem it addresses. Free-form prose. |
| `scope` | object | yes | `{ "in": [...], "out": [...] }`. `in` has at least one item; `out` may be empty. |
| `acceptance_criteria` | array of strings | yes | At least one testable criterion. Prefer EARS notation (see below). |
| `requirements` | array of objects | no | Requirements this feature satisfies, for traceability. Each entry is `{ "source": ..., "id": ... }` with no other keys; `source` is `mther`, `github`, or `manual`. 1–100 entries when present; no `(source, id)` pair repeats. Id formats under [Identifier conventions](#identifier-conventions). |
| `supersedes` | string | no | Optional `feature_id` this proposal replaces. On lock, the superseded feature transitions to `state=superseded`. |
| `proposer` | object | yes | `{ "type": "human"|"agent", "id": "...", "name": "..." }`. `id` is a stable identifier; `name` is optional. |
| `submitted_at` | string (date-time) | yes | RFC 3339 timestamp. UTC (`Z`) or explicit offset. |
| `state` | string | yes | One of `proposed`, `locked`, `superseded`, `retired`. New submissions start as `proposed`. |

`additionalProperties` is forbidden at every object level. Unknown fields cause validation to fail.

`requirements` entries carry `source` and `id` only. `uniqueItems` compares whole entries, so keeping them to those two keys is what lets the schema itself reject a requirement cited twice; a free-text `note` or a `url` would let a duplicate through. Explain *how* the feature satisfies a requirement in `intent` or `acceptance_criteria`.

The uniqueness check compares entries pairwise, so its cost grows with the square of the list length. The schema caps the list at 100 entries and runs the check only within the cap (`if`/`then`). Without that guard, a validator that reports every error, such as Python `jsonschema`'s `iter_errors`, would spend about 20 seconds on an 8,000-entry list before rejecting it.

## EARS-compatible acceptance criteria

`acceptance_criteria` is a string array. Each entry should follow one of the five EARS templates. The canonical list is sops [`standards/acceptance-criteria-ears.md`](https://github.com/weyucou/sops/blob/main/standards/acceptance-criteria-ears.md); change it there first, then mirror it here.

| Pattern | Template |
|---|---|
| Ubiquitous | `The <system> shall <action>` |
| Event-driven | `WHEN <trigger>, the <system> shall <action>` |
| State-driven | `WHILE <state>, the <system> shall <action>` |
| Unwanted | `IF <unwanted condition>, THEN the <system> shall <response>` |
| Optional | `WHERE <feature> is supported, the <system> shall <action>` |

`THEN` after a `WHEN` trigger is optional. EARS is a guideline, not a regex — the schema accepts any non-empty string. Reviewers flag entries that aren't testable.

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
- `supersedes` references a `feature_id` in the same `(tenant, project)`. Cross-project supersession is not supported in v0.1 or v0.2.
- `proposer.id` is a free-form stable identifier: GitHub username (`ellen-goc`), bot handle (`askcc-agent`), or service account name.
- `requirements[].id` takes its format from `source`. The schema checks only for a 1–200 character string, so a consumer validates the format before resolving an id:
  - `mther`: `<org>/<estimate_request_id>#<TR display id>`, an MTHER technical requirement. A sops issue's `## Requirements` bullet `mther:<id>` becomes `{ "source": "mther", "id": "<id>" }`.
  - `github`: `<owner>/<repo>#<number>`, e.g. `weyucou/ibuki#1`.
  - `manual`: free text or a URI, for a requirement recorded in neither system.

## Validation

The schemas, the template, and the v0.1.0 fixture are checked in CI on every push:

```bash
uvx check-jsonschema --check-metaschema schema/v0.1.0/proposal.schema.json schema/v0.2.0/proposal.schema.json
uvx check-jsonschema --schemafile schema/v0.2.0/proposal.schema.json templates/proposal.example.json
uvx check-jsonschema --schemafile schema/v0.1.0/proposal.schema.json tests/fixtures/proposal.v0.1.0.json
```

A pre-commit hook (`.pre-commit-config.yaml`) runs the same checks locally. Two intentionally-broken fixtures confirm in CI that the validators still reject malformed payloads: `tests/fixtures/proposal.invalid.json` (v0.1.0 failure modes) and `tests/fixtures/proposal.v0.2.0.duplicate-requirements.invalid.json` (the same `(source, id)` cited twice).
