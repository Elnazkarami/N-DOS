#!/usr/bin/env python3
"""Round-trip lab metadata through a spreadsheet.

Scanning tells NDOS what is on disk. It cannot tell NDOS which animal a
recording came from, what was injected, or where. That knowledge lives in a
notebook or an Excel sheet, so this module meets it there:

    export   build a table of candidate sessions, with everything NDOS could
             observe already filled in, and blank columns for what only a
             human knows
    check    validate a filled-in table and report what is still missing

Re-exporting never destroys typed-in work: declared values are matched by a
stable identifier and carried across, while observed columns are refreshed.

Standard library only. Run it directly with no installation:

    python3 ndos_table.py export manifest.json -o sessions.csv
    python3 ndos_table.py check sessions.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ndos_report
import ndos_scan

TABLE_VERSION = "0.1"

#: Columns NDOS fills from the manifest. Overwritten on every export, because
#: they describe the filesystem rather than anybody's judgement.
OBSERVED_COLUMNS = (
    "ndos_id",
    "observed_path",
    "observed_folder_subject",
    "observed_folder_session",
    "observed_match",
    "observed_file_count",
    "observed_bytes",
    "observed_modalities",
    "observed_earliest",
    "observed_latest",
)

#: Columns only a person can fill. Always preserved across re-export.
DECLARED_COLUMNS = (
    "subject_id",
    "species",
    "strain",
    "sex",
    "date_of_birth",
    "genotype",
    "session_date",
    "session_type",
    "procedure",
    "target_region",
    "construct_or_drug",
    "task",
    "qc_status",
    "notes",
)

COLUMNS = OBSERVED_COLUMNS + DECLARED_COLUMNS

#: How well a group's folder names fit the shapes NDOS expects of a session.
#: Grouping a messy tree always produces rows that are not sessions at all, so
#: this tells a person which rows are worth their time rather than making them
#: work it out by eye.
MATCH_BOTH = "subject and session"
MATCH_SUBJECT = "subject only"
MATCH_SESSION = "session only"
MATCH_NONE = "no pattern match"

#: Controlled vocabularies. "unknown" is always permitted, and is meaningfully
#: different from an empty cell: it records that somebody looked and could not
#: determine the value, rather than that nobody has looked yet.
VOCABULARIES: Dict[str, Tuple[str, ...]] = {
    "sex": ("F", "M", "unknown"),
    "species": (
        "mus musculus", "rattus norvegicus", "macaca mulatta",
        "danio rerio", "drosophila melanogaster", "unknown",
    ),
    "session_type": (
        "electrophysiology", "calcium imaging", "behaviour", "histology",
        "surgery", "training", "other", "unknown",
    ),
    "qc_status": ("pass", "fail", "review", "unknown"),
}

#: Common ways labs write a species. Mapped rather than rejected, because
#: rejecting "mouse" would teach people that the tool is not worth using.
SPECIES_SYNONYMS: Dict[str, str] = {
    "mouse": "mus musculus",
    "mice": "mus musculus",
    "mus": "mus musculus",
    "m. musculus": "mus musculus",
    "rat": "rattus norvegicus",
    "rats": "rattus norvegicus",
    "r. norvegicus": "rattus norvegicus",
    "macaque": "macaca mulatta",
    "rhesus": "macaca mulatta",
    "zebrafish": "danio rerio",
    "fly": "drosophila melanogaster",
    "fruit fly": "drosophila melanogaster",
}

#: Lab shorthand for modalities. Same reasoning as the species map: people
#: write "ephys", and a tool that rejects it will simply not get used.
SESSION_TYPE_SYNONYMS: Dict[str, str] = {
    "ephys": "electrophysiology",
    "e-phys": "electrophysiology",
    "electrophys": "electrophysiology",
    "electrophysiology recording": "electrophysiology",
    "lfp": "electrophysiology",
    "spikes": "electrophysiology",
    "imaging": "calcium imaging",
    "ca imaging": "calcium imaging",
    "ca2+ imaging": "calcium imaging",
    "2p": "calcium imaging",
    "two-photon": "calcium imaging",
    "miniscope": "calcium imaging",
    "behavior": "behaviour",
    "behavioral": "behaviour",
    "behavioural": "behaviour",
    "histo": "histology",
    "surgical": "surgery",
}

SEX_SYNONYMS: Dict[str, str] = {
    "female": "F", "f": "F", "fem": "F",
    "male": "M", "m": "M",
    "unk": "unknown", "n/a": "unknown", "na": "unknown", "?": "unknown",
}

REQUIRED_FOR_COMPLETE = ("subject_id", "species", "sex", "session_date")

DATE_COLUMNS = ("date_of_birth", "session_date")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SLASH_DATE = re.compile(r"^\d{1,2}[/.]\d{1,2}[/.]\d{2,4}$")

#: Leading characters that make Excel and LibreOffice treat a cell as a
#: formula. Observed values come from folder names, so they are escaped.
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------

def _cell(row: Dict[str, Any], column: str) -> str:
    """Read a cell as text.

    Rows arrive either from a CSV, where every value is a string, or straight
    from group_sessions, where counts are integers. Both are valid inputs.
    """
    value = row.get(column)
    return "" if value is None else str(value).strip()


def _infer_levels(files: Sequence[Dict[str, Any]]) -> Tuple[Optional[int], Optional[int]]:
    """Guess which directory depths hold subjects and sessions."""
    subject_depth = session_depth = None
    for level in ndos_report.structure(files):
        if level["inferred"] == "animal or subject ID" and subject_depth is None:
            subject_depth = level["depth"]
        if level["inferred"] == "session" and session_depth is None:
            session_depth = level["depth"]
    return subject_depth, session_depth


def _group_id(path: str) -> str:
    """Stable identifier for a group, derived from its path.

    Renaming a folder produces a new id, which is the honest behaviour for now:
    NDOS cannot yet know that a renamed directory is the same session. Logical
    identity independent of location arrives with the entity model.
    """
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:10]
    return f"ndos-{digest}"


def group_sessions(
    manifest: Dict[str, Any],
    group_depth: Optional[int] = None,
    subject_depth: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Partition manifest files into candidate sessions.

    Grouping is by directory prefix rather than by inferred subject name, so a
    duplicated backup tree stays a separate row instead of being silently
    merged with the original.
    """
    files = manifest["files"]
    inferred_subject, inferred_session = _infer_levels(files)
    if subject_depth is None:
        subject_depth = inferred_subject
    if group_depth is None:
        group_depth = inferred_session if inferred_session is not None else 0

    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in files:
        parts = entry["path"].split("/")[:-1]
        prefix = "/".join(parts[: group_depth + 1]) if parts else ""
        groups[prefix].append(entry)

    rows = []
    for prefix in sorted(groups):
        members = groups[prefix]
        parts = prefix.split("/") if prefix else []
        modalities = sorted(
            {
                ndos_report.categorise(entry["extension"], entry["name"])
                for entry in members
            }
        )
        modified = sorted(e["modified"] for e in members if e.get("modified"))

        subject_name = (
            parts[subject_depth]
            if subject_depth is not None and len(parts) > subject_depth
            else ""
        )
        session_name = parts[group_depth] if len(parts) > group_depth else ""
        has_subject = (
            ndos_report._classify_name(subject_name) == "animal or subject ID"
            if subject_name
            else False
        )
        has_session = (
            ndos_report._classify_name(session_name) in ("session", "run or recording")
            if session_name
            else False
        )
        if has_subject and has_session:
            match = MATCH_BOTH
        elif has_subject:
            match = MATCH_SUBJECT
        elif has_session:
            match = MATCH_SESSION
        else:
            match = MATCH_NONE

        rows.append(
            {
                "ndos_id": _group_id(prefix),
                "observed_path": prefix or "(root)",
                "observed_folder_subject": subject_name,
                "observed_folder_session": session_name,
                "observed_match": match,
                "observed_file_count": len(members),
                "observed_bytes": sum(e["size_bytes"] for e in members),
                "observed_modalities": "; ".join(modalities),
                "observed_earliest": modified[0][:10] if modified else "",
                "observed_latest": modified[-1][:10] if modified else "",
            }
        )
    return rows


