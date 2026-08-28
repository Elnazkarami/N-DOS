#!/usr/bin/env python3
"""Start an N-DOS project, and make the folder for a recording.

The standard serves two situations. One is an archive nobody understands any
more, which `ndos organize` reconstructs. The other is a lab that is about to
start collecting, or is collecting now — and for them the point is to put data
in the right place the first time rather than sort it out years later.

    ndos init ./my-study
    ndos init ./my-study --subject M123 --date 2025-03-14

The first creates the layout the manuscript defines. The second adds the
folder for one recording, named by the convention, ready to acquire into.

Nothing here writes outside the project directory, and nothing overwrites a
file that already exists.

Standard library only. Run it directly with no installation.
"""

from __future__ import annotations

import argparse
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

#: The N-DOS layout, in the order the manuscript lists it.
DIRECTORIES: Tuple[Tuple[str, str], ...] = (
    ("raw_data", "Immutable raw recordings, as raw_data/<SubjectID>/<SessionID>/"),
    ("processed_data", "Cleaned, sorted and pre-processed data"),
    ("analysis", "Exploratory analyses and intermediate results"),
    ("derivatives", "Validated, finalised analyses approved for sharing"),
    ("flagged_data", "Corrupted, incomplete or uncertain data, each with a note"),
    ("figures", "Visualisations generated from processed or derived data"),
    ("scripts", "Code used for acquisition, preprocessing and analysis"),
    ("metadata", "Experiment, acquisition and session descriptions"),
)

#: SubjectID as the manuscript gives it: e.g. M123.
SUBJECT = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _readme(name: str) -> str:
    rows = "\n".join(
        f"| `{directory}/` | {description} |" for directory, description in DIRECTORIES
    )
    return f"""# {name}

This project follows the N-DOS layout.

| Directory | Contents |
| --- | --- |
{rows}

## Where a recording goes

```
raw_data/<SubjectID>/<SessionID>/
```

`SubjectID` identifies the animal, for example `M123`. `SessionID` is the date
as `YYYYMMDD`, with a number appended when there is more than one recording
that day: `20250314`, `20250314_02`.

Make the folder for a session rather than typing the path, and the convention
is applied for you:

```bash
ndos init . --subject M123 --date 2025-03-14
```

## As data arrives

```bash
ndos table export . -d ./metadata_tables   # spreadsheets to describe it
ndos table check ./metadata_tables         # what is still missing
ndos query linked.json -w species=mouse    # find sessions later
```

## File naming

`<SubjectID>_<SessionID>_<type>.<ext>`, for example:

| Type | Example |
| --- | --- |
| Raw electrophysiology | `M123_20250314_raw.dat` or `.nwb` |
| LFP | `M123_20250314_lfp.npy` |
| Spikes | `M123_20250314_spikes.csv` |
| Behaviour | `M123_20250314_behavior.tsv` |
| Task | `M123_20250314_task.tsv` |
| Position tracking | `M123_20250314_position.tsv` |
| Experimenter input | `M123_20250314_experimenter.tsv` |
| Video | `M123_20250314_video.mp4` |

Add `_v1`, `_v2` when something is reprocessed.

**A note for whoever configures acquisition:** where you can choose, record
video as H.264-encoded MP4. It is the one setting here that is easier to get
right at the rig than to correct afterwards — re-encoding later means either
losing quality or keeping two copies, and raw data is meant to stay as
acquired. Where your hardware writes something else, keep what it writes.
NDOS does not check this and will not re-encode anything.

## Output from analysis tools

Folders written by Phy, Kilosort, SpikeInterface, suite2p, Open Ephys or a
Zarr store are kept exactly as those tools wrote them — their filenames are
how the tools find their own data. Put them under the session they belong to
and leave their contents alone.

Raw data is meant to stay as acquired. Anything that changes it belongs in
`processed_data/`, and anything uncertain belongs in `flagged_data/` with a
note saying why.
"""


