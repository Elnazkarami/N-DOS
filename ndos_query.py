#!/usr/bin/env python3
"""Build a reproducible cohort from NDOS session metadata.

A plain filter answers "which sessions match?". That question is not safe on
real lab data, because a session whose sex was never recorded is not a
non-match; it is an open question. Silently dropping such sessions biases the
resulting cohort in a way nobody sees.

So every query returns three groups: sessions that match, sessions that are
excluded by recorded evidence, and sessions that **cannot be ruled out**
because the deciding value was never entered. When nothing matches, the
constraint responsible is named rather than leaving an empty list.

Standard library only. Run it directly with no installation:

    python3 ndos_query.py metadata.json --where species=mouse --where sex=F
    python3 ndos_query.py metadata.json --where 'modalities~electrophysiology' \\
        --where 'session_date>=2025-03-01' --save-cohort cohort.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ndos_scan
import ndos_table

QUERY_VERSION = "0.1"
COHORT_VERSION = "0.1"

#: Outcome of testing one constraint against one session.
MATCH = "match"
FAIL = "fail"
UNRECORDED = "unrecorded"

#: Observed fields, queryable without a prefix since none collide with a
#: declared column name.
OBSERVED_FIELDS = (
    "path", "folder_subject", "folder_session", "match",
    "file_count", "bytes", "modalities", "earliest", "latest",
)

NUMERIC_FIELDS = ("file_count", "bytes")
LIST_FIELDS = ("modalities",)

#: Longest first, so ">=" is not read as ">".
OPERATORS = (">=", "<=", "!=", "~", "=", ">", "<")

ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class QueryError(ValueError):
    """A constraint could not be understood."""


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def parse_constraint(text: str) -> Dict[str, Any]:
    """Turn `field=value` into a structured, inspectable constraint."""
    for operator in OPERATORS:
        index = text.find(operator)
        if index <= 0:
            continue
        field = text[:index].strip()
        value = text[index + len(operator) :].strip()

        if operator == "=" and value == "*":
            operator, value = "present", ""
        elif operator == "=" and value == "?":
            operator, value = "unknown", ""
        elif not value:
            raise QueryError(f"no value given in {text!r}")

        if field.startswith("observed."):
            field = field[len("observed.") :]
        if field not in ndos_table.DECLARED_COLUMNS and field not in OBSERVED_FIELDS:
            known = ", ".join(sorted(ndos_table.DECLARED_COLUMNS + OBSERVED_FIELDS))
            raise QueryError(f"unknown field {field!r}. Available fields: {known}")

        declared = field in ndos_table.DECLARED_COLUMNS
        # Normalise the query the same way the data was normalised, so that
        # `species=mouse` finds sessions recorded as `mus musculus`.
        resolved = ndos_table.normalise(field, value) if declared and value else value

        return {
            "field": field,
            "operator": operator,
            "value": resolved,
            "as_typed": text,
            "resolved_from": value if resolved != value else None,
            "source": "declared" if declared else "observed",
        }

    raise QueryError(
        f"could not parse {text!r}. Expected something like 'species=mouse', "
        "'session_date>=2025-01-01', or 'modalities~electrophysiology'"
    )


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------

def _observed_value(session: Dict[str, Any], field: str) -> Any:
    return session.get("observed", {}).get(field)


def _declared_entry(session: Dict[str, Any], field: str) -> Optional[Dict[str, Any]]:
    return session.get("declared", {}).get(field)


def _matching_items(actual: Any, expected: str, operator: str) -> List[str]:
    """The list entries that satisfied the constraint, for citation."""
    items = actual if isinstance(actual, list) else [actual]
    needle = expected.lower()
    if operator == "~":
        return [str(item) for item in items if needle in str(item).lower()]
    return [str(item) for item in items if str(item).lower() == needle]


def _compare(operator: str, actual: Any, expected: str, field: str) -> bool:
    if field in LIST_FIELDS:
        items = actual if isinstance(actual, list) else [actual]
        lowered = [str(item).lower() for item in items]
        if operator == "~":
            return any(expected.lower() in item for item in lowered)
        if operator == "=":
            return expected.lower() in lowered
        if operator == "!=":
            return expected.lower() not in lowered
        raise QueryError(f"{operator!r} cannot be used on {field!r}")

    if field in NUMERIC_FIELDS:
        try:
            left, right = float(actual), float(expected)
        except (TypeError, ValueError):
            raise QueryError(f"{field!r} needs a number, got {expected!r}")
    else:
        left, right = str(actual), str(expected)
        if operator in ("=", "!=", "~"):
            left, right = left.lower(), right.lower()

    if operator == "=":
        return left == right
    if operator == "!=":
        return left != right
    if operator == "~":
        return right in left
    if operator == ">":
        return left > right
    if operator == "<":
        return left < right
    if operator == ">=":
        return left >= right
    if operator == "<=":
        return left <= right
    raise QueryError(f"unsupported operator {operator!r}")


def evaluate(session: Dict[str, Any], constraint: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Test one constraint, distinguishing a real failure from missing data."""
    field = constraint["field"]
    operator = constraint["operator"]

    if constraint["source"] == "observed":
        actual = _observed_value(session, field)
        if actual is None or actual == "" or actual == []:
            return UNRECORDED, {"field": field, "reason": "not present in the manifest"}
        if operator == "present":
            return MATCH, {"field": field, "value": actual, "status": "observed"}
        if operator == "unknown":
            return FAIL, {"field": field, "reason": "observed values are never 'unknown'"}
        outcome = MATCH if _compare(operator, actual, constraint["value"], field) else FAIL
        shown = actual
        if outcome == MATCH and field in LIST_FIELDS and operator in ("~", "="):
            # Cite what actually matched, not the whole list; a session with
            # six modalities should not bury the one that was asked for.
            shown = _matching_items(actual, constraint["value"], operator)
        return outcome, {"field": field, "value": shown, "status": "observed"}

    entry = _declared_entry(session, field)
    if entry is None:
        # Nobody has filled this in. That is not evidence against the session.
        return UNRECORDED, {"field": field, "reason": "never entered"}

    status = entry.get("status", "declared")
    if status == "unknown":
        if operator == "unknown":
            return MATCH, {"field": field, "value": "unknown", "status": "unknown"}
        return UNRECORDED, {
            "field": field,
            "reason": "recorded as unknown; checked but could not be determined",
        }

    if operator == "unknown":
        return FAIL, {"field": field, "value": entry["value"], "status": status}
    if operator == "present":
        return MATCH, {"field": field, "value": entry["value"], "status": status}

    outcome = MATCH if _compare(operator, entry["value"], constraint["value"], field) else FAIL
    detail = {"field": field, "value": entry["value"], "status": status}
    if "as_entered" in entry:
        detail["as_entered"] = entry["as_entered"]
    return outcome, detail


