#!/usr/bin/env python3
"""Hand an N-DOS project off to BIDS and NWB workflows.

NDOS does not reimplement either standard. NWB conversion is a solved problem
with maintained tools, and rewriting it here would produce a worse converter
that nobody maintains. So this prepares the handoff instead:

    bids   build a BIDS-style tree of links, with dataset_description.json,
           participants.tsv and per-file sidecars
    nwb    emit a conversion plan that NeuroConv or a lab script can consume,
           with metadata already mapped onto NWB's fields
    check  report what each target still needs before it would be accepted

An honest caveat, stated in the output as well as here: the BIDS export is
BIDS-*shaped*, not a validated BIDS dataset. Animal electrophysiology is
covered by BEP032, which is not finalised, so no export can claim conformance
today. What this gives you is the entity mapping, the required top-level
files, and a report of what is missing.

Standard library only. Run it directly with no installation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ndos_organize
import ndos_scan

CONVERT_VERSION = "0.1"

#: NDOS role and data type mapped onto a BIDS datatype directory. Animal ephys
#: sits under BEP032's `ephys`; the rest follow existing BIDS practice.
BIDS_DATATYPE: Dict[str, str] = {
    "raw": "ephys",
    "lfp": "ephys",
    "spikes": "ephys",
    "video": "beh",
    "position": "beh",
    "behavior": "beh",
    "task": "beh",
    "experimenter": "beh",
    "timestamps": "ephys",
}

#: BIDS labels admit alphanumerics only.
LABEL = re.compile(r"[^A-Za-z0-9]+")

#: NDOS session directory name, as ndos_organize writes it.
SESSION_ID = re.compile(r"^(\d{8})(?:_(\d{2}|\d{6}))?$")


def _label(value: str) -> str:
    return LABEL.sub("", value) or "unknown"


def _parse_name(name: str) -> Tuple[Optional[str], Optional[str], str, str]:
    """Split SubjectID_SessionID_type-discriminator.ext into its parts.

    The discriminator that N-DOS appends to distinguish files sharing a type
    becomes a BIDS acq- entity rather than being lost, and must not be read as
    part of the type: "video-0" is a video.
    """
    # Original names carry dots of their own, as in
    # "position-Take-2020-11-22-06.32.30-PM.csv". Splitting on the first dot
    # truncated the stem and produced an extension of ".30-PM.csv".
    stem, _ = ndos_organize._split_extension(name)
    parts = stem.split("_")
    tail = "_".join(parts[2:]) if len(parts) >= 3 else stem
    subject = parts[0] if len(parts) >= 3 else None
    session = parts[1] if len(parts) >= 3 else None
    data_type, _, discriminator = tail.partition("-")
    return subject, session, data_type, discriminator


# --------------------------------------------------------------------------
# reading an NDOS project
# --------------------------------------------------------------------------

def read_project(root: Path) -> Dict[str, Any]:
    """Sessions and their files, as laid out by ndos_organize."""
    root = root.expanduser().resolve()
    sessions: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}

    for role in ("raw_data", "processed_data", "derivatives"):
        base = root / role
        if not base.is_dir():
            continue
        for subject_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            for session_dir in sorted(p for p in subject_dir.iterdir() if p.is_dir()):
                for path in sorted(session_dir.rglob("*")):
                    if not (path.is_file() or path.is_symlink()):
                        continue
                    if path.name in ("derived_metadata.json", "tags.json"):
                        continue
                    if "temp" in path.relative_to(session_dir).parts:
                        continue  # scratch is not published
                    _, _, data_type, acquisition = _parse_name(path.name)
                    sessions.setdefault((subject_dir.name, session_dir.name), []).append(
                        {
                            "path": str(path),
                            "name": path.name,
                            "role": role,
                            "data_type": data_type,
                            "acquisition": acquisition,
                            "suffix": ndos_organize._split_extension(path.name)[1],
                        }
                    )

    return {
        "root": str(root),
        "sessions": [
            {"subject": subject, "session": session, "files": files}
            for (subject, session), files in sorted(sessions.items())
        ],
    }


def read_metadata(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """Declared metadata keyed by subject, from ndos_table's linked output."""
    if not path or not path.is_file():
        return {}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    animals: Dict[str, Dict[str, Any]] = {}
    for session in content.get("sessions", []):
        animal = session.get("animal")
        if not animal:
            continue
        declared = {
            key: field.get("value")
            for key, field in animal.get("declared", {}).items()
        }
        animals[animal["subject_id"]] = declared
    return animals