# --------------------------------------------------------------------------
# export
# --------------------------------------------------------------------------

def _escape(value: Any) -> str:
    """Neutralise spreadsheet formula injection from filesystem-derived text."""
    text = "" if value is None else str(value)
    if text.startswith(FORMULA_PREFIXES):
        return "'" + text
    return text


def read_table(path: Path) -> List[Dict[str, str]]:
    """Read a previously exported table, tolerating Excel's BOM."""
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def merge_declared(
    rows: List[Dict[str, Any]], existing: Sequence[Dict[str, str]]
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Carry human-entered values from a previous table onto fresh rows.

    Matching is by ndos_id. Rows in the old table with no counterpart are
    reported rather than dropped, since that usually means data moved or a
    scan root changed, and losing typed metadata silently would be the single
    fastest way to lose a user's trust.
    """
    previous = {row.get("ndos_id", ""): row for row in existing if row.get("ndos_id")}
    stats = {"matched": 0, "carried_values": 0, "orphaned": 0}

    for row in rows:
        old = previous.pop(row["ndos_id"], None)
        if old is None:
            continue
        stats["matched"] += 1
        for column in DECLARED_COLUMNS:
            value = _cell(old, column)
            if value:
                row[column] = value
                stats["carried_values"] += 1

    stats["orphaned"] = len(previous)
    return rows, stats


def write_table(rows: Sequence[Dict[str, Any]], path: Path) -> None:
    """Write the table as UTF-8 CSV with a BOM, so Excel opens it correctly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _escape(row.get(key, "")) for key in COLUMNS})


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def normalise(column: str, value: str) -> str:
    """Map a common lab spelling onto the controlled term, if one applies."""
    text = value.strip()
    if not text:
        return ""
    if column == "sex":
        return SEX_SYNONYMS.get(text.lower(), text)
    if column == "species":
        return SPECIES_SYNONYMS.get(text.lower(), text.lower())
    if column == "session_type":
        lowered = text.lower()
        return SESSION_TYPE_SYNONYMS.get(lowered, lowered)
    if column == "qc_status":
        return text.lower()
    return text


