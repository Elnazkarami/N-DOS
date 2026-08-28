#!/usr/bin/env python3
"""Reconstruct a standard NDOS layout from whatever structure already exists.

An inventory describes a directory. It does not make the directory
understandable to a PI who inherited it. This builds the missing half: a clean
NDOS tree, derived from the original layout rather than imposed on it, that
someone can open in a file browser and read.

    raw_data/<subject>/<session>/raw/...
    processed_data/<subject>/<session>/...
    derivatives/  figures/  scripts/  metadata/
    unsorted/                      <- anything not confidently placed

By default nothing is copied or moved: the tree is built from symbolic links,
so 300 GB is organised in seconds, costs no disk space, and is undone by
deleting it. Copying and moving are available, planned and confirmed first.

Every placement records why it was made, and every file is placed somewhere.
Files that cannot be identified go to unsorted/ rather than being dropped.

Standard library only. Run it directly with no installation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ndos_report
import ndos_scan
import ndos_table
import ndos_tags

LAYOUT_VERSION = "0.1"
GENERATOR_VERSION = "0.1.0"

#: The NDOS layout as defined by the manuscript and by ndos_create.py on the
#: manuscript-2025 branch. This module reproduces that standard rather than
#: inventing one: raw_data, processed_data, analysis, figures and scripts come
#: from the scaffold script; derivatives, flagged_data and metadata are named
#: in the manuscript's directory overview.
RAW = "raw_data"
PROCESSED = "processed_data"
ANALYSIS = "analysis"
DERIVATIVES = "derivatives"
FLAGGED = "flagged_data"
FIGURES = "figures"
SCRIPTS = "scripts"
METADATA = "metadata"

#: Created by apply, in the order the manuscript lists them.
SCAFFOLD = (
    RAW, PROCESSED, ANALYSIS, DERIVATIVES, FLAGGED, FIGURES, SCRIPTS, METADATA,
)

README = """# N-DOS Project

This project follows the N-DOS layout.

| Directory | Contents |
| --- | --- |
| `raw_data/` | Immutable raw recordings, as `raw_data/<SubjectID>/<SessionID>/raw/` |
| `processed_data/` | Cleaned, sorted and pre-processed data |
| `analysis/` | Exploratory analyses and intermediate results |
| `derivatives/` | Validated, finalised analyses approved for sharing |
| `flagged_data/` | Corrupted, incomplete or uncertain data, each with a note |
| `figures/` | Visualisations generated from processed or derived data |
| `scripts/` | Code used for acquisition, preprocessing and analysis |
| `metadata/` | Experiment, acquisition and session descriptions |