def run_query(
    metadata: Dict[str, Any], constraints: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """Classify every session as matched, unresolved, or excluded."""
    matched: List[Dict[str, Any]] = []
    unresolved: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    eliminated_by: Dict[str, int] = {c["as_typed"]: 0 for c in constraints}
    blocked_by: Dict[str, int] = {c["as_typed"]: 0 for c in constraints}

    for session in metadata.get("sessions", []):
        evidence: List[Dict[str, Any]] = []
        failures: List[str] = []
        missing: List[Dict[str, Any]] = []

        for constraint in constraints:
            outcome, detail = evaluate(session, constraint)
            if outcome == MATCH:
                evidence.append({**detail, "constraint": constraint["as_typed"]})
            elif outcome == FAIL:
                failures.append(constraint["as_typed"])
                eliminated_by[constraint["as_typed"]] += 1
            else:
                missing.append({**detail, "constraint": constraint["as_typed"]})
                blocked_by[constraint["as_typed"]] += 1

        record = {
            "ndos_id": session.get("ndos_id", ""),
            "path": _observed_value(session, "path") or "",
            "evidence": evidence,
            "missing": missing,
            "failed": failures,
        }
        if failures:
            excluded.append(record)
        elif missing:
            unresolved.append(record)
        else:
            matched.append(record)

    return {
        "query_version": QUERY_VERSION,
        "generated_at": ndos_scan._utc_iso(datetime.now(tz=timezone.utc).timestamp()),
        "constraints": list(constraints),
        "counts": {
            "considered": len(metadata.get("sessions", [])),
            "matched": len(matched),
            "unresolved": len(unresolved),
            "excluded": len(excluded),
        },
        "eliminated_by": eliminated_by,
        "blocked_by": blocked_by,
        "matched": matched,
        "unresolved": unresolved,
        "excluded": excluded,
    }


def diagnose(result: Dict[str, Any]) -> List[str]:
    """Explain an empty or disappointing result instead of returning nothing."""
    notes: List[str] = []
    counts = result["counts"]

    if counts["considered"] == 0:
        return [
            "The metadata file contains no sessions. Run 'ndos_table.py check "
            "--emit' on a filled-in table first."
        ]

    if counts["matched"] == 0 and counts["excluded"]:
        worst = max(result["eliminated_by"].items(), key=lambda item: item[1])
        if worst[1]:
            notes.append(
                f"Nothing matched. The constraint that excluded the most "
                f"sessions was '{worst[0]}' ({worst[1]} excluded). Try dropping "
                "or widening it."
            )

    if counts["unresolved"]:
        # Only fields blocking sessions that failed nothing else are worth
        # naming: filling in a field on an already-excluded session changes
        # nothing, so reporting it would send someone down a dead end.
        blocking: Dict[str, int] = {}
        for row in result["unresolved"]:
            for item in row["missing"]:
                blocking[item["field"]] = blocking.get(item["field"], 0) + 1
        fields = ", ".join(
            f"{field} ({count})"
            for field, count in sorted(blocking.items(), key=lambda i: -i[1])
        )
        count = counts["unresolved"]
        plural = "" if count == 1 else "s"

        if counts["matched"] == 0:
            notes.append(
                f"No session matched outright, but {count} could not be ruled "
                f"out because {fields} was never entered. Filling that in may "
                "be what is needed, not a different query."
            )
        else:
            notes.append(
                f"{count} session{plural} could not be ruled in or out, blocked "
                f"by: {fields}. Treating {'it' if count == 1 else 'them'} as "
                f"{'a non-match' if count == 1 else 'non-matches'} would bias "
                "this cohort, so they are listed separately."
            )

    return notes


# --------------------------------------------------------------------------
# cohort
# --------------------------------------------------------------------------

def build_cohort(
    result: Dict[str, Any],
    metadata: Dict[str, Any],
    source: Path,
    name: Optional[str] = None,
    include_unresolved: bool = False,
) -> Dict[str, Any]:
    """Freeze a query and its members into a reproducible cohort record."""
    members = [
        {"ndos_id": row["ndos_id"], "path": row["path"], "inclusion": "matched"}
        for row in result["matched"]
    ]
    if include_unresolved:
        members += [
            {"ndos_id": row["ndos_id"], "path": row["path"], "inclusion": "unresolved"}
            for row in result["unresolved"]
        ]

    return {
        "cohort_version": COHORT_VERSION,
        "name": name or "unnamed-cohort",
        "generated_at": result["generated_at"],
        "generator": {"name": "ndos-query", "version": QUERY_VERSION},
        "source": {
            "file": str(source),
            "metadata_version": metadata.get("metadata_version", ""),
            "metadata_generated_at": metadata.get("generated_at", ""),
            "session_count": metadata.get("session_count", 0),
        },
        "query_plan": [
            {
                "as_typed": c["as_typed"],
                "field": c["field"],
                "operator": c["operator"],
                "value": c["value"],
                "source": c["source"],
                "resolved_from": c["resolved_from"],
            }
            for c in result["constraints"]
        ],
        "counts": result["counts"],
        "includes_unresolved": include_unresolved,
        "member_count": len(members),
        "members": members,
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render(result: Dict[str, Any], verbose: bool = False) -> str:
    out: List[str] = []
    add = out.append
    counts = result["counts"]

    add("=" * 72)
    add("NDOS COHORT QUERY")
    add("=" * 72)
    add("Query plan:")
    for constraint in result["constraints"]:
        line = (
            f"  {constraint['field']} {constraint['operator']} "
            f"{constraint['value'] or '(any)'}"
        )
        if constraint["resolved_from"]:
            line += f"   [you typed '{constraint['resolved_from']}']"
        line += f"   ({constraint['source']})"
        add(line)
    if not result["constraints"]:
        add("  (no constraints; every session is returned)")

    add("")
    add(
        f"Considered {counts['considered']} sessions: "
        f"{counts['matched']} matched, {counts['unresolved']} unresolved, "
        f"{counts['excluded']} excluded."
    )

    add("")
    add("-" * 72)
    add(f"MATCHED ({counts['matched']})")
    add("-" * 72)
    for row in result["matched"]:
        add(f"  {row['ndos_id']}  {row['path']}")
        for item in row["evidence"]:
            entered = (
                f" [entered as '{item['as_entered']}']" if "as_entered" in item else ""
            )
            value = item.get("value", "")
            shown = ", ".join(value) if isinstance(value, list) else value
            add(f"      {item['field']} = {shown}  ({item['status']}){entered}")
    if not result["matched"]:
        add("  (none)")

    if result["unresolved"]:
        add("")
        add("-" * 72)
        add(f"CANNOT BE RULED OUT ({counts['unresolved']})")
        add("-" * 72)
        add("  These meet every criterion that could be checked, but a deciding")
        add("  value was never recorded. They are not non-matches.")
        add("")
        for row in result["unresolved"]:
            add(f"  {row['ndos_id']}  {row['path']}")
            for item in row["missing"]:
                add(f"      {item['field']}: {item['reason']}")

    if verbose and result["excluded"]:
        add("")
        add("-" * 72)
        add(f"EXCLUDED ({counts['excluded']})")
        add("-" * 72)
        for row in result["excluded"]:
            add(f"  {row['ndos_id']}  {row['path']}")
            add(f"      failed: {', '.join(row['failed'])}")
    elif result["excluded"]:
        add("")
        add("-" * 72)
        add(f"EXCLUDED ({counts['excluded']})")
        add("-" * 72)
        for text, count in result["eliminated_by"].items():
            if count:
                add(f"  {count:>4} excluded by  {text}")
        add("  (use --verbose to list them)")

    notes = diagnose(result)
    if notes:
        add("")
        add("-" * 72)
        add("NOTES")
        add("-" * 72)
        for note in notes:
            add(f"  - {note}")

    add("")
    add("-" * 72)
    add("Every match cites the field and evidence status it was based on.")
    add("-" * 72)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Query NDOS session metadata and build a reproducible cohort.",
        epilog=(
            "Operators: = != > < >= <= ~ (contains). "
            "Use field=* to require any value, field=? for values recorded as unknown."
        ),
    )
    parser.add_argument("metadata", type=Path, help="JSON written by ndos_table.py check --emit")
    parser.add_argument(
        "-w", "--where", action="append", default=[], metavar="EXPR",
        help="Constraint such as 'species=mouse'; repeatable",
    )
    parser.add_argument("--save-cohort", type=Path, help="Write a frozen cohort record here")
    parser.add_argument("--name", help="Name for the saved cohort")
    parser.add_argument(
        "--include-unresolved", action="store_true",
        help="Include sessions that cannot be ruled out in the saved cohort",
    )
    parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    parser.add_argument("-o", "--output", type=Path, help="Write the report here")
    parser.add_argument("-v", "--verbose", action="store_true", help="List excluded sessions")
    args = parser.parse_args()

    try:
        metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
        constraints = [parse_constraint(text) for text in args.where]
        result = run_query(metadata, constraints)
    except QueryError as error:
        parser.error(str(error))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"could not read {args.metadata}: {error}")

    rendered = (
        json.dumps(result, indent=2) + "\n" if args.format == "json"
        else render(result, verbose=args.verbose)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.save_cohort:
        cohort = build_cohort(
            result, metadata, args.metadata,
            name=args.name, include_unresolved=args.include_unresolved,
        )
        args.save_cohort.parent.mkdir(parents=True, exist_ok=True)
        args.save_cohort.write_text(json.dumps(cohort, indent=2) + "\n", encoding="utf-8")
        if args.format != "json":
            print(
                f"Wrote cohort of {cohort['member_count']} sessions to {args.save_cohort}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
