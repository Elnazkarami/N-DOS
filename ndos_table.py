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

#: Facts about an animal, recorded once no matter how many times it is
#: recorded from. Keyed by subject_id.
ANIMAL_COLUMNS = (
    "subject_id",
    "species",
    "strain",
    "sex",
    "date_of_birth",
    "genotype",
    "source",
    "notes",
)

#: Things done to an animal: surgery, injection, implant, drug, training. One
#: procedure typically governs many later sessions, which is why it cannot live
#: on the session row.
PROCEDURE_COLUMNS = (
    "procedure_id",
    "subject_id",
    "procedure_date",
    "procedure_type",
    "target_region",
    "construct_or_drug",
    "dose",
    "notes",
)

#: Facts true of one recording session only.
SESSION_DECLARED_COLUMNS = (
    "subject_id",
    "session_date",
    "session_type",
    "task",
    "qc_status",
    "notes",
)

#: Retained for the session table's own validation and merge logic.
DECLARED_COLUMNS = SESSION_DECLARED_COLUMNS

COLUMNS = OBSERVED_COLUMNS + SESSION_DECLARED_COLUMNS

#: Filenames within a metadata directory.
ANIMALS_FILE = "animals.csv"
PROCEDURES_FILE = "procedures.csv"
SESSIONS_FILE = "sessions.csv"

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
    "procedure_type": (
        "surgery", "injection", "implant", "lesion", "drug", "stimulation",
        "training", "perfusion", "other", "unknown",
    ),
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
PROCEDURE_TYPE_SYNONYMS: Dict[str, str] = {
    "viral injection": "injection",
    "virus injection": "injection",
    "aav": "injection",
    "craniotomy": "surgery",
    "probe implant": "implant",
    "electrode implant": "implant",
    "cannula": "implant",
    "headplate": "implant",
    "headbar": "implant",
    "ip injection": "drug",
    "i.p.": "drug",
    "perfusion/fixation": "perfusion",
    "transcardial perfusion": "perfusion",
}

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

#: A session row is usable when it can be tied to an animal and placed in
#: time. Species and sex now live on the animal, and are checked there.
REQUIRED_FOR_COMPLETE = ("subject_id", "session_date")
REQUIRED_ANIMAL_FIELDS = ("species", "sex")

DATE_COLUMNS = ("date_of_birth", "session_date", "procedure_date")
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


def write_table(
    rows: Sequence[Dict[str, Any]],
    path: Path,
    columns: Sequence[str] = COLUMNS,
) -> None:
    """Write a table as UTF-8 CSV with a BOM, so Excel opens it correctly."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _escape(row.get(key, "")) for key in columns})


def seed_animals(session_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Propose one animal row per distinct subject folder name observed.

    Only groups whose folder names actually looked like a subject are used;
    seeding a row for every scratch directory would bury the real animals.
    """
    names: List[str] = []
    for row in session_rows:
        if row.get("observed_match") not in (MATCH_BOTH, MATCH_SUBJECT):
            continue
        name = str(row.get("observed_folder_subject") or "").strip()
        if name and name not in names:
            names.append(name)
    return [{"subject_id": name} for name in sorted(names, key=str.lower)]


def export_metadata(
    manifest: Dict[str, Any],
    directory: Path,
    group_depth: Optional[int] = None,
    subject_depth: Optional[int] = None,
) -> Dict[str, Any]:
    """Write (or refresh) the three linked metadata tables.

    Sessions are regenerated so observed columns stay current, with entered
    values carried across. Animals are merged, gaining rows for newly seen
    subjects. Procedures are never rewritten: NDOS cannot observe a surgery,
    so that file belongs entirely to the person keeping it.
    """
    directory.mkdir(parents=True, exist_ok=True)
    sessions_path = directory / SESSIONS_FILE
    animals_path = directory / ANIMALS_FILE
    procedures_path = directory / PROCEDURES_FILE

    sessions = group_sessions(
        manifest, group_depth=group_depth, subject_depth=subject_depth
    )
    stats = {"matched": 0, "carried_values": 0, "orphaned": 0}
    if sessions_path.exists():
        sessions, stats = merge_declared(sessions, read_table(sessions_path))
    write_table(sessions, sessions_path)

    proposed = seed_animals(sessions)
    existing_animals = read_table(animals_path) if animals_path.exists() else []
    by_id = {
        (row.get("subject_id") or "").strip(): row
        for row in existing_animals
        if (row.get("subject_id") or "").strip()
    }
    added = 0
    for candidate in proposed:
        if candidate["subject_id"] not in by_id:
            by_id[candidate["subject_id"]] = candidate
            added += 1
    animals = sorted(by_id.values(), key=lambda r: str(r.get("subject_id", "")).lower())
    write_table(animals, animals_path, ANIMAL_COLUMNS)

    procedures_created = not procedures_path.exists()
    if procedures_created:
        write_table([], procedures_path, PROCEDURE_COLUMNS)

    return {
        "directory": directory,
        "sessions": len(sessions),
        "animals": len(animals),
        "animals_added": added,
        "procedures_created": procedures_created,
        "merge": stats,
    }


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
    if column == "procedure_type":
        lowered = text.lower()
        return PROCEDURE_TYPE_SYNONYMS.get(lowered, lowered)
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