Built by `ndos_organize.py` from an existing directory. Placements were derived
from the original folder structure; see `.ndos-layout-log.json` to undo.
"""

#: Path words that say what a file is for. Checked against the original
#: directory names, because that is where a lab records intent.
ROLE_WORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (PROCESSED, ("processed", "processed_data", "preprocessed", "sorted", "curated")),
    # The manuscript separates exploratory analysis from validated derivatives.
    (DERIVATIVES, ("derivative", "derivatives", "validated", "final")),
    (ANALYSIS, ("analysis", "analyses", "results", "exploratory")),
    (FLAGGED, ("flagged", "flagged_data", "bad", "corrupt", "suspect", "quarantine")),
    (FIGURES, ("figure", "figures", "plots", "graphs")),
    (SCRIPTS, ("script", "scripts", "code", "src", "notebook", "notebooks")),
    (METADATA, ("metadata", "meta", "config", "protocol", "protocols")),
    (RAW, ("raw", "raw_data", "acquisition", "acquired", "original")),
)

#: Content categories that imply a role when the path says nothing.
CATEGORY_ROLE: Dict[str, str] = {
    "Figures and images": FIGURES,
    "Code and notebooks": SCRIPTS,
    "Metadata and configuration": METADATA,
    "Notes and documents": METADATA,
    "Electrophysiology": RAW,
    "Imaging and video": RAW,
    "Motion capture and tracking": RAW,
    "Standard neurodata containers": RAW,
    "Arrays and analysis outputs": PROCESSED,
}

#: SessionID as the manuscript specifies it: YYYYMMDD, optionally with a
#: session number or acquisition time appended.
def _session_id(date: str, suffix: str = "") -> str:
    compact = date.replace("-", "")
    return f"{compact}_{suffix}" if suffix else compact

SUBJECT_PATTERNS = (
    re.compile(r"^(?:sub|subj|subject|animal|mouse|rat)[-_]?([A-Za-z0-9]+)$", re.I),
    re.compile(r"^([A-Za-z]{1,4}[-_]?\d{2,6}[a-z]?)$"),
)

DATE_PATTERNS = (
    re.compile(r"^(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})"),
    re.compile(r"^(\d{2})(\d{2})(\d{2})$"),
)

SESSION_PATTERNS = (
    re.compile(r"^(?:ses|sess|session)[-_]?(\d{1,4})$", re.I),
    re.compile(r"^(?:run|rec|recording|trial|block)[-_]?(\d{1,4})$", re.I),
)

TIME_PATTERN = re.compile(r"^(\d{2})[-_.](\d{2})[-_.](\d{2})$")

#: A subject folder above another subject-shaped folder is usually a cohort or
#: range, as in A0600/A0634. The deeper one is the animal.
COHORT_HINT = re.compile(r"^[A-Za-z]{1,4}\d{2,6}$")

#: Data-type suffixes named in the manuscript's naming conventions. Matched
#: on the filename and on the directories above it, most specific first: a
#: file called lfp.dat is LFP, not generic raw electrophysiology.
TYPE_RULES: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    # (type, filename/path keywords, extensions)
    ("spikes", ("spike", "cluster", "sorted", "kilosort", "phy", "mountainsort"), (".kwik", ".kwx")),
    ("lfp", ("lfp", "localfield", ".lf."), ()),
    ("position", ("position", "tracking", "optitrack", "take", "dlc", "deeplabcut", "pose"), (".tak", ".c3d", ".trc", ".anc", ".bvh")),
    ("task", ("task", "maze", "reward", "trial", "protocol"), ()),
    ("behavior", ("behavior", "behaviour"), ()),
    ("experimenter", ("experimenter", "keypress", "notes", "annotation"), ()),
    ("video", ("video", "miniscope", "camera"), (".avi", ".mp4", ".mov", ".mkv")),
    ("timestamps", ("timestamp", "timestamps"), ()),
    ("raw", ("raw", "amplifier", "continuous"), (
        ".rhd", ".rhs", ".ap", ".nev", ".ns5", ".ns6",
        # The manuscript names .nwb alongside .dat as raw electrophysiology.
        ".nwb", ".nix",
        # A zipped session is still raw acquisition data.
        ".zip", ".tar", ".tgz", ".tar.gz", ".gz",
    )),
)

#: Directories written by an analysis tool, recognised by the files that must
#: be present for that tool to read them back. Their internal filenames are an
#: interface, not a naming choice: Phy, Kilosort and SpikeInterface look for
#: `spike_times.npy` and `params.py` by name, so renaming them means the
#: sorting can no longer be opened. Everything below such a directory is kept
#: exactly as it is.
TOOL_OUTPUTS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Phy / Kilosort sorting", ("params.py", "spike_times.npy")),
    ("Phy / Kilosort sorting", ("spike_times.npy", "spike_clusters.npy")),
    ("SpikeInterface folder", ("si_folder.json",)),
    ("SpikeInterface folder", ("spikeinterface_info.json",)),
    ("SpikeInterface binary", ("binary.json",)),
    ("suite2p output", ("ops.npy", "stat.npy")),
    ("Open Ephys recording", ("structure.oebin",)),
    ("Zarr store", (".zgroup",)),
    ("Zarr store", (".zarray",)),
    ("Zarr store", ("zarr.json",)),
    ("DeepLabCut project", ("config.yaml", "dlc_config.yaml")),
)

#: Version markers a lab already writes into filenames, preserved rather than
#: discarded so a reprocessing is not silently flattened onto its predecessor.
VERSION_TOKEN = re.compile(r"[._-](v\d+|version\d+)$", re.I)

#: How many directory levels above a file may inform its data type.
NEARBY_SEGMENTS = 3

#: Recordings started within this many seconds are one session. Acquisition
#: systems in the same rig start seconds apart; that is not two sessions.
SESSION_GAP_SECONDS = 600

#: Characters that have no place in a standardised name.
UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

#: A date as the standard writes it.
ISO_DATE_TEXT = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Names like A0634_201122_183220: subject, then YYMMDD, then HHMMSS.
COMPOUND_SEGMENT = re.compile(r"^[A-Za-z]{1,4}\d{2,6}[-_](\d{6})[-_](\d{6})$")

#: Names like A3302-190809.zip: the animal and the date, in the filename, with
#: a two-digit year. A whole lab archived every session this way, and the
#: animal was nowhere in the folders -- the directory above held the cohort.
SUBJECT_DATE_NAME = re.compile(
    r"^([A-Za-z]{1,4}[-_]?\d{2,6}[a-z]?)[-_](\d{6})(?:[-_](\d{4,6}))?$"
)


# --------------------------------------------------------------------------
# derivation
# --------------------------------------------------------------------------

def _normalise_date(parts: Sequence[str]) -> Optional[str]:
    try:
        year, month, day = (int(part) for part in parts)
    except (TypeError, ValueError):
        return None
    if year < 100:
        year += 2000
    if not (1900 < year < 2200 and 1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _seconds(time: str) -> int:
    """HHMMSS as seconds past midnight."""
    return int(time[:2]) * 3600 + int(time[2:4]) * 60 + int(time[4:6])


def subject_and_session_from_name(
    filename: str,
) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """Read `A3302-190809.zip` as animal A3302 recorded on 2019-08-09.

    The filename is more specific than the folders around it: where a session
    is archived as one file, the directory above it is usually the cohort, so
    trusting the folder would label every animal with its group.
    """
    stem, _ = _split_extension(filename)
    match = SUBJECT_DATE_NAME.match(stem)
    if not match:
        return None, None, None

    digits = match.group(2)
    date = _normalise_date((digits[:2], digits[2:4], digits[4:]))
    if not date:
        return None, None, None

    session: Dict[str, Any] = {"date": date}
    time = match.group(3)
    if time and len(time) == 6:
        session["time"] = time
    return (
        match.group(1),
        session,
        f"filename {filename!r} names the animal and the date",
    )


def _names_a_session(segment: str) -> bool:
    """Whether a folder name is a session or run rather than a subject."""
    return any(pattern.match(segment) for pattern in SESSION_PATTERNS)


def _find_subject(segments: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    """The subject, and the reason it was chosen, from the original path."""
    candidates = []
    for segment in segments:
        # "ses-01" is letters followed by digits, so the generic identifier
        # pattern matches it. Taking the deepest match then read the session
        # as the animal and called the animal a cohort.
        if _names_a_session(segment):
            continue
        for pattern in SUBJECT_PATTERNS:
            match = pattern.match(segment)
            if match:
                candidates.append((segment, match.group(1)))
                break
    if not candidates:
        return None, None
    # With A0600/A0634 the outer folder is a cohort range; take the deepest.
    segment, value = candidates[-1]
    reason = f"folder {segment!r} matches a subject identifier"
    if len(candidates) > 1 and COHORT_HINT.match(candidates[0][0]):
        reason += f"; {candidates[0][0]!r} above it read as a cohort or range"
    return value, reason


def _find_session(
    segments: Sequence[str], filename: str = ""
) -> Tuple[Optional[str], Optional[str]]:
    """The session, preferring an explicit label, then a date, then date+time.

    Directories are searched first, then the filename: a session archived as
    `2020_11_20.zip` carries its date in the name and nowhere else.
    """
    # A segment such as A0634_201122_183220 holds subject, date and time in
    # one directory name. This shape appears throughout real lab storage.
    for segment in segments:
        compound = COMPOUND_SEGMENT.match(segment)
        if compound:
            candidate = _normalise_date(
                (compound.group(1)[:2], compound.group(1)[2:4], compound.group(1)[4:])
            )
            if candidate:
                return (
                    {"date": candidate, "time": compound.group(2)},
                    f"folder {segment!r} holds a subject, date and time",
                )

    date = None
    date_segment = None
    for segment in segments:
        for pattern in DATE_PATTERNS:
            match = pattern.match(segment)
            if match:
                candidate = _normalise_date(match.groups())
                if candidate:
                    date, date_segment = candidate, segment
                    break
        if date:
            break
    if not date and filename:
        stem = filename.rsplit(".", 1)[0]
        # A stem such as A0634_201122_183220 holds subject, date and time.
        compound = re.match(
            r"^[A-Za-z]{1,4}\d{2,6}[-_](\d{6})[-_](\d{6})$", stem
        )
        if compound:
            candidate = _normalise_date(
                (compound.group(1)[:2], compound.group(1)[2:4], compound.group(1)[4:])
            )
            if candidate:
                return (
                    {"date": candidate, "time": compound.group(2)},
                    f"filename {filename!r} holds a date and time",
                )
        for pattern in DATE_PATTERNS:
            match = pattern.match(stem)
            if match:
                candidate = _normalise_date(match.groups())
                if candidate:
                    return (
                        {"date": candidate},
                        f"filename {filename!r} reads as a date",
                    )

    if not date:
        # No date anywhere, so an explicitly numbered session is the best
        # identifier available. The standard prefers a date; where the data
        # does not carry one, inventing it would be worse.
        for segment in segments:
            for pattern in SESSION_PATTERNS:
                match = pattern.match(segment)
                if match:
                    return (
                        {"label": f"ses-{int(match.group(1)):02d}"},
                        f"folder {segment!r} names a session, and no date is "
                        "recorded in the path",
                    )
        return None, None

    for segment in segments:
        match = TIME_PATTERN.match(segment)
        if match:
            time = f"{match.group(1)}{match.group(2)}{match.group(3)}"
            return (
                {"date": date, "time": time},
                f"date {date_segment!r} with acquisition time {segment!r}",
            )
    return {"date": date}, f"folder {date_segment!r} reads as a date"


def _parse_session_label(segment: str) -> Tuple[Dict[str, Any], str]:
    """Read one directory name as a session, however it happens to be written.

    A user pointing at a level is telling us *where* the session is, not what
    shape it takes, so a date, a compound name and an arbitrary label all have
    to work.
    """
    compound = COMPOUND_SEGMENT.match(segment)
    if compound:
        date = _normalise_date(
            (compound.group(1)[:2], compound.group(1)[2:4], compound.group(1)[4:])
        )
        if date:
            return {"date": date, "time": compound.group(2)}, "read as a date and time"
    for pattern in DATE_PATTERNS:
        match = pattern.match(segment)
        if match:
            date = _normalise_date(match.groups())
            if date:
                return {"date": date}, "read as a date"
    for pattern in SESSION_PATTERNS:
        match = pattern.match(segment)
        if match:
            return {"label": f"ses-{int(match.group(1)):02d}"}, "read as a session number"
    # Not a shape we recognise, so it is used as written.
    return {"label": UNSAFE_NAME.sub("-", segment).strip("-.")}, "used as written"


def _find_role(segments: Sequence[str], category: str) -> Tuple[str, str]:
    """What the file is for: stated by the path if possible, else inferred."""
    lowered = [segment.lower() for segment in segments]
    for role, words in ROLE_WORDS:
        for segment in lowered:
            if segment in words:
                return role, f"folder {segment!r} says this is {role}"
    role = CATEGORY_ROLE.get(category)
    if role:
        return role, f"{category.lower()} is treated as {role}"
    return RAW, "no role stated; defaulting to raw"


def _split_extension(name: str) -> Tuple[str, str]:
    """Stem and suffix, keeping compound suffixes such as .ap.bin intact."""
    lowered = name.lower()
    for compound in (".tar.gz", ".tar.bz2", ".tar.xz", ".ap.bin", ".lf.bin", ".ap.meta", ".lf.meta"):
        if lowered.endswith(compound):
            return name[: -len(compound)], name[-len(compound):]
    stem, dot, suffix = name.rpartition(".")
    return (stem, dot + suffix) if dot else (name, "")


def _data_type(name: str, segments: Sequence[str], extension: str) -> Tuple[str, bool]:
    """The manuscript's data-type suffix for a file, and whether it is certain.

    Determined by the file itself — its extension, then its name — and never
    by the directories above it. Those decide the *role* (raw_data versus
    processed_data), which is a separate question. Mixing the two gave the
    same recording two different type labels depending on which copy of the
    tree it sat in.

    Falls back to a slug of the original name rather than forcing a file into
    a standard type it may not be. A wrong label on a filename is worse than
    an unfamiliar one, because it is what everyone reads first.
    """
    for label, _, extensions in TYPE_RULES:
        if extension in extensions:
            return label, True

    lowered = name.lower()
    for label, keywords, _ in TYPE_RULES:
        if any(keyword in lowered for keyword in keywords):
            return label, True

    stem, _ = _split_extension(name)
    slug = UNSAFE_NAME.sub("-", stem).strip("-.").lower()
    return (slug or "data"), False


def standard_name(
    subject: str,
    session: str,
    name: str,
    segments: Sequence[str],
    extension: str,
    discriminator: Optional[str] = None,
) -> Tuple[str, str, bool]:
    """`SubjectID_SessionID_type.ext`, as the manuscript's conventions specify.

    Returns the name, the reason, and whether the type is a standard one.
    """
    data_type, confident = _data_type(name, segments, extension)
    stem, suffix = _split_extension(name)
    version = ""
    marker = VERSION_TOKEN.search(stem)
    if marker:
        version = "_" + marker.group(1).lower()
    parts = f"{subject}_{session}_{data_type}"
    # A discriminator only helps when the type is a shared standard label.
    # Where the type was taken from the filename, repeating it would give
    # names like M01_20250314_analogin-analogin.dat.
    if discriminator and confident:
        parts += f"-{UNSAFE_NAME.sub('-', discriminator).strip('-.')}"
    reason = (
        f"named {data_type!r} by the N-DOS conventions"
        if confident
        else f"no standard data type applies; kept {data_type!r} from the original name"
    )
    if version:
        reason += f"; version marker {version.lstrip('_')!r} kept"
    return parts + version + suffix, reason, confident


def _target(
    role: str,
    subject: Optional[str],
    session: Optional[str],
    name: str,
    temporary: bool = False,
) -> Optional[str]:
    """Where a file belongs in the NDOS layout."""
    if temporary and subject and session:
        # The manuscript places spike-sorting scratch in a temp/ subdirectory
        # of the session, tagged for deletion after validation.
        return f"{PROCESSED}/{subject}/{session}/temp/{name}"
    if role in (FIGURES, SCRIPTS, METADATA):
        if subject and session:
            return f"{role}/{subject}/{session}/{name}"
        return f"{role}/{name}"
    if not subject or not session:
        return None
    # raw_data/SubjectID/SessionID/acquisition_files, per the manuscript.
    return f"{role}/{subject}/{session}/{name}"


def find_tool_outputs(files: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """Directory prefixes that belong to an analysis tool, and what wrote them.

    Renaming inside one of these breaks the tool that produced it, so they are
    carried across whole. Detection is by the marker files each tool requires,
    which is also how the tools themselves recognise their own output.
    """
    by_directory: Dict[str, set] = {}
    for entry in files:
        parts = entry["path"].split("/")
        prefix = "/".join(parts[:-1])
        by_directory.setdefault(prefix, set()).add(parts[-1])

    found: Dict[str, str] = {}
    for prefix, names in by_directory.items():
        for label, markers in TOOL_OUTPUTS:
            if all(marker in names for marker in markers):
                found[prefix] = label
                break
    return found


def _owning_tool_output(path: str, outputs: Dict[str, str]) -> Optional[str]:
    """The tool-output directory a file sits in, if any."""
    parts = path.split("/")[:-1]
    for depth in range(len(parts), 0, -1):
        prefix = "/".join(parts[:depth])
        if prefix in outputs:
            return prefix
    return None


def read_declared_dates(source: Path) -> Dict[str, str]:
    """Session dates a person recorded, keyed by the path they describe.

    A folder named only `ses-01` says a session happened but not when. Once
    someone writes the date in sessions.csv, that is the missing fact, and the
    layout can carry it: an identifier that says when a recording happened is
    what makes a session locatable in time without opening anything.
    """
    source = Path(source).expanduser()
    if source.is_dir():
        source = source / ndos_table.SESSIONS_FILE
    if not source.is_file():
        return {}

    dates: Dict[str, str] = {}
    if source.suffix.lower() == ".json":
        try:
            content = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        for session in content.get("sessions", []):
            path = session.get("observed", {}).get("path", "")
            declared = session.get("declared", {}).get("session_date", {})
            if path and declared.get("value"):
                dates[path] = declared["value"]
        return dates

    try:
        for row in ndos_table.read_table(source):
            path = (row.get("observed_path") or "").strip()
            date = (row.get("session_date") or "").strip()
            if path and date:
                dates[path] = date
    except (OSError, ValueError):
        return {}
    return dates


def _declared_for(path: str, dates: Dict[str, str]) -> Optional[Tuple[str, str]]:
    """The recorded date covering a file, and the path it was recorded against."""
    parts = path.split("/")[:-1]
    for depth in range(len(parts), 0, -1):
        prefix = "/".join(parts[:depth])
        if prefix in dates:
            return dates[prefix], prefix
    return None


def _at_depth(directories: Sequence[str], depth: Optional[int]) -> Optional[str]:
    """The directory name at a given level, if the path is that deep."""
    if depth is None or depth < 0 or len(directories) <= depth:
        return None
    return directories[depth]


def derive(
    manifest: Dict[str, Any],
    strip_prefix: int = 0,
    standard_names: bool = True,
    subject_depth: Optional[int] = None,
    session_depth: Optional[int] = None,
    declared_dates: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Decide where every file belongs, and say why.

    Runs in two passes. The first identifies subject, session and role for
    each file; the second assigns SessionID. Numbering has to be global,
    because "was this the first or second recording that day?" cannot be
    answered from one file's path alone.
    """
    tool_outputs = find_tool_outputs(manifest["files"])

    found = []
    for entry in manifest["files"]:
        segments = entry["path"].split("/")
        directories = segments[:-1][strip_prefix:]
        name = segments[-1]
        category = ndos_report.categorise(entry["extension"], name)

        # An explicit depth overrides the guess. Real layouts exist that no
        # heuristic will read correctly, and a user who can see the mistake
        # needs a way to say so.
        named_subject, named_session, named_reason = (
            subject_and_session_from_name(name)
        )

        forced_subject = _at_depth(directories, subject_depth)
        if forced_subject is not None:
            subject = forced_subject
            subject_reason = f"folder {forced_subject!r} at level {subject_depth}, as you specified"
        elif named_subject:
            subject, subject_reason = named_subject, named_reason
        else:
            subject, subject_reason = _find_subject(directories)
            if subject_depth is not None:
                subject_reason = (
                    f"no level {subject_depth} in this path"
                    + (f"; fell back to {subject_reason}" if subject_reason else "")
                )

        forced_session = _at_depth(directories, session_depth)
        if forced_session is not None:
            session, session_reason = _parse_session_label(forced_session)
            session_reason = (
                f"folder {forced_session!r} at level {session_depth}, as you "
                f"specified ({session_reason})"
            )
        elif named_session:
            session, session_reason = named_session, named_reason
        else:
            session, session_reason = _find_session(directories, name)

        # A date somebody recorded outranks a bare label the folder happened
        # to carry: it is the fact the path was missing.
        if declared_dates and (not session or "date" not in session):
            declared = _declared_for(entry["path"], declared_dates)
            if declared:
                value, against = declared
                if ISO_DATE_TEXT.match(value):
                    session = {"date": value}
                    session_reason = (
                        f"date {value} recorded for {against!r} in the metadata; "
                        "the folder name did not carry one"
                    )
        role, role_reason = _find_role(directories, category)

        found.append(
            {
                "entry": entry,
                "name": name,
                "category": category,
                "subject": subject,
                "session": session,
                "role": role,
                "reasons": [
                    reason for reason in (subject_reason, session_reason, role_reason)
                    if reason
                ],
            }
        )

    # Which acquisition times exist for each subject and date.
    times: Dict[Tuple[str, str], set] = {}
    for item in found:
        session = item["session"]
        if not item["subject"] or not session or "date" not in session:
            continue
        key = (item["subject"], session["date"])
        times.setdefault(key, set())
        if session.get("time"):
            times[key].add(session["time"])

    # Collapse times that are moments apart into one session.
    groups: Dict[Tuple[str, str], List[List[str]]] = {}
    for key, values in times.items():
        clustered: List[List[str]] = []
        for time in sorted(values):
            if clustered and _seconds(time) - _seconds(clustered[-1][-1]) <= SESSION_GAP_SECONDS:
                clustered[-1].append(time)
            else:
                clustered.append([time])
        groups[key] = clustered

    for item in found:
        session = item["session"]
        subject = item["subject"]
        reasons = list(item["reasons"])
        session_id = None

        if session and "label" in session:
            session_id = session["label"]
        elif session and subject:
            date = session["date"]
            clustered = groups.get((subject, date), [])
            if len(clustered) <= 1:
                # One recording that day, so the date alone identifies it.
                session_id = _session_id(date)
                if clustered and len(clustered[0]) > 1:
                    reasons.append(
                        f"acquisition times {', '.join(clustered[0])} are within "
                        "minutes of each other, so they are one session"
                    )
            elif session.get("time"):
                number = next(
                    index for index, group in enumerate(clustered, start=1)
                    if session["time"] in group
                )
                session_id = _session_id(date, f"{number:02d}")
                reasons.append(
                    f"{len(clustered)} separate recordings on {date}; this is "
                    f"number {number}, started {session['time']}"
                )
            else:
                # A file that names the date but no time, on a day with
                # several recordings. Which one it belongs to is unknown.
                session_id = None
                reasons.append(
                    f"{len(clustered)} separate recordings on {date} and this "
                    "path gives no time, so which one it belongs to cannot be "
                    "determined"
                )

        item["session_id"] = session_id
        item["reasons"] = reasons
        item["subject_final"] = subject

    if standard_names:
        # How many files of each type land in one session, so a discriminator
        # is added only where it is genuinely needed.
        counts: Counter = Counter()
        for item in found:
            if item["subject_final"] and item.get("session_id"):
                proposed, _, _ = standard_name(
                    item["subject_final"], item["session_id"], item["name"],
                    item["entry"]["path"].split("/")[:-1], item["entry"]["extension"],
                )
                item["proposed"] = proposed
                counts[(item["subject_final"], item["session_id"], proposed)] += 1

    placements = []
    for item in found:
        subject = item["subject_final"]
        session_id = item.get("session_id")
        reasons = item["reasons"]
        filename = item["name"]

        owner = _owning_tool_output(item["entry"]["path"], tool_outputs)
        if owner:
            # Kept exactly as written, including the path below the tool's
            # own directory, so the tool can still open its own output.
            relative = item["entry"]["path"][len(owner) + 1 :]
            directory = owner.split("/")[-1]
            reasons.append(
                f"{tool_outputs[owner]} output: {directory}/ is carried across "
                "unchanged, because renaming inside it would stop the tool "
                "reading it back"
            )
            target = (
                f"{PROCESSED}/{subject}/{session_id}/{directory}/{relative}"
                if subject and session_id
                else f"{FLAGGED}/{item['entry']['path']}"
            )
            placements.append(
                {
                    "source": item["entry"]["path"],
                    "target": target,
                    "subject": subject,
                    "session": session_id,
                    "role": PROCESSED,
                    "category": item["category"],
                    "size_bytes": item["entry"]["size_bytes"],
                    "original_name": item["name"],
                    "temporary": False,
                    "tool_output": tool_outputs[owner],
                    "placed": not target.startswith(f"{FLAGGED}/"),
                    "why": reasons,
                }
            )
            continue

        if standard_names and subject and session_id:
            proposed = item.get("proposed")
            crowded = counts[(subject, session_id, proposed)] > 1
            discriminator = _split_extension(filename)[0] if crowded else None
            filename, naming_reason, confident = standard_name(
                subject, session_id, item["name"],
                item["entry"]["path"].split("/")[:-1], item["entry"]["extension"],
                discriminator=discriminator,
            )
            reasons.append(naming_reason)
            if crowded and confident:
                reasons.append(
                    f"several files share this type in the session, so the "
                    f"original name {_split_extension(item['name'])[0]!r} "
                    "distinguishes it"
                )

        temporary = ndos_tags.looks_temporary(Path(item["entry"]["path"]))
        if temporary:
            reasons.append(
                "scratch by convention, so it goes to the session's temp/ "
                "directory and is tagged temporary"
            )

        target = _target(
            item["role"], subject, session_id, filename, temporary=temporary
        )
        if target is None:
            missing = "subject" if not subject else "session"
            target = f"{FLAGGED}/{item['entry']['path']}"
            reasons.append(
                f"no {missing} could be identified from the path, so this is "
                f"{FLAGGED}/ — uncertain, per the N-DOS layout"
            )

        placements.append(
            {
                "source": item["entry"]["path"],
                "target": target,
                "subject": subject,
                "session": session_id,
                "role": item["role"],
                "category": item["category"],
                "size_bytes": item["entry"]["size_bytes"],
                "original_name": item["name"],
                "temporary": temporary,
                "placed": not target.startswith(f"{FLAGGED}/"),
                "why": reasons,
            }
        )
    return placements


