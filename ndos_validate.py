#!/usr/bin/env python3
"""Check a project against the N-DOS standard.

The standard is only useful if a lab can tell whether they are following it.
This reports what does not conform, separating the requirements from the
recommendations, and says what to do about each.

    ndos validate ./my-study

Exits non-zero when a requirement is unmet, so it can gate a hand-off or a
submission. Recommendations never affect the exit code: a project may depart
from them deliberately and still conform.

See SPECIFICATION.md for what is being checked and why.

Standard library only. Run it directly with no installation.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ndos_init
import ndos_scan

SPEC_VERSION = "0.1"

#: The directories §1 requires, taken from the module that creates them so
#: the checker and the creator cannot disagree about what the standard is.
REQUIRED_DIRECTORIES = tuple(name for name, _ in ndos_init.DIRECTORIES)

#: The form §3 recommends for a SessionID.
SESSION_ID = re.compile(r"^\d{8}(_\d{2})?$")

#: A date whose day and month can be swapped, which §3 forbids.
SLASH_DATE = re.compile(r"\d{1,2}[/.]\d{1,2}[/.]\d{2,4}")

#: Files that legitimately sit at a project root or inside a session without
#: being acquisition data.
ALLOWED_LOOSE = {"README.md", "project.toml", "tags.json", "derived_metadata.json"}


def _requirement(code: str, message: str, fix: str, where: str = "") -> Dict[str, Any]:
    return {"level": "requirement", "code": code, "message": message,
            "fix": fix, "where": where}


def _recommendation(code: str, message: str, fix: str, where: str = "") -> Dict[str, Any]:
    return {"level": "recommendation", "code": code, "message": message,
            "fix": fix, "where": where}


def _check_structure(root: Path) -> List[Dict[str, Any]]:
    """§1: the directories and README a project must have."""
    findings = []
    missing = [name for name in REQUIRED_DIRECTORIES if not (root / name).is_dir()]
    if missing:
        findings.append(_requirement(
            "missing-directories",
            f"{len(missing)} of the required directories are absent: "
            + ", ".join(missing),
            f"ndos init {root} adds them without touching anything that is there",
        ))
    if not (root / "README.md").is_file():
        findings.append(_requirement(
            "missing-readme",
            "no README.md at the project root",
            f"ndos init {root} writes one describing the layout",
        ))
    return findings


def _sessions(root: Path) -> List[Tuple[str, str, Path]]:
    """Every (subject, session, path) under raw_data."""
    base = root / "raw_data"
    if not base.is_dir():
        return []
    found = []
    for subject in sorted(p for p in base.iterdir() if p.is_dir()):
        for session in sorted(p for p in subject.iterdir() if p.is_dir()):
            found.append((subject.name, session.name, session))
    return found


def _check_sessions(root: Path) -> List[Dict[str, Any]]:
    """§2 and §3: where data sits, and how sessions are named."""
    findings = []
    base = root / "raw_data"
    if not base.is_dir():
        return findings

    loose = [
        path for path in base.iterdir()
        if path.is_file() and path.name not in ALLOWED_LOOSE
    ]
    if loose:
        findings.append(_requirement(
            "data-outside-a-session",
            f"{len(loose)} files sit directly in raw_data/ rather than under "
            "<SubjectID>/<SessionID>/",
            "ndos organize plan will show where they belong",
            ", ".join(path.name for path in loose[:3]),
        ))

    for subject in sorted(p for p in base.iterdir() if p.is_dir()):
        stray = [
            path for path in subject.iterdir()
            if path.is_file() and path.name not in ALLOWED_LOOSE
        ]
        if stray:
            findings.append(_requirement(
                "data-outside-a-session",
                f"{len(stray)} files sit in raw_data/{subject.name}/ without a "
                "session directory",
                "put them under the session they were recorded in",
                f"raw_data/{subject.name}/",
            ))

    # A duplicate SessionID within one subject is a genuine failure: two
    # recordings that cannot be told apart.
    seen: Dict[str, List[str]] = {}
    for subject, session, _ in _sessions(root):
        seen.setdefault(subject, []).append(session)
        if SLASH_DATE.search(session):
            findings.append(_requirement(
                "ambiguous-date",
                f"session {session!r} contains a date whose day and month can "
                "be confused",
                "rename it to YYYYMMDD",
                f"raw_data/{subject}/{session}",
            ))
    return findings


def _check_recommendations(root: Path) -> List[Dict[str, Any]]:
    """The SHOULDs: worth knowing, never a failure."""
    findings = []
    sessions = _sessions(root)

    if (root / "raw_data").is_dir() and not sessions:
        findings.append(_recommendation(
            "no-data",
            "raw_data/ holds no sessions yet",
            f"ndos init {root} --subject M123 --date YYYY-MM-DD makes the first one",
        ))

    writable = []
    for _, _, path in sessions:
        for item in path.rglob("*"):
            if item.is_file() and not item.is_symlink():
                try:
                    if item.stat().st_mode & stat.S_IWUSR:
                        writable.append(item)
                except OSError:
                    continue
    if writable:
        findings.append(_recommendation(
            "raw-data-writable",
            f"{len(writable)} raw files can still be written to",
            f"ndos protect {root} --apply makes them read-only",
        ))

    unconventional = []
    for subject, session, path in sessions:
        expected = f"{subject}_{session}_"
        for item in path.iterdir():
            if item.is_dir() or item.name in ALLOWED_LOOSE:
                continue
            if not item.name.startswith(expected):
                unconventional.append(item.name)
    if unconventional:
        findings.append(_recommendation(
            "file-naming",
            f"{len(unconventional)} files are not named "
            "<SubjectID>_<SessionID>_<type>",
            "ndos organize applies the convention; files inside analysis-tool "
            "output are exempt and should stay as they are",
            ", ".join(unconventional[:3]),
        ))

    undated = [
        (subject, session) for subject, session, _ in sessions
        if not SESSION_ID.match(session)
    ]
    if undated:
        findings.append(_recommendation(
            "session-id-not-a-date",
            f"{len(undated)} sessions are not named as YYYYMMDD",
            "a dated identifier places a recording in time without opening "
            "anything. If you know the dates, put them in sessions.csv and "
            "re-run: ndos organize plan <source> -d <project> --dates <metadata>",
            ", ".join(f"{s}/{n}" for s, n in undated[:3]),
        ))

    metadata = root / "metadata"
    if metadata.is_dir() and not any(metadata.rglob("*")):
        findings.append(_recommendation(
            "no-metadata",
            "metadata/ is empty, so nothing records what these recordings are",
            f"ndos table export {root} -d {root}/metadata writes the sheets to fill in",
        ))
    return findings


def validate(root: Path) -> Dict[str, Any]:
    """Check a project, and say what does not conform."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    findings = _check_structure(root) + _check_sessions(root)
    findings += _check_recommendations(root)

    requirements = [f for f in findings if f["level"] == "requirement"]
    return {
        "spec_version": SPEC_VERSION,
        "root": str(root),
        "checked_at": ndos_scan._utc_iso(datetime.now(tz=timezone.utc).timestamp()),
        "conforms": not requirements,
        "session_count": len(_sessions(root)),
        "subject_count": len({subject for subject, _, _ in _sessions(root)}),
        "findings": findings,
    }