def _days_between(earlier: str, later: str) -> Optional[int]:
    """Whole days from one ISO date to another, or None if either is unusable."""
    try:
        start = datetime.strptime(earlier, "%Y-%m-%d")
        end = datetime.strptime(later, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None
    return (end - start).days


def check_metadata(directory: Path) -> Dict[str, Any]:
    """Validate the three tables together, including references between them.

    Validating each file alone would miss the errors that actually matter: a
    session naming an animal that has no row, or a procedure recorded against
    a subject nobody has described.
    """
    sessions = read_table(directory / SESSIONS_FILE)
    animals = (
        read_table(directory / ANIMALS_FILE)
        if (directory / ANIMALS_FILE).exists() else []
    )
    procedures = (
        read_table(directory / PROCEDURES_FILE)
        if (directory / PROCEDURES_FILE).exists() else []
    )

    result = check_table(sessions)
    result["animals"] = _check_entity(animals, ANIMAL_COLUMNS, "subject_id", ANIMALS_FILE)
    result["procedures"] = _check_entity(
        procedures, PROCEDURE_COLUMNS, "procedure_id", PROCEDURES_FILE
    )

    known = {
        _cell(row, "subject_id") for row in animals if _cell(row, "subject_id")
    }
    references: List[Dict[str, Any]] = []

    for index, row in enumerate(sessions, start=2):
        subject = _cell(row, "subject_id")
        if subject and subject not in known:
            references.append(
                {
                    "file": SESSIONS_FILE,
                    "line": index,
                    "message": (
                        f"session names subject {subject!r}, which has no row in "
                        f"{ANIMALS_FILE}"
                    ),
                }
            )

    for index, row in enumerate(procedures, start=2):
        subject = _cell(row, "subject_id")
        if not subject:
            references.append(
                {
                    "file": PROCEDURES_FILE,
                    "line": index,
                    "message": "procedure has no subject_id, so it cannot be linked to an animal",
                }
            )
        elif subject not in known:
            references.append(
                {
                    "file": PROCEDURES_FILE,
                    "line": index,
                    "message": (
                        f"procedure names subject {subject!r}, which has no row in "
                        f"{ANIMALS_FILE}"
                    ),
                }
            )

    result["references"] = references
    result["counts"] = {
        "animals": len(animals),
        "procedures": len(procedures),
        "sessions": len(sessions),
    }
    return result


def _check_entity(
    rows: Sequence[Dict[str, str]],
    columns: Sequence[str],
    key: str,
    filename: str,
) -> Dict[str, Any]:
    """Validate one entity table's own values and key uniqueness."""
    problems: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    filled: Counter = Counter()

    for index, row in enumerate(rows, start=2):
        identifier = _cell(row, key)
        if identifier:
            if identifier in seen:
                problems.append(
                    {
                        "file": filename,
                        "line": index,
                        "column": key,
                        "value": identifier,
                        "message": f"duplicate, first seen on line {seen[identifier]}",
                    }
                )
            else:
                seen[identifier] = index

        for column in columns:
            raw = _cell(row, column)
            if not raw:
                continue
            filled[column] += 1
            value = normalise(column, raw)

            vocabulary = VOCABULARIES.get(column)
            if vocabulary and value not in vocabulary:
                problems.append(
                    {
                        "file": filename,
                        "line": index,
                        "column": column,
                        "value": raw,
                        "message": f"expected one of {', '.join(vocabulary)}",
                    }
                )
            if column in DATE_COLUMNS and not ISO_DATE.match(value):
                message = (
                    "ambiguous date: 03/04/2025 means 3 April in the UK and 4 "
                    "March in the US, so NDOS will not guess. Write it as "
                    "YYYY-MM-DD"
                    if SLASH_DATE.match(value)
                    else "dates must be written as YYYY-MM-DD"
                )
                problems.append(
                    {
                        "file": filename,
                        "line": index,
                        "column": column,
                        "value": raw,
                        "message": message,
                    }
                )

    return {
        "file": filename,
        "row_count": len(rows),
        "problems": problems,
        "filled": dict(filled),
    }


def render_check(result: Dict[str, Any]) -> str:
    out: List[str] = []
    add = out.append
    total = result["row_count"]

    add("=" * 72)
    add("NDOS METADATA CHECK")
    add("=" * 72)
    tables = result.get("counts") or {}
    if "animals" in tables:
        add(
            f"Tables          : {tables['animals']} animals, "
            f"{tables['procedures']} procedures, {tables['sessions']} sessions"
        )
    add(f"Session rows    : {total}")
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

    entity_problems = []
    for key in ("animals", "procedures"):
        entity = result.get(key)
        if entity:
            entity_problems += entity["problems"]

    if result["problems"] or entity_problems:
        add("")
        add("-" * 72)
        add("PROBLEMS")
        add("-" * 72)
        for problem in result["problems"]:
            add(
                f"  {SESSIONS_FILE} line {problem['line']:<4} "
                f"{problem['column']:<18} {problem['value']!r}"
            )
            add(f"        {problem['message']}")
        for problem in entity_problems:
            add(
                f"  {problem['file']} line {problem['line']:<4} "
                f"{problem['column']:<18} {problem['value']!r}"
            )
            add(f"        {problem['message']}")

    if result.get("references"):
        add("")
        add("-" * 72)
        add("BROKEN LINKS BETWEEN TABLES")
        add("-" * 72)
        for problem in result["references"]:
            add(f"  {problem['file']} line {problem['line']}")
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


def _typed_fields(row: Dict[str, Any], columns: Sequence[str]) -> Dict[str, Any]:
    """Evidence-typed values for one row, omitting anything not filled in."""
    fields: Dict[str, Any] = {}
    for column in columns:
        raw = _cell(row, column)
        if not raw:
            continue
        value = normalise(column, raw)
        field: Dict[str, Any] = {
            "value": value,
            "status": "unknown" if value == "unknown" else "declared",
        }
        if value != raw:
            field["as_entered"] = raw
        fields[column] = field
    return fields


def link_records(directory: Path, include_empty: bool = False) -> Dict[str, Any]:
    """Join sessions to their animal and to the procedures that preceded them.

    This is what the flat table could not express: a surgery happens once and
    governs every session after it. Intervals are computed here rather than
    typed by hand, and are labelled 'computed' so they are never mistaken for
    something a person asserted.
    """
    sessions = read_table(directory / SESSIONS_FILE)
    animals = (
        read_table(directory / ANIMALS_FILE)
        if (directory / ANIMALS_FILE).exists() else []
    )
    procedures = (
        read_table(directory / PROCEDURES_FILE)
        if (directory / PROCEDURES_FILE).exists() else []
    )

    by_subject = {
        _cell(row, "subject_id"): row for row in animals if _cell(row, "subject_id")
    }
    procedures_by_subject: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for row in procedures:
        subject = _cell(row, "subject_id")
        if subject:
            procedures_by_subject[subject].append(row)

    records = []
    for row in sessions:
        declared = _typed_fields(row, SESSION_DECLARED_COLUMNS)
        if not declared and not include_empty:
            continue

        observed: Dict[str, Any] = {}
        for column in OBSERVED_COLUMNS:
            if column == "ndos_id":
                continue
            raw = _cell(row, column)
            name = column[len("observed_") :]
            if column in OBSERVED_NUMERIC:
                observed[name] = int(raw) if raw.isdigit() else 0
            elif column == "observed_modalities":
                observed["modalities"] = [
                    part.strip() for part in raw.split(";") if part.strip()
                ]
            else:
                observed[name] = raw

        subject = _cell(row, "subject_id")
        session_date = normalise("session_date", _cell(row, "session_date"))
        derived: Dict[str, Any] = {}

        animal_record = None
        animal_row = by_subject.get(subject)
        if animal_row is not None:
            animal_record = {
                "subject_id": subject,
                "declared": _typed_fields(animal_row, ANIMAL_COLUMNS),
            }
            birth = normalise("date_of_birth", _cell(animal_row, "date_of_birth"))
            age = _days_between(birth, session_date) if birth and session_date else None
            if age is not None and age >= 0:
                derived["age_days"] = {"value": str(age), "status": "computed"}

        linked_procedures = []
        for procedure_row in procedures_by_subject.get(subject, []):
            procedure_date = normalise(
                "procedure_date", _cell(procedure_row, "procedure_date")
            )
            interval = (
                _days_between(procedure_date, session_date)
                if procedure_date and session_date else None
            )
            entry: Dict[str, Any] = {
                "procedure_id": _cell(procedure_row, "procedure_id"),
                "declared": _typed_fields(procedure_row, PROCEDURE_COLUMNS),
            }
            if interval is not None:
                entry["days_before_session"] = interval
                entry["relation"] = "before" if interval >= 0 else "after"
            linked_procedures.append(entry)

            # Expose the most recent preceding procedure of each type as a
            # queryable interval, which is how questions are actually asked:
            # "recorded three to five weeks after the injection".
            kind = normalise("procedure_type", _cell(procedure_row, "procedure_type"))
            if kind and interval is not None and interval >= 0:
                key = f"days_since_{kind.replace(' ', '_')}"
                current = derived.get(key)
                if current is None or interval < int(current["value"]):
                    derived[key] = {"value": str(interval), "status": "computed"}

        record = {
            "ndos_id": _cell(row, "ndos_id"),
            "observed": observed,
            "declared": declared,
        }
        if animal_record:
            record["animal"] = animal_record
        if linked_procedures:
            record["procedures"] = linked_procedures
        if derived:
            record["derived"] = derived
        records.append(record)

    return {
        "metadata_version": METADATA_VERSION,
        "generated_at": ndos_scan._utc_iso(datetime.now(tz=timezone.utc).timestamp()),
        "generator": {"name": "ndos-table", "version": TABLE_VERSION},
        "session_count": len(records),
        "sessions": records,
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
    summary = export_metadata(
        manifest,
        args.dir,
        group_depth=args.group_depth,
        subject_depth=args.subject_depth,
    )

    if not args.quiet:
        print(
            f"{summary['sessions']} sessions -> {args.dir / SESSIONS_FILE}",
            file=sys.stderr,
        )
        print(
            f"{summary['animals']} animals ({summary['animals_added']} new) -> "
            f"{args.dir / ANIMALS_FILE}",
            file=sys.stderr,
        )
        if summary["procedures_created"]:
            print(
                f"empty procedure sheet -> {args.dir / PROCEDURES_FILE}  "
                "(NDOS cannot observe surgeries; this file is yours)",
                file=sys.stderr,
            )
        else:
            print(
                f"left {args.dir / PROCEDURES_FILE} untouched",
                file=sys.stderr,
            )
        merge = summary["merge"]
        if merge["carried_values"]:
            print(
                f"carried {merge['carried_values']} entered values across "
                f"{merge['matched']} sessions",
                file=sys.stderr,
            )
        if merge["orphaned"]:
            print(
                f"warning: {merge['orphaned']} previous session rows had no "
                "match and were not carried over; nothing was deleted",
                file=sys.stderr,
            )
        print(
            f"Fill these in, then run: python3 ndos_table.py check {args.dir}",
            file=sys.stderr,
        )
    return 0


def command_check(args: argparse.Namespace) -> int:
    result = check_metadata(args.dir)

    if args.format == "json":
        rendered = json.dumps(result, indent=2) + "\n"
    else:
        rendered = render_check(result)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    problems = (
        result["problems"]
        + result["animals"]["problems"]
        + result["procedures"]["problems"]
        + result["references"]
    )

    if args.emit:
        if problems and args.strict:
            print(
                f"Refusing to write {args.emit}: fix the problems above first, "
                "or drop --strict.",
                file=sys.stderr,
            )
            return 1
        records = link_records(args.dir, include_empty=args.include_empty)
        args.emit.parent.mkdir(parents=True, exist_ok=True)
        args.emit.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        if args.format != "json":
            print(
                f"Wrote {records['session_count']} linked session records to "
                f"{args.emit}",
                file=sys.stderr,
            )

    return 1 if problems and args.strict else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Round-trip lab metadata through linked spreadsheets.",
        epilog=(
            "Metadata lives in three tables: animals.csv (one row per animal), "
            "procedures.csv (surgeries, injections, drugs) and sessions.csv "
            "(recordings). These commands never modify source data files."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export = subparsers.add_parser(
        "export", help="Create or refresh the metadata tables"
    )
    export.add_argument("source", type=Path, help="manifest.json, or a directory to scan")
    export.add_argument(
        "-d", "--dir", type=Path, default=Path("metadata"),
        help="Directory to hold the tables (default: metadata/)",
    )
    export.add_argument(
        "--group-depth", type=int,
        help="Directory depth that separates sessions (default: inferred)",
    )
    export.add_argument(
        "--subject-depth", type=int,
        help="Directory depth holding subject names (default: inferred)",
    )
    export.add_argument("-q", "--quiet", action="store_true")
    export.set_defaults(func=command_export)

    check = subparsers.add_parser("check", help="Validate the metadata tables")
    check.add_argument(
        "dir", type=Path, nargs="?", default=Path("metadata"),
        help="Metadata directory (default: metadata/)",
    )
    check.add_argument("-o", "--output", type=Path, help="Write the report here")
    check.add_argument("-f", "--format", choices=("text", "json"), default="text")
    check.add_argument(
        "--strict", action="store_true", help="Exit non-zero if any problem is found"
    )
    check.add_argument(
        "--emit", type=Path, metavar="JSON",
        help="Write linked, evidence-typed session records for downstream NDOS modules",
    )
    check.add_argument(
        "--include-empty", action="store_true",
        help="Include sessions with no entered metadata in --emit output",
    )
    check.set_defaults(func=command_check)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