def check_table(rows: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    """Validate a filled-in table and measure how complete it is."""
    problems: List[Dict[str, Any]] = []
    filled: Counter = Counter()
    explicit_unknown: Counter = Counter()
    complete_rows = 0

    seen_ids: Dict[str, int] = {}

    for index, row in enumerate(rows, start=2):  # header is line 1
        row_id = _cell(row, "ndos_id")
        if not row_id:
            problems.append(
                {
                    "line": index,
                    "column": "ndos_id",
                    "value": "",
                    "message": "missing identifier; this row cannot be matched on re-export",
                }
            )
        elif row_id in seen_ids:
            problems.append(
                {
                    "line": index,
                    "column": "ndos_id",
                    "value": row_id,
                    "message": f"duplicate identifier, first seen on line {seen_ids[row_id]}",
                }
            )
        else:
            seen_ids[row_id] = index

        for column in DECLARED_COLUMNS:
            raw = _cell(row, column)
            if not raw:
                continue
            value = normalise(column, raw)
            filled[column] += 1
            if value == "unknown":
                explicit_unknown[column] += 1

            vocabulary = VOCABULARIES.get(column)
            if vocabulary and value not in vocabulary:
                problems.append(
                    {
                        "line": index,
                        "column": column,
                        "value": raw,
                        "message": f"not a recognised value; expected one of {', '.join(vocabulary)}",
                    }
                )
            if column in DATE_COLUMNS and not ISO_DATE.match(value):
                if SLASH_DATE.match(value):
                    message = (
                        "ambiguous date: 03/04/2025 means 3 April in the UK and "
                        "4 March in the US, so NDOS will not guess. Write it as "
                        "YYYY-MM-DD"
                    )
                else:
                    message = "dates must be written as YYYY-MM-DD"
                problems.append(
                    {
                        "line": index,
                        "column": column,
                        "value": raw,
                        "message": message,
                    }
                )

        if all(_cell(row, column) for column in REQUIRED_FOR_COMPLETE):
            complete_rows += 1

    total = len(rows)
    return {
        "row_count": total,
        "complete_rows": complete_rows,
        "problems": problems,
        "completeness": {
            column: {
                "filled": filled[column],
                "explicit_unknown": explicit_unknown[column],
                "percent": round(100 * filled[column] / total, 1) if total else 0.0,
                "required": column in REQUIRED_FOR_COMPLETE,
            }
            for column in DECLARED_COLUMNS
        },
    }


def render_check(result: Dict[str, Any]) -> str:
    out: List[str] = []
    add = out.append
    total = result["row_count"]

    add("=" * 72)
    add("NDOS METADATA CHECK")
    add("=" * 72)
    add(f"Rows            : {total}")
    add(
        f"Ready to use    : {result['complete_rows']} "
        f"({(100 * result['complete_rows'] / total) if total else 0:.0f}%)"
    )
    add(f"Problems        : {len(result['problems'])}")
    add("")
    add(
        "A row is ready when "
        + ", ".join(REQUIRED_FOR_COMPLETE)
        + " are all filled in."
    )

    add("")
    add("-" * 72)
    add("COMPLETENESS BY COLUMN")
    add("-" * 72)
    for column, stats in result["completeness"].items():
        marker = "required" if stats["required"] else ""
        bar = "#" * int(stats["percent"] / 5)
        note = (
            f"  ({stats['explicit_unknown']} recorded as unknown)"
            if stats["explicit_unknown"]
            else ""
        )
        add(
            f"  {column:<20}{stats['percent']:>6.1f}%  {bar:<20} "
            f"{marker}{note}"
        )

    if result["problems"]:
        add("")
        add("-" * 72)
        add("PROBLEMS")
        add("-" * 72)
        for problem in result["problems"]:
            add(
                f"  line {problem['line']:<5} {problem['column']:<18} "
                f"{problem['value']!r}"
            )
            add(f"        {problem['message']}")

    add("")
    add("-" * 72)
    add("An empty cell means nobody has filled it in yet.")
    add("Write 'unknown' to record that it was checked and cannot be known.")
    add("-" * 72)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# machine-readable output
# --------------------------------------------------------------------------

METADATA_VERSION = "0.1"

OBSERVED_NUMERIC = ("observed_file_count", "observed_bytes")


def to_records(
    rows: Sequence[Dict[str, Any]], include_empty: bool = False
) -> Dict[str, Any]:
    """Convert a filled table into validated, evidence-typed session records.

    Every declared value carries how it is known. NDOS distinguishes three
    states that are routinely conflated: a value somebody asserted, a value
    somebody checked and could not determine, and a value nobody has looked at
    yet. Only the first two appear here; the third is simply absent.
    """
    sessions = []
    for row in rows:
        declared: Dict[str, Any] = {}
        for column in DECLARED_COLUMNS:
            raw = _cell(row, column)
            if not raw:
                continue  # nobody has filled this in; absence is the record
            value = normalise(column, raw)
            field: Dict[str, Any] = {
                "value": value,
                "status": "unknown" if value == "unknown" else "declared",
            }
            if value != raw:
                # Keep what the person actually typed, so a mapping can be
                # audited or disputed later.
                field["as_entered"] = raw
            declared[column] = field

        if not declared and not include_empty:
            continue

        observed: Dict[str, Any] = {}
        for column in OBSERVED_COLUMNS:
            if column == "ndos_id":
                continue
            raw = _cell(row, column)
            if column in OBSERVED_NUMERIC:
                observed[column[len("observed_") :]] = int(raw) if raw.isdigit() else 0
            elif column == "observed_modalities":
                observed["modalities"] = [
                    part.strip() for part in raw.split(";") if part.strip()
                ]
            else:
                observed[column[len("observed_") :]] = raw

        sessions.append(
            {
                "ndos_id": _cell(row, "ndos_id"),
                "observed": observed,
                "declared": declared,
            }
        )

    return {
        "metadata_version": METADATA_VERSION,
        "generated_at": ndos_scan._utc_iso(
            datetime.now(tz=timezone.utc).timestamp()
        ),
        "generator": {"name": "ndos-table", "version": TABLE_VERSION},
        "session_count": len(sessions),
        "sessions": sessions,
    }


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def _load_manifest(path: Path, quiet: bool) -> Dict[str, Any]:
    if path.is_dir():
        if not quiet:
            print(f"Scanning {path} (read-only)...", file=sys.stderr)
        return ndos_scan.scan(path, progress=not quiet)
    return json.loads(path.read_text(encoding="utf-8"))


def command_export(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.source, args.quiet)
    rows = group_sessions(
        manifest, group_depth=args.group_depth, subject_depth=args.subject_depth
    )

    stats = None
    merge_source = args.merge or (args.output if args.output.exists() else None)
    if merge_source and merge_source.exists():
        rows, stats = merge_declared(rows, read_table(merge_source))

    write_table(rows, args.output)

    if not args.quiet:
        likely = sum(1 for row in rows if row["observed_match"] == MATCH_BOTH)
        print(f"Wrote {len(rows)} candidate sessions to {args.output}", file=sys.stderr)
        print(
            f"  {likely} look like real sessions (observed_match = "
            f"'{MATCH_BOTH}'); the rest may be backups, analysis folders, or "
            "loose files. Check that column before filling anything in.",
            file=sys.stderr,
        )
        if stats:
            print(
                f"Carried {stats['carried_values']} entered values across "
                f"{stats['matched']} matching rows.",
                file=sys.stderr,
            )
            if stats["orphaned"]:
                print(
                    f"Warning: {stats['orphaned']} rows in {merge_source} had no "
                    "match and were not carried over. Their metadata is still in "
                    "that file; nothing was deleted.",
                    file=sys.stderr,
                )
        print(
            "Open it in Excel, fill in the non-observed columns, then run: "
            f"python3 ndos_table.py check {args.output}",
            file=sys.stderr,
        )
    return 0


def command_check(args: argparse.Namespace) -> int:
    rows = read_table(args.table)
    result = check_table(rows)

    if args.format == "json":
        rendered = json.dumps(result, indent=2) + "\n"
    else:
        rendered = render_check(result)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if args.emit:
        if result["problems"] and args.strict:
            print(
                f"Refusing to write {args.emit}: fix the problems above first, "
                "or drop --strict.",
                file=sys.stderr,
            )
            return 1
        records = to_records(rows, include_empty=args.include_empty)
        args.emit.parent.mkdir(parents=True, exist_ok=True)
        args.emit.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        if args.format != "json":
            print(
                f"Wrote {records['session_count']} session records to {args.emit}",
                file=sys.stderr,
            )

    # A non-zero status lets this gate a pipeline or a pre-publication check.
    return 1 if result["problems"] and args.strict else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Round-trip lab metadata through a spreadsheet.",
        epilog="These commands never modify, move, or delete source data files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser(
        "export", help="Build a metadata table from a manifest or directory"
    )
    export.add_argument("source", type=Path, help="manifest.json, or a directory to scan")
    export.add_argument(
        "-o", "--output", type=Path, default=Path("sessions.csv"), help="CSV to write"
    )
    export.add_argument(
        "--merge",
        type=Path,
        help="Previous table to carry entered values from (defaults to --output if it exists)",
    )
    export.add_argument(
        "--group-depth",
        type=int,
        help="Directory depth that separates sessions (default: inferred)",
    )
    export.add_argument(
        "--subject-depth",
        type=int,
        help="Directory depth holding subject names (default: inferred)",
    )
    export.add_argument("-q", "--quiet", action="store_true")
    export.set_defaults(func=command_export)

    check = subparsers.add_parser("check", help="Validate a filled-in metadata table")
    check.add_argument("table", type=Path, help="CSV produced by export")
    check.add_argument("-o", "--output", type=Path, help="Write the report here")
    check.add_argument("-f", "--format", choices=("text", "json"), default="text")
    check.add_argument(
        "--strict", action="store_true", help="Exit non-zero if any problem is found"
    )
    check.add_argument(
        "--emit",
        type=Path,
        metavar="JSON",
        help="Write validated, evidence-typed session records for downstream NDOS modules",
    )
    check.add_argument(
        "--include-empty",
        action="store_true",
        help="Include rows with no entered metadata in --emit output",
    )
    check.set_defaults(func=command_check)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
