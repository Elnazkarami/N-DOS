#!/usr/bin/env python3
"""Summarise what is actually sitting in a lab data directory.

Reads an NDOS manifest (or scans a directory directly) and reports content
composition, duplicate files, inferred folder structure, and things worth a
human's attention. It answers "what do we have, and what is wrong with it?"
before anyone has entered a single piece of metadata.

Standard library only. Run it directly with no installation:

    python3 ndos_report.py /path/to/data
    python3 ndos_report.py manifest.json --format markdown -o report.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import ndos_scan

REPORT_VERSION = "0.1.0"

#: Extension groupings. Deliberately coarse: the goal is orientation, not
#: classification. Ambiguous extensions are named as ambiguous rather than
#: guessed at, because a wrong confident label is worse than "unclassified".
CATEGORIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "Electrophysiology",
        (
            ".rhd", ".rhs", ".nev", ".nsx", ".ns1", ".ns2", ".ns3", ".ns4",
            ".ns5", ".ns6", ".ncs", ".ntt", ".nse", ".nvt", ".plx", ".pl2",
            ".kwik", ".kwd", ".kwx", ".continuous", ".oebin", ".phy", ".ap",
            ".lf", ".imec", ".meta",
        ),
    ),
    (
        "Imaging and video",
        (
            ".tif", ".tiff", ".avi", ".mp4", ".mov", ".mkv", ".isxd", ".czi",
            ".lif", ".nd2", ".sbx", ".seq", ".ims", ".lsm", ".oib", ".oif",
        ),
    ),
    ("Standard neurodata containers", (".nwb", ".nix")),
    (
        "Motion capture and tracking",
        # .tak is OptiTrack Motive; the rest are common mocap interchange
        # formats. Position tracking is core experimental data, not an extra.
        (".tak", ".c3d", ".trc", ".anc", ".bvh", ".fbx", ".take"),
    ),
    (
        "Arrays and analysis outputs",
        (".mat", ".npy", ".npz", ".h5", ".hdf", ".hdf4", ".hdf5", ".nc",
         ".pkl", ".pickle", ".parquet", ".feather"),
    ),
    ("Tabular and behavioural", (".csv", ".tsv", ".xlsx", ".xls", ".ods", ".sav")),
    ("Notes and documents", (".txt", ".md", ".rst", ".doc", ".docx", ".pdf", ".rtf", ".odt")),
    ("Metadata and configuration", (".json", ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg")),
    ("Figures and images", (".png", ".jpg", ".jpeg", ".gif", ".svg", ".eps", ".ai", ".psd")),
    ("Code and notebooks", (".py", ".m", ".r", ".jl", ".sh", ".bash", ".ipynb", ".c", ".cpp", ".h")),
    ("Archives", (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar")),
)

#: Filename shapes that identify a format when the final suffix alone cannot.
#: `M01_g0_t0.imec0.ap.bin` is unambiguously SpikeGLX, but its suffix is `.bin`.
FILENAME_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\.(ap|lf)\.(bin|meta)$", "Electrophysiology"),
    (r"\.imec\d*\.", "Electrophysiology"),
    (r"^continuous\.dat$", "Electrophysiology"),
    (r"^(structure|settings)\.oebin$", "Electrophysiology"),
    (r"\.tar\.(gz|bz2|xz|zst)$", "Archives"),
)

#: Extensions that could be raw acquisition data or could be anything at all.
AMBIGUOUS_EXTENSIONS = (".dat", ".bin", ".raw", ".log", ".rec", ".out")

ARCHIVE_EXTENSIONS = (".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar")

#: Characters that survive on macOS or Linux but break on Windows, on some NAS
#: exports, and in URLs. Worth knowing before data is shared or published.
UNSAFE_FILENAME_CHARS = set('<>:"|?*\\')

#: Directory-name shapes commonly used as organisational levels in animal labs.
NAME_PATTERNS: Tuple[Tuple[str, str], ...] = (
    # Dates first: they are the least ambiguous.
    ("date", r"^\d{4}[-_.]?\d{2}[-_.]?\d{2}([-_.].*)?$"),
    ("date", r"^\d{2}[-_.]?\d{2}[-_.]?\d{4}([-_.].*)?$"),
    ("date (6-digit)", r"^\d{6}$"),
    # Explicit keyword prefixes next, before any generic shape.
    ("session", r"^(ses|sess|session)[-_]?\d{1,4}$"),
    ("run or recording", r"^(run|rec|recording|trial|block)[-_]?\d{1,4}$"),
    ("animal or subject ID", r"^(sub|subj|subject|animal|mouse|rat)[-_]?\d{1,6}$"),
    # Generic alphanumeric identifier last: it would otherwise swallow the
    # keyword forms above, since `ses-01` also reads as letters-then-digits.
    ("animal or subject ID", r"^[A-Za-z]{1,4}[-_]?\d{2,6}[a-z]?$"),
    ("plain number", r"^\d{1,3}$"),
    ("recovery output", r"^recup_dir\.\d+$"),
    ("recovery output", r"^(recovered|recovery|carved|photorec|testdisk)[-_. ]?\d*$"),
)

#: Words that usually indicate what a folder holds rather than which subject.
ROLE_WORDS = (
    "raw", "processed", "derivative", "derivatives", "analysis", "analyses",
    "behavior", "behaviour", "video", "videos", "histology", "histo", "ephys",
    "imaging", "figures", "results", "sorted", "spikes", "backup", "old",
)


# --------------------------------------------------------------------------
# input
# --------------------------------------------------------------------------

def load_manifest(source: Path, include_checksums: bool = True, quiet: bool = False) -> Dict[str, Any]:
    """Load a manifest from JSON, or produce one by scanning a directory."""
    source = source.expanduser()
    if source.is_dir():
        if not quiet:
            print(f"Scanning {source} (read-only)...", file=sys.stderr)
        return ndos_scan.scan(
            source, include_checksums=include_checksums, progress=not quiet
        )
    if source.is_file():
        manifest = json.loads(source.read_text(encoding="utf-8"))
        version = manifest.get("manifest_version")
        if version != ndos_scan.MANIFEST_VERSION:
            print(
                f"Warning: manifest version {version!r} does not match the "
                f"expected {ndos_scan.MANIFEST_VERSION!r}; some sections may be "
                "incomplete.",
                file=sys.stderr,
            )
        return manifest
    raise ValueError(f"Not a directory or manifest file: {source}")


# --------------------------------------------------------------------------
# analysis
# --------------------------------------------------------------------------

def _plural(count: int, singular: str, plural: Optional[str] = None) -> str:
    """Render a count with a correctly inflected noun."""
    word = singular if count == 1 else (plural or singular + "s")
    return f"{count:,} {word}"


def categorise(extension: str, name: str = "") -> str:
    """Assign a file to a coarse content category.

    Filename patterns are checked before the bare extension so that compound
    suffixes such as `.ap.bin` are recognised rather than written off as
    ambiguous.
    """
    for pattern, label in FILENAME_PATTERNS:
        if re.search(pattern, name, flags=re.IGNORECASE):
            return label
    for label, extensions in CATEGORIES:
        if extension in extensions:
            return label
    if extension in AMBIGUOUS_EXTENSIONS:
        return "Ambiguous (could be raw data)"
    if not extension:
        return "No extension"
    return "Unclassified"


def composition(files: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group files into categories with counts, sizes, and top extensions."""
    counts: Counter = Counter()
    sizes: Counter = Counter()
    extensions: Dict[str, Counter] = defaultdict(Counter)

    for entry in files:
        label = categorise(entry["extension"], entry["name"])
        counts[label] += 1
        sizes[label] += entry["size_bytes"]
        extensions[label][entry["extension"] or "(none)"] += 1

    rows = []
    for label, size in sizes.most_common():
        rows.append(
            {
                "category": label,
                "file_count": counts[label],
                "total_bytes": size,
                "top_extensions": extensions[label].most_common(5),
            }
        )
    return rows