def _session_start(session: str) -> Optional[str]:
    match = SESSION_ID.match(session)
    if not match:
        return None
    date = match.group(1)
    stamp = match.group(2)
    time = (
        f"{stamp[:2]}:{stamp[2:4]}:{stamp[4:6]}"
        if stamp and len(stamp) == 6 else "00:00:00"
    )
    return f"{date[:4]}-{date[4:6]}-{date[6:8]}T{time}"


# --------------------------------------------------------------------------
# BIDS
# --------------------------------------------------------------------------

def plan_bids(
    project: Dict[str, Any], destination: Path, metadata: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Map an N-DOS project onto BIDS entities, without writing anything."""
    destination = destination.expanduser().resolve()
    actions: List[Dict[str, Any]] = []
    warnings: List[str] = []
    subjects: Dict[str, Dict[str, Any]] = {}

    for session in project["sessions"]:
        subject = _label(session["subject"])
        label = _label(session["session"])
        subjects.setdefault(subject, metadata.get(session["subject"], {}))

        counters: Dict[str, int] = {}
        for item in session["files"]:
            datatype = BIDS_DATATYPE.get(item["data_type"])
            if datatype is None:
                warnings.append(
                    f"{item['name']}: no BIDS datatype maps to "
                    f"{item['data_type']!r}; left out of the export"
                )
                continue
            suffix = _label(item["data_type"])
            name = f"sub-{subject}_ses-{label}"
            if item.get("acquisition"):
                name += f"_acq-{_label(item['acquisition'])}"
            else:
                # Only files with no acquisition label need a run number to
                # tell them apart.
                counters[item["data_type"]] = counters.get(item["data_type"], 0) + 1
                if counters[item["data_type"]] > 1:
                    name += f"_run-{counters[item['data_type']]:02d}"
            name += f"_{suffix}{item['suffix']}"

            actions.append(
                {
                    "source": item["path"],
                    "target": str(
                        destination / f"sub-{subject}" / f"ses-{label}" / datatype / name
                    ),
                    "datatype": datatype,
                    "sidecar": str(
                        destination / f"sub-{subject}" / f"ses-{label}" / datatype
                        / (name.rsplit(".", 1)[0] + ".json")
                    ),
                    "subject": subject,
                    "session": label,
                }
            )

    return {
        "target": "bids",
        "destination": str(destination),
        "generated_at": ndos_scan._utc_iso(
            datetime.now(tz=timezone.utc).timestamp()
        ),
        "subjects": sorted(subjects),
        "session_count": len(project["sessions"]),
        "file_count": len(actions),
        "actions": actions,
        "warnings": warnings,
        "participants": subjects,
        "conformance": (
            "BIDS-shaped, not validated BIDS. Animal electrophysiology is "
            "covered by BEP032, which is not finalised, so no export can claim "
            "conformance today."
        ),
    }


def write_bids(plan: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
    """Build the BIDS-style tree from links, plus the files BIDS requires."""
    destination = Path(plan["destination"])
    destination.mkdir(parents=True, exist_ok=True)
    created: List[str] = []

    (destination / "dataset_description.json").write_text(
        json.dumps(
            {
                "Name": Path(plan["destination"]).name,
                "BIDSVersion": "1.9.0",
                "DatasetType": "raw",
                "GeneratedBy": [
                    {"Name": "ndos-convert", "Version": CONVERT_VERSION}
                ],
                "SourceDatasets": [{"URL": str(project_root)}],
                "HowToAcknowledge": plan["conformance"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    created.append(str(destination / "dataset_description.json"))

    columns = ["participant_id", "species", "sex", "strain", "genotype", "date_of_birth"]
    lines = ["\t".join(columns)]
    for subject in plan["subjects"]:
        declared = plan["participants"].get(subject, {})
        # BIDS uses n/a for values that were never recorded.
        lines.append(
            "\t".join(
                [f"sub-{subject}"]
                + [str(declared.get(column, "n/a") or "n/a") for column in columns[1:]]
            )
        )
    (destination / "participants.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    created.append(str(destination / "participants.tsv"))

    for action in plan["actions"]:
        target = Path(action["target"])
        target.parent.mkdir(parents=True, exist_ok=True)
        if not (target.exists() or target.is_symlink()):
            try:
                target.symlink_to(Path(action["source"]).resolve())
                created.append(str(target))
            except OSError:
                continue
        sidecar = Path(action["sidecar"])
        if not sidecar.exists():
            sidecar.write_text(
                json.dumps(
                    {
                        "NDOSSource": action["source"],
                        "GeneratedBy": "ndos-convert",
                        "Conformance": plan["conformance"],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            created.append(str(sidecar))

    return {"created": created, "created_count": len(created)}


# --------------------------------------------------------------------------
# NWB
# --------------------------------------------------------------------------

def plan_nwb(
    project: Dict[str, Any], metadata: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """A conversion plan with metadata already mapped onto NWB's fields."""
    conversions = []
    missing: List[str] = []

    for session in project["sessions"]:
        subject = session["subject"]
        declared = metadata.get(subject, {})
        start = _session_start(session["session"])
        identifier = f"{subject}_{session['session']}"

        required = {
            "session_start_time": start,
            "subject_id": subject,
            "species": declared.get("species"),
            "sex": declared.get("sex"),
            "date_of_birth": declared.get("date_of_birth"),
        }
        absent = [name for name, value in required.items() if not value]
        if absent:
            missing.append(f"{identifier}: {', '.join(absent)}")

        conversions.append(
            {
                "identifier": identifier,
                "nwbfile": {
                    "session_description": f"N-DOS session {session['session']}",
                    "identifier": identifier,
                    "session_start_time": start,
                    "session_id": session["session"],
                },
                "subject": {
                    "subject_id": subject,
                    "species": declared.get("species"),
                    "sex": declared.get("sex"),
                    "date_of_birth": declared.get("date_of_birth"),
                    "strain": declared.get("strain"),
                    "genotype": declared.get("genotype"),
                },
                "source_data": [
                    {
                        "path": item["path"],
                        "data_type": item["data_type"],
                        "role": item["role"],
                    }
                    for item in session["files"]
                ],
                "missing_required": absent,
            }
        )

    return {
        "target": "nwb",
        "generated_at": ndos_scan._utc_iso(
            datetime.now(tz=timezone.utc).timestamp()
        ),
        "generator": {"name": "ndos-convert", "version": CONVERT_VERSION},
        "note": (
            "A plan, not a conversion. Run it through NeuroConv or a lab "
            "script: NDOS does not reimplement NWB writing, which is already "
            "solved and maintained elsewhere."
        ),
        "session_count": len(conversions),
        "conversions": conversions,
        "missing_required": missing,
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render_bids(plan: Dict[str, Any]) -> str:
    out: List[str] = []
    add = out.append
    add("=" * 72)
    add("NDOS -> BIDS EXPORT PLAN")
    add("=" * 72)
    add(f"Destination : {plan['destination']}")
    add(f"Subjects    : {len(plan['subjects'])}  {', '.join(plan['subjects'][:8])}")
    add(f"Sessions    : {plan['session_count']}")
    add(f"Files       : {plan['file_count']}")
    add("")
    add("  " + plan["conformance"])
    add("")
    add("-" * 72)
    add("ENTITY MAPPING")
    add("-" * 72)
    for action in plan["actions"][:10]:
        add(f"  {Path(action['target']).relative_to(plan['destination'])}")
        add(f"      from {Path(action['source']).name}")
    if plan["file_count"] > 10:
        add(f"  ... and {plan['file_count'] - 10} more")

    if plan["warnings"]:
        add("")
        add("-" * 72)
        add(f"LEFT OUT ({len(plan['warnings'])})")
        add("-" * 72)
        for warning in plan["warnings"][:8]:
            add(f"  {warning}")
    add("")
    add("-" * 72)
    add("Nothing written. Run 'bids --write' to build the tree.")
    add("-" * 72)
    return "\n".join(out) + "\n"


def render_nwb(plan: Dict[str, Any]) -> str:
    out: List[str] = []
    add = out.append
    add("=" * 72)
    add("NDOS -> NWB CONVERSION PLAN")
    add("=" * 72)
    add(f"Sessions : {plan['session_count']}")
    add("")
    add("  " + plan["note"])
    add("")
    add("-" * 72)
    add("SESSIONS")
    add("-" * 72)
    for conversion in plan["conversions"][:10]:
        mark = "!" if conversion["missing_required"] else " "
        add(
            f" {mark} {conversion['identifier']}  "
            f"{len(conversion['source_data'])} files"
        )
        if conversion["missing_required"]:
            add(f"      missing: {', '.join(conversion['missing_required'])}")
    if plan["session_count"] > 10:
        add(f"  ... and {plan['session_count'] - 10} more")

    if plan["missing_required"]:
        add("")
        add("-" * 72)
        add("NOT READY TO CONVERT")
        add("-" * 72)
        add("  NWB requires these before a file can be written. Fill them in")
        add("  with ndos_table, then re-run.")
        for item in plan["missing_required"][:8]:
            add(f"    {item}")
    add("")
    add("-" * 72)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def command_bids(args: argparse.Namespace) -> int:
    project = read_project(args.project)
    plan = plan_bids(project, args.dest, read_metadata(args.metadata))
    print(render_bids(plan), end="")
    if args.save:
        args.save.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    if args.write:
        result = write_bids(plan, args.project)
        print(f"Wrote {result['created_count']} entries.", file=sys.stderr)
    return 0


def command_nwb(args: argparse.Namespace) -> int:
    project = read_project(args.project)
    plan = plan_nwb(project, read_metadata(args.metadata))
    if args.format == "json":
        print(json.dumps(plan, indent=2))
    else:
        print(render_nwb(plan), end="")
    if args.save:
        args.save.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"Plan written to {args.save}", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hand an N-DOS project off to BIDS and NWB workflows.",
        epilog=(
            "NDOS does not reimplement either standard; it prepares the "
            "handoff and reports what is still missing."
        ),
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    bids = subparsers.add_parser("bids", help="Export a BIDS-style tree")
    bids.add_argument("project", type=Path, help="N-DOS project root")
    bids.add_argument("-d", "--dest", type=Path, required=True)
    bids.add_argument("--metadata", type=Path, help="linked.json from ndos_table")
    bids.add_argument("--write", action="store_true", help="Actually build the tree")
    bids.add_argument("--save", type=Path, help="Write the plan to a file")
    bids.set_defaults(func=command_bids)

    nwb = subparsers.add_parser("nwb", help="Emit an NWB conversion plan")
    nwb.add_argument("project", type=Path, help="N-DOS project root")
    nwb.add_argument("--metadata", type=Path, help="linked.json from ndos_table")
    nwb.add_argument("--save", type=Path, help="Write the plan to a file")
    nwb.add_argument("-f", "--format", choices=("text", "json"), default="text")
    nwb.set_defaults(func=command_nwb)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