def _project_id(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return normalized or "ndos-project"


def _project_toml(project_name: str, project_id: str) -> str:
    return (
        "[ndos]\n"
        'version = "0.1"\n'
        f'name = "{project_name}"\n'
        f'id = "{project_id}"\n'
        "\n"
        "[storage]\n"
        'raw_data = "read-only after acquisition"\n'
    )


def session_id(date: str, number: Optional[int] = None) -> str:
    """`YYYYMMDD`, or `YYYYMMDD_NN` when a day holds more than one recording."""
    match = ISO_DATE.match(date)
    if not match:
        raise ValueError(
            f"date must be written as YYYY-MM-DD, not {date!r}. "
            "Ambiguous forms like 03/04/2025 mean different days in different "
            "countries, so NDOS does not accept them."
        )
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"{date!r} is not a real date")
    compact = "".join(match.groups())
    return f"{compact}_{number:02d}" if number else compact


def initialize(root: Path, project_id: Optional[str] = None, force: bool = False) -> Path:
    """Create the N-DOS layout. Existing directories and files are left alone."""
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)

    for directory, _ in DIRECTORIES:
        (root / directory).mkdir(exist_ok=True)

    readme = root / "README.md"
    if not readme.exists() or force:
        readme.write_text(_readme(root.name), encoding="utf-8")

    profile = root / "project.toml"
    if not profile.exists() or force:
        profile.write_text(
            _project_toml(root.name, project_id or _project_id(root.name)),
            encoding="utf-8",
        )
    return profile


def add_session(
    root: Path, subject: str, date: str, number: Optional[int] = None
) -> Tuple[Path, List[Path]]:
    """Make the folders for one recording, named by the convention."""
    if not SUBJECT.match(subject):
        raise ValueError(
            f"subject {subject!r} should be a plain identifier such as M123: "
            "letters, digits, hyphen or underscore, starting with a letter"
        )
    root = root.expanduser().resolve()
    session = session_id(date, number)

    created: List[Path] = []
    raw = root / "raw_data" / subject / session
    if not raw.exists():
        created.append(raw)
    raw.mkdir(parents=True, exist_ok=True)

    # The manuscript pairs each raw session with a processed one holding temp/.
    processed = root / "processed_data" / subject / session
    if not processed.exists():
        created.append(processed)
    processed.mkdir(parents=True, exist_ok=True)
    (processed / "temp").mkdir(exist_ok=True)

    return raw, created


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start an N-DOS project, or make the folder for a recording.",
        epilog=(
            "Already have data that is not organised? Use 'ndos organize' "
            "instead; it builds this layout from the structure you already have."
        ),
    )
    parser.add_argument("root", type=Path, help="Project directory")
    parser.add_argument(
        "--subject",
        metavar="ID",
        help="Also make the folder for a recording from this animal, e.g. M123",
    )
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Date of that recording (default: today)",
    )
    parser.add_argument(
        "--number",
        type=int,
        metavar="N",
        help="Which recording of that day, when there is more than one",
    )
    parser.add_argument("--project-id", help="Stable logical project identifier")
    parser.add_argument(
        "--force", action="store_true", help="Rewrite README.md and project.toml"
    )
    args = parser.parse_args()

    if args.date and not args.subject:
        parser.error("--date describes a recording, so it needs --subject too")

    try:
        profile = initialize(args.root, args.project_id, args.force)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    root = profile.parent
    print(f"N-DOS project ready: {root}")
    for directory, _ in DIRECTORIES:
        print(f"  {directory}/")

    if args.subject:
        date = args.date or datetime.now().strftime("%Y-%m-%d")
        try:
            raw, created = add_session(root, args.subject, date, args.number)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        print()
        if created:
            print(f"Acquire into: {raw}")
        else:
            print(f"Already there: {raw}")
        print(
            "  Name files as "
            f"{args.subject}_{session_id(date, args.number)}_<type>, "
            "for example _raw.dat, _lfp.npy, _behavior.tsv"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