# --------------------------------------------------------------------------
# planning
# --------------------------------------------------------------------------

def build_plan(
    manifest: Dict[str, Any],
    destination: Path,
    mode: str = "link",
    strip_prefix: int = 0,
    standard_names: bool = True,
    subject_depth: Optional[int] = None,
    session_depth: Optional[int] = None,
    declared_dates: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """A complete, reviewable description of the tree that would be built."""
    source_root = Path(manifest["source_root"])
    destination = destination.expanduser().resolve()
    placements = derive(
        manifest,
        strip_prefix=strip_prefix,
        standard_names=standard_names,
        subject_depth=subject_depth,
        session_depth=session_depth,
        declared_dates=declared_dates,
    )

    by_source = {entry["path"]: entry for entry in manifest["files"]}
    seen: Dict[str, Dict[str, Any]] = {}
    collisions: List[Dict[str, str]] = []
    duplicates: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []

    def _same_file(left: str, right: str) -> Optional[bool]:
        """Whether two source files are the same content, if we can tell."""
        first, second = by_source.get(left), by_source.get(right)
        if not first or not second:
            return None
        if "sha256" in first and "sha256" in second:
            return first["sha256"] == second["sha256"]
        if first["size_bytes"] != second["size_bytes"]:
            return False
        return None  # same size, but without checksums we cannot be sure

    for placement in placements:
        target = placement["target"]
        previous = seen.get(target)
        if previous is not None:
            identical = _same_file(previous["source"], placement["source"])
            if identical is not False:
                # A lab that restructured its data once has the same recording
                # in two places. Linking it twice under invented names would
                # present redundancy as if it were distinct data.
                duplicates.append(
                    {
                        "target": target,
                        "kept": previous["source"],
                        "duplicate": placement["source"],
                        "confirmed": bool(identical),
                        "size_bytes": placement["size_bytes"],
                    }
                )
                continue

            stem, _, suffix = target.rpartition(".")
            unique = Path(placement["source"]).parent.name
            target = (
                f"{stem}__{unique}.{suffix}" if stem and suffix
                else f"{target}__{unique}"
            )
            collisions.append(
                {
                    "target": placement["target"],
                    "first": previous["source"],
                    "second": placement["source"],
                    "renamed_to": target,
                }
            )
        seen[target] = placement

        actions.append(
            {
                "source": str(source_root / placement["source"]),
                "target": str(destination / target),
                "relative_target": target,
                "size_bytes": placement["size_bytes"],
                "subject": placement["subject"],
                "session": placement["session"],
                "role": placement["role"],
                "temporary": placement.get("temporary", False),
                "tool_output": placement.get("tool_output"),
                "placed": placement["placed"],
                "why": placement["why"],
            }
        )

    placed = [a for a in actions if a["placed"]]
    unsorted = [a for a in actions if not a["placed"]]
    subjects = sorted({a["subject"] for a in placed if a["subject"]})
    sessions = sorted({(a["subject"], a["session"]) for a in placed if a["session"]})

    bytes_needed = sum(a["size_bytes"] for a in actions) if mode == "copy" else 0
    try:
        free = shutil.disk_usage(
            destination if destination.exists() else destination.parent
        ).free
    except OSError:
        free = None

    return {
        "layout_version": LAYOUT_VERSION,
        "generated_at": ndos_scan._utc_iso(datetime.now(tz=timezone.utc).timestamp()),
        "generator": {"name": "ndos-organize", "version": GENERATOR_VERSION},
        "source_root": str(source_root),
        "destination": str(destination),
        "mode": mode,
        # Every file in the source, including ones dropped as redundant, so
        # the total always reconciles with the inventory.
        "file_count": len(placements),
        "action_count": len(actions),
        "placed_count": len(placed),
        "unsorted_count": len(unsorted),
        "subjects": subjects,
        "session_count": len(sessions),
        "roles": dict(Counter(a["role"] for a in placed)),
        "collisions": collisions,
        "duplicates": duplicates,
        "duplicate_bytes": sum(d["size_bytes"] for d in duplicates),
        "bytes_needed": bytes_needed,
        "free_bytes": free,
        "enough_space": None if free is None or not bytes_needed else free > bytes_needed * 1.05,
        "actions": actions,
    }


# --------------------------------------------------------------------------
# applying
# --------------------------------------------------------------------------

def apply_plan(
    plan: Dict[str, Any], progress: bool = True
) -> Dict[str, Any]:
    """Build the tree. Records everything it creates so it can be undone."""
    mode = plan["mode"]
    destination = Path(plan["destination"])
    created: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []

    # The full N-DOS scaffold, so the project is recognisable even where a
    # directory happens to be empty for this dataset.
    destination.mkdir(parents=True, exist_ok=True)
    for name in SCAFFOLD:
        (destination / name).mkdir(exist_ok=True)
    readme = destination / "README.md"
    # Recorded as created only when we actually wrote it, so undo never
    # deletes a README that was already there.
    scaffold_files: List[str] = []
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")
        scaffold_files.append(str(readme))

    for index, action in enumerate(plan["actions"], start=1):
        source = Path(action["source"])
        target = Path(action["target"])

        if target.exists() or target.is_symlink():
            skipped.append({"target": str(target), "reason": "already exists"})
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "link":
                # Absolute, so the view keeps working if it is moved.
                target.symlink_to(source)
            elif mode == "copy":
                shutil.copy2(source, target)
            elif mode == "move":
                shutil.move(str(source), str(target))
            else:
                raise ValueError(f"unknown mode {mode!r}")
            created.append({"target": str(target), "source": str(source)})
        except (OSError, ValueError) as error:
            failed.append({"target": str(target), "reason": str(error)})

        if progress and index % 500 == 0:
            print(f"  ...{index}/{len(plan['actions'])}", file=sys.stderr)

    # The manuscript places a derived_metadata.json in each processed session,
    # documenting how the contents came to be there.
    sessions: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for action in plan["actions"]:
        # Scratch lands under processed_data regardless of the role its
        # content implies, so it belongs in that session's record too.
        in_processed = action["role"] == PROCESSED or action.get("temporary")
        if not in_processed or not action["subject"] or not action["session"]:
            continue
        sessions.setdefault((action["subject"], action["session"]), []).append(action)

    for (subject, session), members in sessions.items():
        record = destination / PROCESSED / subject / session / "derived_metadata.json"
        if record.exists():
            continue
        try:
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(
                json.dumps(
                    {
                        "subject_id": subject,
                        "session_id": session,
                        "generated_at": ndos_scan._utc_iso(
                            datetime.now(tz=timezone.utc).timestamp()
                        ),
                        "generator": {
                            "name": "ndos-organize", "version": GENERATOR_VERSION
                        },
                        "source_root": plan["source_root"],
                        "mode": mode,
                        "files": [
                            {
                                "name": Path(item["target"]).name,
                                "original": item["source"],
                                "temporary": item.get("temporary", False),
                                "why": item["why"],
                            }
                            for item in members
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            scaffold_files.append(str(record))
        except OSError:
            pass

    # Scratch is tagged where it lands, so a sweep can find it later without
    # anyone having to remember which files were intermediates.
    temporary = [a for a in plan["actions"] if a.get("temporary")]
    for action in temporary:
        target = Path(action["target"])
        if not target.exists() and not target.is_symlink():
            continue
        try:
            ndos_tags.set_tags(
                target, {"temp": True},
                note="placed in temp/ by ndos_organize; not validated",
                author="ndos-organize",
            )
        except (ndos_tags.TagError, OSError):
            pass
    if temporary:
        directories = {str(Path(a["target"]).parent) for a in temporary}
        for directory in directories:
            candidate = Path(directory) / ndos_tags.TAGS_FILE
            if candidate.exists():
                scaffold_files.append(str(candidate))

    flagged = [a for a in plan["actions"] if not a["placed"]]
    if flagged:
        # The N-DOS layout specifies a note describing why data is flagged.
        note = destination / FLAGGED / "flagged_notes.json"
        try:
            note.parent.mkdir(parents=True, exist_ok=True)
            wrote_note = not note.exists()
            note.write_text(
                json.dumps(
                    {
                        "generated_at": ndos_scan._utc_iso(
                            datetime.now(tz=timezone.utc).timestamp()
                        ),
                        "reason": (
                            "Subject or session could not be identified from the "
                            "original path. Original structure is preserved here."
                        ),
                        "files": [
                            {"target": a["relative_target"], "why": a["why"]}
                            for a in flagged
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            if wrote_note:
                scaffold_files.append(str(note))
        except OSError:
            pass

    return {
        "mode": mode,
        "destination": plan["destination"],
        "applied_at": ndos_scan._utc_iso(datetime.now(tz=timezone.utc).timestamp()),
        "created": created,
        "created_count": len(created),
        "scaffold_files": scaffold_files,
        "skipped": skipped,
        "failed": failed,
    }


def undo(log: Dict[str, Any], progress: bool = True) -> Dict[str, Any]:
    """Reverse an applied plan using its own record of what it created."""
    mode = log["mode"]
    removed, restored, failed = 0, 0, []

    for record in reversed(log["created"]):
        target = Path(record["target"])
        try:
            if mode == "move":
                source = Path(record["source"])
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
                restored += 1
            else:
                if target.is_symlink() or target.exists():
                    target.unlink()
                    removed += 1
        except OSError as error:
            failed.append({"target": str(target), "reason": str(error)})

    for path in log.get("scaffold_files", []):
        try:
            Path(path).unlink()
            removed += 1
        except OSError:
            pass

    # Clear the directories the plan created, deepest first, but only ones
    # that are now empty: never remove anything holding unrelated files.
    destination = Path(log["destination"])
    if destination.exists():
        for directory in sorted(
            (p for p in destination.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts), reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            destination.rmdir()
        except OSError:
            pass

    return {"removed": removed, "restored": restored, "failed": failed}


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_bytes = ndos_scan._human_bytes


def render_plan(
    plan: Dict[str, Any], limit: int = 15, footer: bool = True
) -> str:
    out: List[str] = []
    add = out.append

    verb = {
        "link": "linked to, not moved",
        "copy": "copied",
        "move": "MOVED out of their original locations",
    }[plan["mode"]]

    add("=" * 72)
    add("NDOS LAYOUT PLAN")
    add("=" * 72)
    add(f"From        : {plan['source_root']}")
    add(f"To          : {plan['destination']}")
    add(f"Mode        : {plan['mode']}  (files will be {verb})")
    duplicate_count = len(plan.get("duplicates", []))
    breakdown = f"{plan['placed_count']:,} placed"
    if plan["unsorted_count"]:
        breakdown += f", {plan['unsorted_count']:,} flagged"
    if duplicate_count:
        breakdown += f", {duplicate_count:,} redundant copies"
    add(f"Files       : {plan['file_count']:,} in source ({breakdown})")
    add(f"Subjects    : {len(plan['subjects'])}  {', '.join(plan['subjects'][:8])}")
    add(f"Sessions    : {plan['session_count']}")
    if plan["mode"] == "copy":
        add(f"Disk needed : {_bytes(plan['bytes_needed'])}")
        if plan["free_bytes"] is not None:
            add(f"Free        : {_bytes(plan['free_bytes'])}")
            if plan["enough_space"] is False:
                add("")
                add("  *** NOT ENOUGH SPACE. Use --mode link instead. ***")
    elif plan["mode"] == "link":
        add("Disk needed : none; the tree is symbolic links to the originals")

    add("")
    add("-" * 72)
    add("STRUCTURE THAT WOULD BE BUILT")
    add("-" * 72)
    for role, count in sorted(plan["roles"].items(), key=lambda item: -item[1]):
        add(f"  {role + '/':<20}{ndos_report._plural(count, 'file'):>14}")
    if plan["unsorted_count"]:
        add(
            f"  {FLAGGED + '/':<20}"
            f"{ndos_report._plural(plan['unsorted_count'], 'file'):>14}"
            "   (subject or session unidentified)"
        )

    add("")
    add("-" * 72)
    add("EXAMPLE PLACEMENTS, AND WHY")
    add("-" * 72)
    shown = [a for a in plan["actions"] if a["placed"]][:limit]
    for action in shown:
        add(f"  {action['relative_target']}")
        add(f"      from  {Path(action['source']).name}")
        for reason in action["why"]:
            add(f"      why   {reason}")
    if plan["placed_count"] > len(shown):
        add(f"  ... and {plan['placed_count'] - len(shown):,} more")

    tools: Dict[str, int] = {}
    for action in plan["actions"]:
        label = action.get("tool_output")
        if label:
            tools[label] = tools.get(label, 0) + 1
    if tools:
        add("")
        add("-" * 72)
        add("TOOL OUTPUT, CARRIED ACROSS UNCHANGED")
        add("-" * 72)
        add("  These were written by an analysis tool that reads its own files")
        add("  back by name. Renaming inside them would break that, so they")
        add("  keep their filenames and internal structure exactly.")
        for label, count in sorted(tools.items(), key=lambda item: -item[1]):
            add(f"    {ndos_report._plural(count, 'file'):>12}  {label}")

    if plan.get("duplicates"):
        confirmed = sum(1 for d in plan["duplicates"] if d["confirmed"])
        add("")
        add("-" * 72)
        add(f"REDUNDANT COPIES ({len(plan['duplicates'])})")
        add("-" * 72)
        add(
            f"  {_bytes(plan['duplicate_bytes'])} of the source is the same data "
            "in more than"
        )
        add("  one place. Each is linked once; the others are listed here.")
        if confirmed < len(plan["duplicates"]):
            add("  Sizes match but checksums were not computed, so this is")
            add("  likely rather than proven. Scan without --no-checksum to confirm.")
        for item in plan["duplicates"][:5]:
            add(f"    {item['target']}")
            add(f"        also at {item['duplicate']}")
        if len(plan["duplicates"]) > 5:
            add(f"    ... and {len(plan['duplicates']) - 5} more")

    if plan["collisions"]:
        add("")
        add("-" * 72)
        add(f"NAME COLLISIONS ({len(plan['collisions'])})")
        add("-" * 72)
        add("  Two files wanted the same place. Both are kept; the second is")
        add("  renamed rather than overwriting the first.")
        for collision in plan["collisions"][:5]:
            add(f"    {collision['target']}")
            add(f"        second copy renamed to {Path(collision['renamed_to']).name}")

    if plan["unsorted_count"]:
        add("")
        add("-" * 72)
        add(f"FLAGGED ({plan['unsorted_count']:,})")
        add("-" * 72)
        add("  No subject or session could be read from these paths, so they are")
        add("  placed in flagged_data/ with their original structure intact.")
        add("  Nothing is dropped, and each keeps a note saying why.")
        for action in [a for a in plan["actions"] if not a["placed"]][:5]:
            add(f"    {Path(action['source']).name}")

    if footer:
        add("")
        add("-" * 72)
        add("Nothing has been created. To build this tree, run 'apply'.")
        add("-" * 72)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def _load_manifest(source: Path, quiet: bool) -> Dict[str, Any]:
    if source.is_dir():
        if not quiet:
            print(f"Scanning {source} (read-only)...", file=sys.stderr)
        return ndos_scan.scan(source, include_checksums=False, progress=not quiet)
    return json.loads(source.read_text(encoding="utf-8"))


def command_plan(args: argparse.Namespace) -> int:
    manifest = _load_manifest(args.source, args.quiet)
    plan = build_plan(
        manifest, args.dest, mode=args.mode, strip_prefix=args.strip,
        standard_names=not args.keep_original_names,
        subject_depth=args.subject_depth, session_depth=args.session_depth,
        declared_dates=read_declared_dates(args.dates) if args.dates else None,
    )
    rendered = (
        json.dumps(plan, indent=2) + "\n" if args.format == "json"
        else render_plan(plan)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"Plan saved to {args.save}", file=sys.stderr)
    return 0


def command_apply(args: argparse.Namespace) -> int:
    if args.plan_file:
        plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
    else:
        manifest = _load_manifest(args.source, args.quiet)
        plan = build_plan(
            manifest, args.dest, mode=args.mode, strip_prefix=args.strip,
            standard_names=not args.keep_original_names,
            subject_depth=args.subject_depth, session_depth=args.session_depth,
            declared_dates=read_declared_dates(args.dates) if args.dates else None,
        )

    # Without footer=False this ended a successful run by telling the user to
    # run the command they had just run.
    print(render_plan(plan, footer=False), end="")

    if plan["mode"] == "copy" and plan["enough_space"] is False and not args.force:
        print(
            "Refusing to start: not enough free space. Use --mode link, which "
            "needs none, or pass --force.",
            file=sys.stderr,
        )
        return 1

    if not args.yes:
        warning = (
            "\nThis MOVES files out of their original locations. "
            if plan["mode"] == "move" else "\n"
        )
        try:
            answer = input(
                f"{warning}Build this tree at {plan['destination']}? [y/N] "
            )
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was created.", file=sys.stderr)
            return 1

    log = apply_plan(plan, progress=not args.quiet)
    log_path = Path(plan["destination"]) / ".ndos-layout-log.json"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2) + "\n", encoding="utf-8")
    except OSError:
        log_path = None

    print(
        f"\nCreated {log['created_count']:,} entries. "
        f"Skipped {len(log['skipped'])}, failed {len(log['failed'])}.",
        file=sys.stderr,
    )
    if log_path:
        print(f"Undo with: {ndos_scan.invocation('ndos_organize')} undo {log_path}",
            file=sys.stderr,
        )
    return 1 if log["failed"] else 0


def command_undo(args: argparse.Namespace) -> int:
    log = json.loads(args.log.read_text(encoding="utf-8"))
    if not args.yes:
        try:
            answer = input(
                f"Undo {len(log['created']):,} entries at {log['destination']}? [y/N] "
            )
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled.", file=sys.stderr)
            return 1

    result = undo(log, progress=not args.quiet)
    print(
        f"Removed {result['removed']:,}, restored {result['restored']:,}, "
        f"failed {len(result['failed'])}.",
        file=sys.stderr,
    )
    return 1 if result["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconstruct a standard NDOS layout from an existing directory.",
        epilog=(
            "The default mode builds the tree from symbolic links: instant, no "
            "disk space, and undone by deleting it. Source data is untouched "
            "unless you choose --mode move."
        ),
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    common = lambda p: (
        p.add_argument("source", type=Path, help="manifest.json, or a directory to scan"),
        p.add_argument("-d", "--dest", type=Path, required=True, help="Where to build the layout"),
        p.add_argument(
            "-m", "--mode", choices=("link", "copy", "move"), default="link",
            help="link (default, no data moved), copy, or move",
        ),
        p.add_argument(
            "--strip", type=int, default=0, metavar="N",
            help="Ignore the first N directory levels when reading structure",
        ),
        p.add_argument(
            "--subject-depth", type=int, metavar="N",
            help="The subject is the folder at level N, rather than guessing",
        ),
        p.add_argument(
            "--session-depth", type=int, metavar="N",
            help="The session is the folder at level N, rather than guessing",
        ),
        p.add_argument(
            "--dates", type=Path, metavar="FILE",
            help=(
                "sessions.csv, a metadata directory, or linked.json: use the "
                "session dates recorded there where a folder name has none"
            ),
        ),
        p.add_argument(
            "--keep-original-names", action="store_true",
            help="Do not apply the N-DOS SubjectID_SessionID_type naming",
        ),
        p.add_argument("-q", "--quiet", action="store_true"),
    )

    plan_parser = subparsers.add_parser("plan", help="Show the layout that would be built")
    common(plan_parser)
    plan_parser.add_argument("-o", "--output", type=Path)
    plan_parser.add_argument("--save", type=Path, help="Write the plan to a file")
    plan_parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    plan_parser.set_defaults(func=command_plan)

    apply_parser = subparsers.add_parser("apply", help="Build the layout, after confirmation")
    apply_parser.add_argument("source", type=Path, nargs="?")
    apply_parser.add_argument("-d", "--dest", type=Path)
    apply_parser.add_argument(
        "-m", "--mode", choices=("link", "copy", "move"), default="link"
    )
    apply_parser.add_argument("--strip", type=int, default=0)
    apply_parser.add_argument("--keep-original-names", action="store_true")
    apply_parser.add_argument("--subject-depth", type=int, metavar="N")
    apply_parser.add_argument("--session-depth", type=int, metavar="N")
    apply_parser.add_argument("--dates", type=Path, metavar="FILE")
    apply_parser.add_argument("--plan-file", type=Path, help="A plan saved earlier")
    apply_parser.add_argument("--yes", action="store_true", help="Skip the confirmation")
    apply_parser.add_argument("--force", action="store_true", help="Proceed despite low space")
    apply_parser.add_argument("-q", "--quiet", action="store_true")
    apply_parser.set_defaults(func=command_apply)

    undo_parser = subparsers.add_parser("undo", help="Reverse an applied layout")
    undo_parser.add_argument("log", type=Path, help=".ndos-layout-log.json from apply")
    undo_parser.add_argument("--yes", action="store_true")
    undo_parser.add_argument("-q", "--quiet", action="store_true")
    undo_parser.set_defaults(func=command_undo)

    args = parser.parse_args()
    if getattr(args, "func", None) is command_apply:
        if not args.plan_file and (not args.source or not args.dest):
            parser.error("apply needs a source and --dest, or --plan-file")
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
