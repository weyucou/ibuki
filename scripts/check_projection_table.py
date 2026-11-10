#!/usr/bin/env python3
"""Fail when the role/field table in docs/agent-consumption.md drifts from the canonical map.

The current schema version's `role-projections.json` (under `SCHEMA_DIR`) is what
`ibuki-backend` consumes; the markdown table is what a human reads before deciding
which role to ask for. A table that disagrees with the JSON is worse than no table —
it describes a projection no agent will ever be served.

Also checks that every field of the proposal schema has a row, so a field added to
the schema cannot quietly ship without a role mapping decision.

Standard library only; run from the repository root.
"""

from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# The table documents the current schema version; bump this when a new version ships.
SCHEMA_DIR = REPO_ROOT / "schema" / "v0.2.0"
PROJECTIONS_PATH = SCHEMA_DIR / "role-projections.json"
SCHEMA_PATH = SCHEMA_DIR / "proposal.schema.json"
DOC_PATH = REPO_ROOT / "docs" / "agent-consumption.md"

TABLE_HEADER_CELL = "Field"
INCLUDED = "✓"
EXCLUDED = "—"
# Footnote markers hang off field names in the doc; they are annotation, not identity.
FOOTNOTE_MARKS = "¹²³⁴⁵⁶⁷⁸⁹"


def split_row(line: str) -> list[str]:
    """Split one markdown table row into its normalised cells."""
    cells = line.strip().strip("|").split("|")
    # Footnote markers sit outside the code span (`field`¹), so they come off first.
    return [unicodedata.normalize("NFC", cell).strip().rstrip(FOOTNOTE_MARKS).strip("`") for cell in cells]


def parse_table(markdown: str) -> tuple[list[str], list[list[str]]]:
    """Return the (header, rows) of the field-mapping table, or exit if it is missing."""
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("|"):
            continue
        header = split_row(line)
        if header[0] != TABLE_HEADER_CELL:
            continue
        # Skip the header separator row (|---|:---:|...), then take rows until the table ends.
        body = []
        for row_line in lines[index + 2 :]:
            if not row_line.startswith("|"):
                break
            body.append(split_row(row_line))
        return header, body

    sys.exit(f"::error::No table with a leading '{TABLE_HEADER_CELL}' column found in {DOC_PATH.name}.")


def documented_roles(header: list[str], rows: list[list[str]]) -> dict[str, list[str]]:
    """Map each role column to the fields its column marks as included."""
    roles: dict[str, list[str]] = {role: [] for role in header[1:]}
    for row in rows:
        field, marks = row[0], row[1:]
        for role, mark in zip(header[1:], marks, strict=True):
            if mark == INCLUDED:
                roles[role].append(field)
            elif mark != EXCLUDED:
                sys.exit(f"::error::Row '{field}', column '{role}': expected '{INCLUDED}' or '{EXCLUDED}', got '{mark}'.")
    return roles


def schema_fields() -> tuple[set[str], set[str]]:
    """Return (top-level property names, every path the table may address).

    A projection addresses a field either whole (`proposer`) or one level in
    (`scope.in`), so both forms are legal rows; but every top-level property must
    be accounted for by some row.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    top_level = set(schema["properties"])
    addressable = set(top_level)
    for name, definition in schema["properties"].items():
        addressable.update(f"{name}.{child}" for child in definition.get("properties", ()))
    return top_level, addressable


def report(problems: list[str]) -> int:
    for problem in problems:
        print(f"::error::{problem}")
    if problems:
        return 1
    print(f"ok  {DOC_PATH.relative_to(REPO_ROOT)} matches {PROJECTIONS_PATH.relative_to(REPO_ROOT)}")
    return 0


def main() -> int:
    canonical = json.loads(PROJECTIONS_PATH.read_text(encoding="utf-8"))
    header, rows = parse_table(DOC_PATH.read_text(encoding="utf-8"))
    documented = documented_roles(header, rows)
    problems = []

    table_fields = [row[0] for row in rows]
    duplicates = {field for field in table_fields if table_fields.count(field) > 1}
    if duplicates:
        problems.append(f"Duplicate rows in the field table: {sorted(duplicates)}.")

    top_level, addressable = schema_fields()
    missing_rows = top_level - {field.split(".")[0] for field in table_fields}
    if missing_rows:
        problems.append(f"Schema fields with no row in the field table: {sorted(missing_rows)}.")
    unknown_rows = set(table_fields) - addressable
    if unknown_rows:
        problems.append(f"Field table rows that are not schema fields: {sorted(unknown_rows)}.")

    complete_role = canonical["complete_role"]
    expected_columns = {complete_role, *canonical["roles"]}
    if set(header[1:]) != expected_columns:
        problems.append(f"Field table columns {sorted(header[1:])} do not match roles {sorted(expected_columns)}.")
        return report(problems)

    for role, fields in canonical["roles"].items():
        if set(documented[role]) != set(fields):
            problems.append(
                f"Role '{role}' documents {sorted(documented[role])} but the canonical map is {sorted(fields)}."
            )

    # `full` is not a projection — it returns the stored document whole, so every row is included.
    omitted_from_complete = set(table_fields) - set(documented[complete_role])
    if omitted_from_complete:
        problems.append(f"Role '{complete_role}' must include every field; missing {sorted(omitted_from_complete)}.")

    return report(problems)


if __name__ == "__main__":
    sys.exit(main())