def duplicate_groups(files: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find sets of byte-identical files, largest reclaimable waste first.

    Zero-byte files are excluded: they are all trivially identical and would
    swamp the result without indicating a real storage problem.
    """
    by_digest: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in files:
        digest = entry.get("sha256")
        if digest and entry["size_bytes"] > 0:
            by_digest[digest].append(entry)

    groups = []
    for digest, members in by_digest.items():
        if len(members) < 2:
            continue
        size = members[0]["size_bytes"]
        groups.append(
            {
                "sha256": digest,
                "copies": len(members),
                "size_bytes": size,
                "wasted_bytes": size * (len(members) - 1),
                "paths": sorted(entry["path"] for entry in members),
            }
        )

    groups.sort(key=lambda group: (-group["wasted_bytes"], group["sha256"]))
    return groups


def _classify_name(name: str) -> Optional[str]:
    lowered = name.lower()
    for label, pattern in NAME_PATTERNS:
        if re.match(pattern, name, flags=re.IGNORECASE):
            return label
    if lowered in ROLE_WORDS or any(word in lowered for word in ROLE_WORDS):
        return "role or content label"
    return None


def structure(files: Sequence[Dict[str, Any]], min_names: int = 3) -> List[Dict[str, Any]]:
    """Infer what each directory depth appears to represent.

    Reported as an observation, never as a conclusion: NDOS labels this as
    inferred evidence and expects a human to confirm or correct it.
    """
    names_at_depth: Dict[int, Counter] = defaultdict(Counter)
    for entry in files:
        parts = entry["path"].split("/")[:-1]
        for depth, part in enumerate(parts):
            names_at_depth[depth][part] += 1

    levels = []
    for depth in sorted(names_at_depth):
        names = names_at_depth[depth]
        distinct = list(names)
        if len(distinct) < min_names:
            continue

        votes: Counter = Counter()
        for name in distinct:
            label = _classify_name(name)
            if label:
                votes[label] += 1

        best_label, best_count = (votes.most_common(1) or [(None, 0)])[0]
        confidence = best_count / len(distinct)
        inferred = best_label if confidence >= 0.6 else None

        ranked = [name for name, _ in names.most_common()]
        if inferred:
            examples = [n for n in ranked if _classify_name(n) == inferred][:4]
            exceptions = [n for n in ranked if _classify_name(n) != inferred][:3]
        else:
            examples = ranked[:4]
            exceptions = []

        levels.append(
            {
                "depth": depth,
                "distinct_names": len(distinct),
                "inferred": inferred,
                "confidence": round(confidence, 2) if inferred else 0.0,
                "examples": examples,
                "exceptions": exceptions,
            }
        )
    return levels


def heaviest_directories(files: Sequence[Dict[str, Any]], depth: int = 1, limit: int = 10):
    """Total bytes per directory prefix at a given depth."""
    sizes: Counter = Counter()
    counts: Counter = Counter()
    for entry in files:
        parts = entry["path"].split("/")[:-1]
        key = "/".join(parts[:depth]) if parts else "(root)"
        sizes[key or "(root)"] += entry["size_bytes"]
        counts[key or "(root)"] += 1
    return [
        {"directory": name, "total_bytes": size, "file_count": counts[name]}
        for name, size in sizes.most_common(limit)
    ]


def attention_flags(manifest: Dict[str, Any], duplicates: Sequence[Dict[str, Any]]):
    """Collect concrete, actionable observations about the collection."""
    files = manifest["files"]
    flags: List[Dict[str, Any]] = []

    if not manifest.get("checksums", True):
        flags.append(
            {
                "severity": "info",
                "title": "Checksums were not computed",
                "detail": "Duplicate detection and integrity tracking are unavailable. Re-run without --no-checksum for a complete picture.",
            }
        )

    archives = [entry for entry in files if entry["extension"] in ARCHIVE_EXTENSIONS]
    if archives:
        total = sum(entry["size_bytes"] for entry in archives)
        flags.append(
            {
                "severity": "warning",
                "title": f"{_plural(len(archives), 'archive')} holding {_bytes(total)}",
                "detail": "Contents are not inventoried. Data inside archives is invisible to search and cannot be checked for completeness.",
                "examples": [entry["path"] for entry in archives[:5]],
            }
        )

    if duplicates:
        wasted = sum(group["wasted_bytes"] for group in duplicates)
        flags.append(
            {
                "severity": "warning",
                "title": f"{_plural(len(duplicates), 'set')} of identical files wasting {_bytes(wasted)}",
                "detail": "Byte-identical copies. Confirm which location is authoritative before deleting anything.",
            }
        )

    empty = [entry for entry in files if entry["size_bytes"] == 0]
    if empty:
        flags.append(
            {
                "severity": "warning",
                "title": f"{_plural(len(empty), 'zero-byte file')}",
                "detail": "Often a failed acquisition, an interrupted copy, or a placeholder.",
                "examples": [entry["path"] for entry in empty[:5]],
            }
        )

    unsafe = [
        entry
        for entry in files
        if UNSAFE_FILENAME_CHARS & set(entry["name"]) or not entry["name"].isascii()
    ]
    if unsafe:
        flags.append(
            {
                "severity": "info",
                "title": f"{_plural(len(unsafe), 'filename uses', 'filenames use')} characters that break on other systems",
                "detail": "These fail on Windows, some NAS exports, and in URLs. Worth renaming before sharing or publishing.",
                "examples": [entry["path"] for entry in unsafe[:5]],
            }
        )

    # Counting affected files rather than badly named things turns one
    # awkward folder into thousands of reported problems.
    spaced_files = sorted({entry["name"] for entry in files if " " in entry["name"]})
    spaced_dirs = sorted(
        {
            part
            for entry in files
            for part in entry["path"].split("/")[:-1]
            if " " in part
        }
    )
    if spaced_files or spaced_dirs:
        parts = []
        if spaced_dirs:
            parts.append(_plural(len(spaced_dirs), "directory", "directories"))
        if spaced_files:
            parts.append(_plural(len(spaced_files), "filename"))
        flags.append(
            {
                "severity": "info",
                "title": f"{' and '.join(parts)} contain spaces",
                "detail": "Not an error, but a frequent source of broken analysis scripts.",
                "examples": (spaced_dirs + spaced_files)[:5],
            }
        )

    no_extension = [entry for entry in files if not entry["extension"]]
    if no_extension:
        flags.append(
            {
                "severity": "info",
                "title": f"{_plural(len(no_extension), 'file has', 'files have')} no extension",
                "detail": "Format cannot be determined from the name alone; these need explicit annotation.",
                "examples": [entry["path"] for entry in no_extension[:5]],
            }
        )

    excluded = [
        entry for entry in manifest.get("skipped", []) if entry["reason"] == "excluded"
    ]
    if excluded and len(excluded) > max(20, len(files) // 10):
        flags.append(
            {
                "severity": "info",
                "title": f"{_plural(len(excluded), 'file')} skipped as system clutter",
                "detail": (
                    "Resource forks, thumbnail caches and similar. Not counted "
                    "above, because they are not data. Common on drives written "
                    "by macOS or by recovery tools."
                ),
                "examples": [entry["path"] for entry in excluded[:3]],
            }
        )

    unreadable = [
        entry
        for entry in manifest.get("skipped", [])
        if entry["reason"].startswith("unreadable")
    ]
    if unreadable:
        flags.append(
            {
                "severity": "error",
                "title": f"{_plural(len(unreadable), 'item')} could not be read",
                "detail": "This inventory is incomplete. Usually a permissions problem or an unmounted volume.",
                "examples": [entry["path"] for entry in unreadable[:5]],
            }
        )

    symlinks = [
        entry for entry in manifest.get("skipped", []) if entry["reason"] == "symlink"
    ]
    if symlinks:
        flags.append(
            {
                "severity": "info",
                "title": f"{_plural(len(symlinks), 'symbolic link was', 'symbolic links were')} not followed",
                "detail": "Their targets are not part of this inventory. Scan the target locations separately if they hold data.",
            }
        )

    return flags


def build_report(manifest: Dict[str, Any], duplicate_limit: int = 10) -> Dict[str, Any]:
    files = manifest["files"]
    duplicates = duplicate_groups(files)
    modified = sorted(entry["modified"] for entry in files if entry.get("modified"))

    return {
        "report_version": REPORT_VERSION,
        "source_root": manifest["source_root"],
        "generated_at": manifest.get("generated_at"),
        "summary": {
            "file_count": manifest["file_count"],
            "total_bytes": manifest.get(
                "total_bytes", sum(entry["size_bytes"] for entry in files)
            ),
            "skipped_count": len(manifest.get("skipped", [])),
            "oldest_modified": modified[0] if modified else None,
            "newest_modified": modified[-1] if modified else None,
            "max_depth": max(
                (entry["path"].count("/") for entry in files), default=0
            ),
        },
        "composition": composition(files),
        "structure": structure(files),
        "duplicates": {
            "group_count": len(duplicates),
            "wasted_bytes": sum(group["wasted_bytes"] for group in duplicates),
            "largest": duplicates[:duplicate_limit],
        },
        "heaviest_directories": heaviest_directories(files),
        "attention": attention_flags(manifest, duplicates),
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_bytes = ndos_scan._human_bytes

SEVERITY_MARK = {"error": "[!]", "warning": "[*]", "info": "[ ]"}


def render_text(report: Dict[str, Any]) -> str:
    out: List[str] = []
    add = out.append
    summary = report["summary"]

    add("=" * 72)
    add("NDOS INVENTORY REPORT")
    add("=" * 72)
    add(f"Source      : {report['source_root']}")
    add(f"Scanned     : {report['generated_at'] or 'unknown'}")
    add(
        f"Contents    : {summary['file_count']:,} files, "
        f"{_bytes(summary['total_bytes'])}"
    )
    if summary["oldest_modified"]:
        add(
            f"Modified    : {summary['oldest_modified'][:10]} "
            f"to {summary['newest_modified'][:10]}"
        )
    add(f"Max depth   : {summary['max_depth']} directories below the root")
    if summary["skipped_count"]:
        add(f"Skipped     : {summary['skipped_count']} entries")

    add("")
    add("-" * 72)
    add("WHAT IS IN HERE")
    add("-" * 72)
    for row in report["composition"]:
        extensions = ", ".join(
            f"{ext} ({count})" for ext, count in row["top_extensions"]
        )
        count = _plural(row["file_count"], "file")
        add(
            f"{row['category']:<34}{count:>14}"
            f"{_bytes(row['total_bytes']):>12}"
        )
        add(f"{'':<34}{extensions}")

    if report["structure"]:
        add("")
        add("-" * 72)
        add("INFERRED FOLDER STRUCTURE")
        add("-" * 72)
        add("Observed patterns only. Confirm before relying on them.")
        add("")
        for level in report["structure"]:
            label = level["inferred"] or "no clear pattern"
            confidence = (
                f" ({level['confidence']:.0%} of names)" if level["inferred"] else ""
            )
            add(
                f"  Level {level['depth']}: {label}{confidence} "
                f"- {level['distinct_names']} distinct names"
            )
            add(f"    e.g. {', '.join(level['examples'])}")
            if level.get("exceptions"):
                add(f"    does not fit: {', '.join(level['exceptions'])}")

    duplicates = report["duplicates"]
    if duplicates["group_count"]:
        add("")
        add("-" * 72)
        add("DUPLICATE FILES")
        add("-" * 72)
        add(
            f"{_plural(duplicates['group_count'], 'set')} of byte-identical "
            f"files, {_bytes(duplicates['wasted_bytes'])} reclaimable."
        )
        add("")
        for group in duplicates["largest"]:
            add(
                f"  {group['copies']} copies x {_bytes(group['size_bytes'])} "
                f"= {_bytes(group['wasted_bytes'])} wasted"
            )
            for path in group["paths"][:4]:
                add(f"      {path}")
            if len(group["paths"]) > 4:
                add(f"      ... and {len(group['paths']) - 4} more")

    add("")
    add("-" * 72)
    add("LARGEST DIRECTORIES")
    add("-" * 72)
    for row in report["heaviest_directories"]:
        add(
            f"  {_bytes(row['total_bytes']):>12}  "
            f"{_plural(row['file_count'], 'file'):>12}  "
            f"{row['directory']}"
        )

    if report["attention"]:
        add("")
        add("-" * 72)
        add("NEEDS ATTENTION")
        add("-" * 72)
        for flag in report["attention"]:
            add(f"{SEVERITY_MARK[flag['severity']]} {flag['title']}")
            add(f"    {flag['detail']}")
            for example in flag.get("examples", []):
                add(f"      {example}")
            add("")

    add("-" * 72)
    add("This report describes observations only. Nothing was modified.")
    add("-" * 72)
    return "\n".join(out) + "\n"


def render_markdown(report: Dict[str, Any]) -> str:
    out: List[str] = []
    add = out.append
    summary = report["summary"]

    add("# NDOS inventory report")
    add("")
    add(f"**Source:** `{report['source_root']}`  ")
    add(f"**Scanned:** {report['generated_at'] or 'unknown'}  ")
    add(
        f"**Contents:** {summary['file_count']:,} files, "
        f"{_bytes(summary['total_bytes'])}"
    )
    add("")
    add("> This report describes observations only. Nothing was modified.")
    add("")

    add("## What is in here")
    add("")
    add("| Category | Files | Size | Common extensions |")
    add("| --- | ---: | ---: | --- |")
    for row in report["composition"]:
        extensions = ", ".join(f"`{ext}`" for ext, _ in row["top_extensions"])
        add(
            f"| {row['category']} | {row['file_count']:,} | "
            f"{_bytes(row['total_bytes'])} | {extensions} |"
        )
    add("")

    if report["structure"]:
        add("## Inferred folder structure")
        add("")
        add("Observed patterns only. Confirm before relying on them.")
        add("")
        add("| Depth | Appears to be | Confidence | Names | Examples | Does not fit |")
        add("| ---: | --- | ---: | ---: | --- | --- |")
        for level in report["structure"]:
            label = level["inferred"] or "_no clear pattern_"
            confidence = f"{level['confidence']:.0%}" if level["inferred"] else "-"
            examples = ", ".join(f"`{name}`" for name in level["examples"])
            exceptions = (
                ", ".join(f"`{name}`" for name in level.get("exceptions", [])) or "-"
            )
            add(
                f"| {level['depth']} | {label} | {confidence} | "
                f"{level['distinct_names']} | {examples} | {exceptions} |"
            )
        add("")

    duplicates = report["duplicates"]
    if duplicates["group_count"]:
        add("## Duplicate files")
        add("")
        add(
            f"{_plural(duplicates['group_count'], 'set')} of byte-identical "
            f"files, **{_bytes(duplicates['wasted_bytes'])} reclaimable**."
        )
        add("")
        for group in duplicates["largest"]:
            add(
                f"- **{group['copies']} copies × {_bytes(group['size_bytes'])}** "
                f"({_bytes(group['wasted_bytes'])} wasted)"
            )
            for path in group["paths"][:4]:
                add(f"  - `{path}`")
            if len(group["paths"]) > 4:
                add(f"  - _... and {len(group['paths']) - 4} more_")
        add("")

    add("## Largest directories")
    add("")
    add("| Size | Files | Directory |")
    add("| ---: | ---: | --- |")
    for row in report["heaviest_directories"]:
        add(
            f"| {_bytes(row['total_bytes'])} | {row['file_count']:,} | "
            f"`{row['directory']}` |"
        )
    add("")

    if report["attention"]:
        add("## Needs attention")
        add("")
        for flag in report["attention"]:
            add(f"### {SEVERITY_MARK[flag['severity']]} {flag['title']}")
            add("")
            add(flag["detail"])
            if flag.get("examples"):
                add("")
                for example in flag["examples"]:
                    add(f"- `{example}`")
            add("")

    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarise the contents of a lab data directory or NDOS manifest.",
        epilog="This command never modifies, moves, or deletes source files.",
    )
    parser.add_argument(
        "source", type=Path, help="Directory to scan, or an existing manifest.json"
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="Write the report here; stdout when omitted"
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=("text", "markdown", "json"),
        default="text",
        help="Report format (default: text)",
    )
    parser.add_argument(
        "--no-checksum",
        action="store_true",
        help="When scanning a directory, skip checksums (disables duplicate detection)",
    )
    parser.add_argument(
        "--duplicates",
        type=int,
        default=10,
        metavar="N",
        help="Number of duplicate sets to list (default: 10)",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress output"
    )
    args = parser.parse_args()

    try:
        manifest = load_manifest(
            args.source,
            include_checksums=not args.no_checksum,
            quiet=args.quiet,
        )
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))

    report = build_report(manifest, duplicate_limit=args.duplicates)

    if args.format == "json":
        rendered = json.dumps(report, indent=2) + "\n"
    elif args.format == "markdown":
        rendered = render_markdown(report)
    else:
        rendered = render_text(report)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        if not args.quiet:
            print(f"Wrote report to {args.output}", file=sys.stderr)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