def render(result: Dict[str, Any]) -> str:
    out: List[str] = []
    add = out.append
    add("=" * 72)
    add(f"N-DOS {result['spec_version']} CONFORMANCE")
    add("=" * 72)
    add(f"Project  : {result['root']}")
    add(f"Contents : {result['subject_count']} subjects, {result['session_count']} sessions")
    add("")
    if result["conforms"]:
        add("  This project conforms to N-DOS " + result["spec_version"] + ".")
    else:
        add("  This project does not yet conform.")
    add("")

    for level, heading, note in (
        ("requirement", "REQUIRED", "These must be met to conform."),
        ("recommendation", "RECOMMENDED",
         "Worth knowing. A project may depart from these and still conform."),
    ):
        items = [f for f in result["findings"] if f["level"] == level]
        if not items:
            continue
        add("-" * 72)
        add(f"{heading} ({len(items)})")
        add("-" * 72)
        add(f"  {note}")
        add("")
        for finding in items:
            add(f"  {finding['message']}")
            if finding["where"]:
                add(f"      at    {finding['where']}")
            add(f"      fix   {finding['fix']}")
            add("")

    add("-" * 72)
    add("What is being checked, and why: SPECIFICATION.md")
    add("-" * 72)
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"Check a project against the N-DOS standard, version {SPEC_VERSION}.",
        epilog=(
            "Exits non-zero when a requirement is unmet. Recommendations never "
            "affect the exit code."
        ),
    )
    parser.add_argument("root", type=Path, nargs="?", default=Path("."))
    parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also exit non-zero when a recommendation is unmet",
    )
    args = parser.parse_args()

    try:
        result = validate(args.root)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    rendered = (
        json.dumps(result, indent=2) + "\n" if args.format == "json"
        else render(result)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")

    if not result["conforms"]:
        return 1
    if args.strict and any(
        f["level"] == "recommendation" for f in result["findings"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
