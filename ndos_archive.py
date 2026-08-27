#!/usr/bin/env python3
"""Look inside archives without extracting them.

Labs zip their archives because the data is enormous, which leaves the
contents invisible: on a real lab drive, 88% to 100% of everything was inside
`.zip` files that no inventory could describe.

This reads an archive's index rather than its contents, so a 300 GB collection
can be catalogued without unpacking a byte. Listings are cached, because on a
slow external drive the first read of a 2 GB archive took nearly a minute and
nobody should pay that twice.

    inspect   list what is inside every archive, and remember it
    search    find members across all catalogued archives
    plan      show exactly what extracting would write, and what it would cost
    extract   carry out a reviewed plan, after explicit confirmation

Nothing is ever extracted without being planned and confirmed first.

Standard library only. Run it directly with no installation.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import ndos_report
import ndos_scan

CATALOGUE_VERSION = "0.1"
GENERATOR_VERSION = "0.1.0"

ZIP_SUFFIXES = (".zip",)
#: Tar variants must be streamed end to end to be listed, so they are opt-in.
TAR_SUFFIXES = (".tar", ".tgz", ".tar.gz", ".tar.bz2", ".tar.xz")

#: Members that are not real content and would only clutter a catalogue.
NOISE_PREFIXES = ("__MACOSX/", "._")
NOISE_NAMES = (".DS_Store", "Thumbs.db", "desktop.ini")


class ArchiveError(Exception):
    """An archive could not be read."""


# --------------------------------------------------------------------------
# identifying archives
# --------------------------------------------------------------------------

def _kind(path: Path) -> Optional[str]:
    name = path.name.lower()
    if name.endswith(ZIP_SUFFIXES):
        return "zip"
    if any(name.endswith(suffix) for suffix in TAR_SUFFIXES):
        return "tar"
    return None


def find_archives(root: Path) -> List[Path]:
    """Every archive below a directory, or the file itself if it is one.

    Filesystem clutter is skipped rather than opened: a macOS resource fork
    named `._session.zip` sits beside the real archive, is not a zip, and
    reading it on a slow drive wastes time only to report a failure.
    """
    root = root.expanduser().resolve()
    if root.is_file():
        return [root] if _kind(root) and not _is_excluded(root.name) else []
    return sorted(
        path for path in root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and _kind(path)
        and not _is_excluded(path.name)
    )


def _is_excluded(name: str) -> bool:
    return ndos_scan._is_excluded(name, ndos_scan.DEFAULT_EXCLUDES)


def _is_noise(name: str) -> bool:
    base = name.rsplit("/", 1)[-1]
    return (
        base in NOISE_NAMES
        or base.startswith("._")
        or name.startswith("__MACOSX/")
    )


# --------------------------------------------------------------------------
# listing
# --------------------------------------------------------------------------

def list_zip(path: Path) -> List[Dict[str, Any]]:
    """Members of a zip, read from its index rather than its contents."""
    members = []
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or _is_noise(info.filename):
                continue
            members.append(
                {
                    "name": info.filename,
                    "size_bytes": info.file_size,
                    "compressed_bytes": info.compress_size,
                    # CRC32 comes free in a zip index and is enough to tell
                    # whether a copy already sits extracted on disk.
                    "crc32": f"{info.CRC:08x}",
                    "modified": "%04d-%02d-%02dT%02d:%02d:%02dZ" % info.date_time,
                }
            )
    return members


def list_tar(path: Path) -> List[Dict[str, Any]]:
    """Members of a tar. Requires streaming the whole file."""
    members = []
    with tarfile.open(path, "r:*") as archive:
        for info in archive:
            if not info.isfile() or _is_noise(info.name):
                continue
            members.append(
                {
                    "name": info.name,
                    "size_bytes": info.size,
                    "modified": ndos_scan._utc_iso(info.mtime),
                }
            )
    return members


def inspect_archive(path: Path) -> Dict[str, Any]:
    """Catalogue one archive without extracting it."""
    kind = _kind(path)
    if kind is None:
        raise ArchiveError(f"not a recognised archive: {path}")

    stat = path.stat()
    entry: Dict[str, Any] = {
        "path": str(path),
        "format": kind,
        "archive_bytes": stat.st_size,
        "archive_modified": ndos_scan._utc_iso(stat.st_mtime),
        "inspected_at": ndos_scan._utc_iso(
            datetime.now(tz=timezone.utc).timestamp()
        ),
    }
    try:
        members = list_zip(path) if kind == "zip" else list_tar(path)
    except (zipfile.BadZipFile, tarfile.TarError, OSError, EOFError) as error:
        entry["error"] = str(error) or error.__class__.__name__
        entry["members"] = []
        entry["member_count"] = 0
        entry["uncompressed_bytes"] = 0
        return entry

    entry["members"] = members
    entry["member_count"] = len(members)
    entry["uncompressed_bytes"] = sum(m["size_bytes"] for m in members)
    return entry


def _cache_key(path: Path) -> Tuple[str, int, str]:
    stat = path.stat()
    return (str(path), stat.st_size, ndos_scan._utc_iso(stat.st_mtime))


def inspect(
    root: Path,
    cache_path: Optional[Path] = None,
    include_tar: bool = False,
    refresh: bool = False,
    progress: bool = True,
) -> Dict[str, Any]:
    """Catalogue every archive below ``root``, reusing a cache where possible."""
    archives = find_archives(root)
    deferred: List[Dict[str, Any]] = []
    if not include_tar:
        deferred = [
            {"path": str(path), "bytes": path.stat().st_size}
            for path in archives
            if _kind(path) == "tar"
        ]
        archives = [path for path in archives if _kind(path) == "zip"]

    cached: Dict[str, Dict[str, Any]] = {}
    if cache_path and cache_path.exists() and not refresh:
        try:
            previous = json.loads(cache_path.read_text(encoding="utf-8"))
            cached = {entry["path"]: entry for entry in previous.get("archives", [])}
        except (OSError, json.JSONDecodeError, KeyError):
            cached = {}

    entries: List[Dict[str, Any]] = []
    reused = 0
    for index, path in enumerate(archives, start=1):
        try:
            key = _cache_key(path)
        except OSError:
            continue

        previous = cached.get(str(path))
        if (
            previous
            and previous.get("archive_bytes") == key[1]
            and previous.get("archive_modified") == key[2]
            and "error" not in previous
        ):
            entries.append(previous)
            reused += 1
            continue

        if progress:
            print(
                f"  [{index}/{len(archives)}] reading index of {path.name} "
                f"({ndos_scan._human_bytes(key[1])})...",
                file=sys.stderr,
            )
        entries.append(inspect_archive(path))

    catalogue = {
        "catalogue_version": CATALOGUE_VERSION,
        "generated_at": ndos_scan._utc_iso(
            datetime.now(tz=timezone.utc).timestamp()
        ),
        "generator": {"name": "ndos-archive", "version": GENERATOR_VERSION},
        "root": str(root.expanduser().resolve()),
        "archive_count": len(entries),
        "reused_from_cache": reused,
        "member_count": sum(e["member_count"] for e in entries),
        "uncompressed_bytes": sum(e["uncompressed_bytes"] for e in entries),
        "archives": entries,
        # Tar archives must be streamed end to end to be listed, so they are
        # opt-in -- but skipping them silently left 155 GB of a real drive
        # uninventoried with nothing saying so.
        "deferred": deferred,
        "deferred_bytes": sum(item["bytes"] for item in deferred),
    }
    if cache_path:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(catalogue, indent=2) + "\n", encoding="utf-8")
    return catalogue


# --------------------------------------------------------------------------
# searching
# --------------------------------------------------------------------------

def search(
    catalogue: Dict[str, Any], pattern: str, category: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Members whose name matches a glob or substring, across all archives."""
    lowered = pattern.lower()
    globbed = any(character in pattern for character in "*?[")
    hits = []
    for archive in catalogue.get("archives", []):
        for member in archive.get("members", []):
            name = member["name"]
            base = name.rsplit("/", 1)[-1]
            if globbed:
                matched = fnmatch.fnmatch(base.lower(), lowered) or fnmatch.fnmatch(
                    name.lower(), lowered
                )
            else:
                matched = lowered in name.lower()
            if not matched:
                continue
            if category:
                extension = Path(base).suffix.lower()
                if ndos_report.categorise(extension, base) != category:
                    continue
            hits.append({**member, "archive": archive["path"]})
    return hits


def composition(catalogue: Dict[str, Any]) -> List[Dict[str, Any]]:
    """What is inside the archives, grouped the way the inventory groups files."""
    from collections import Counter

    counts: Counter = Counter()
    sizes: Counter = Counter()
    for archive in catalogue.get("archives", []):
        for member in archive.get("members", []):
            base = member["name"].rsplit("/", 1)[-1]
            label = ndos_report.categorise(Path(base).suffix.lower(), base)
            counts[label] += 1
            sizes[label] += member["size_bytes"]
    return [
        {"category": label, "file_count": counts[label], "total_bytes": size}
        for label, size in sizes.most_common()
    ]


# --------------------------------------------------------------------------
# extraction planning
# --------------------------------------------------------------------------

def _safe_target(destination: Path, member_name: str) -> Optional[Path]:
    """Resolve a member to a path inside the destination, or reject it.

    Archive members can contain `..` segments or absolute paths that would
    write outside the destination. That is a real attack against anyone
    unpacking an archive they did not create, and this is where it is stopped.
    """
    candidate = (destination / member_name).resolve()
    try:
        candidate.relative_to(destination.resolve())
    except ValueError:
        return None
    return candidate


def plan_extraction(
    catalogue: Dict[str, Any],
    destination: Path,
    pattern: Optional[str] = None,
    category: Optional[str] = None,
    archive_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Work out exactly what an extraction would write, before writing anything."""
    destination = destination.expanduser().resolve()
    actions: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for archive in catalogue.get("archives", []):
        if archive_filter and archive_filter not in archive["path"]:
            continue
        for member in archive.get("members", []):
            name = member["name"]
            base = name.rsplit("/", 1)[-1]
            if pattern:
                lowered = pattern.lower()
                globbed = any(c in pattern for c in "*?[")
                matched = (
                    fnmatch.fnmatch(base.lower(), lowered)
                    or fnmatch.fnmatch(name.lower(), lowered)
                    if globbed else lowered in name.lower()
                )
                if not matched:
                    continue
            if category:
                if ndos_report.categorise(Path(base).suffix.lower(), base) != category:
                    continue

            target = _safe_target(destination, name)
            if target is None:
                rejected.append(
                    {
                        "archive": archive["path"],
                        "member": name,
                        "reason": "member path escapes the destination directory",
                    }
                )
                continue

            actions.append(
                {
                    "archive": archive["path"],
                    "member": name,
                    "target": str(target),
                    "size_bytes": member["size_bytes"],
                    "exists": target.exists(),
                }
            )

    required = sum(a["size_bytes"] for a in actions if not a["exists"])
    try:
        free = shutil.disk_usage(
            destination if destination.exists() else destination.parent
        ).free
    except OSError:
        free = None

    return {
        "destination": str(destination),
        "action_count": len(actions),
        "total_bytes": sum(a["size_bytes"] for a in actions),
        "bytes_to_write": required,
        "already_present": sum(1 for a in actions if a["exists"]),
        "free_bytes": free,
        "enough_space": None if free is None else free > required * 1.05,
        "rejected": rejected,
        "actions": actions,
    }


def apply_extraction(
    plan: Dict[str, Any], overwrite: bool = False, progress: bool = True
) -> Dict[str, Any]:
    """Carry out a plan. Only ever called after explicit confirmation."""
    written: List[str] = []
    skipped: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []

    by_archive: Dict[str, List[Dict[str, Any]]] = {}
    for action in plan["actions"]:
        by_archive.setdefault(action["archive"], []).append(action)

    for archive_path, actions in by_archive.items():
        path = Path(archive_path)
        kind = _kind(path)
        try:
            opener = (
                zipfile.ZipFile(path) if kind == "zip" else tarfile.open(path, "r:*")
            )
        except (zipfile.BadZipFile, tarfile.TarError, OSError) as error:
            for action in actions:
                failed.append({"target": action["target"], "reason": str(error)})
            continue

        with opener as archive:
            for action in actions:
                target = Path(action["target"])
                if target.exists() and not overwrite:
                    skipped.append(
                        {"target": str(target), "reason": "already exists"}
                    )
                    continue
                try:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if kind == "zip":
                        with archive.open(action["member"]) as source, target.open("wb") as sink:
                            shutil.copyfileobj(source, sink)
                    else:
                        extracted = archive.extractfile(action["member"])
                        if extracted is None:
                            raise ArchiveError("member is not a regular file")
                        with extracted as source, target.open("wb") as sink:
                            shutil.copyfileobj(source, sink)
                    written.append(str(target))
                    if progress:
                        print(f"  extracted {target.name}", file=sys.stderr)
                except (OSError, KeyError, ArchiveError, tarfile.TarError) as error:
                    failed.append({"target": str(target), "reason": str(error)})

    return {
        "written": written,
        "written_count": len(written),
        "skipped": skipped,
        "failed": failed,
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_bytes = ndos_scan._human_bytes


def render_catalogue(catalogue: Dict[str, Any], limit: int = 12) -> str:
    out: List[str] = []
    add = out.append

    add("=" * 72)
    add("NDOS ARCHIVE CATALOGUE")
    add("=" * 72)
    add(f"Root      : {catalogue['root']}")
    add(f"Archives  : {catalogue['archive_count']}")
    add(
        f"Contents  : {catalogue['member_count']:,} files, "
        f"{_bytes(catalogue['uncompressed_bytes'])} uncompressed"
    )
    if catalogue.get("reused_from_cache"):
        add(f"Cached    : {catalogue['reused_from_cache']} read from a previous run")
    if catalogue.get("deferred"):
        add("")
        add(
            f"NOT READ  : {ndos_report._plural(len(catalogue['deferred']), 'tar archive')}"
            f", {_bytes(catalogue['deferred_bytes'])}"
        )
        add(
            "            Unlike a zip, a tar must be read end to end to be "
            "listed. Pass"
        )
        add("            --include-tar to inventory them; expect it to be slow.")
    add("")
    add("Nothing was extracted. These are the archives' own indexes.")

    rows = composition(catalogue)
    if rows:
        add("")
        add("-" * 72)
        add("WHAT IS INSIDE THE ARCHIVES")
        add("-" * 72)
        for row in rows:
            add(
                f"  {row['category']:<34}"
                f"{ndos_report._plural(row['file_count'], 'file'):>14}"
                f"{_bytes(row['total_bytes']):>12}"
            )

    add("")
    add("-" * 72)
    add("ARCHIVES")
    add("-" * 72)
    for archive in catalogue["archives"][:limit]:
        name = Path(archive["path"]).name
        if archive.get("error"):
            add(f"  [!] {name}")
            add(f"        could not be read: {archive['error']}")
            continue
        ratio = (
            archive["uncompressed_bytes"] / archive["archive_bytes"]
            if archive["archive_bytes"] else 0
        )
        add(
            f"  {name}  ({_bytes(archive['archive_bytes'])} on disk, "
            f"{_bytes(archive['uncompressed_bytes'])} inside, {ratio:.1f}x)"
        )
        add(f"      {archive['member_count']:,} files")
        for member in archive["members"][:3]:
            add(f"        {member['name']}")
        if archive["member_count"] > 3:
            add(f"        ... and {archive['member_count'] - 3:,} more")
    if len(catalogue["archives"]) > limit:
        add(f"  ... and {len(catalogue['archives']) - limit} more archives")

    add("")
    add("-" * 72)
    add("Search inside without extracting:")
    add(f"  {ndos_scan.invocation('ndos_archive')} search <cache.json> '*.avi'")
    add("-" * 72)
    return "\n".join(out) + "\n"


def render_plan(plan: Dict[str, Any], limit: int = 20) -> str:
    out: List[str] = []
    add = out.append

    add("=" * 72)
    add("NDOS EXTRACTION PLAN")
    add("=" * 72)
    add(f"Destination : {plan['destination']}")
    add(
        f"Would write : {ndos_report._plural(plan['action_count'], 'file')}, "
        f"{_bytes(plan['bytes_to_write'])}"
    )
    if plan["already_present"]:
        add(
            f"Already there: {plan['already_present']} "
            "(skipped unless --overwrite)"
        )
    if plan["free_bytes"] is not None:
        add(f"Free space  : {_bytes(plan['free_bytes'])}")
        if plan["enough_space"] is False:
            add("")
            add("  *** NOT ENOUGH FREE SPACE. Extraction would fail partway. ***")
    add("")

    if plan["rejected"]:
        add("-" * 72)
        add("REFUSED")
        add("-" * 72)
        for item in plan["rejected"]:
            add(f"  {item['member']}")
            add(f"      {item['reason']}")
        add("")

    add("-" * 72)
    add("FILES")
    add("-" * 72)
    for action in plan["actions"][:limit]:
        mark = "(exists)" if action["exists"] else ""
        add(f"  {_bytes(action['size_bytes']):>10}  {action['member']} {mark}")
    if plan["action_count"] > limit:
        add(f"  ... and {plan['action_count'] - limit:,} more")

    add("")
    add("-" * 72)
    add("Nothing has been extracted. To carry this out, re-run with 'extract'.")
    add("-" * 72)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def _load_catalogue(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def command_inspect(args: argparse.Namespace) -> int:
    if not args.quiet:
        print(f"Reading archive indexes under {args.root}...", file=sys.stderr)
    catalogue = inspect(
        args.root,
        cache_path=args.cache,
        include_tar=args.include_tar,
        refresh=args.refresh,
        progress=not args.quiet,
    )
    rendered = (
        json.dumps(catalogue, indent=2) + "\n" if args.format == "json"
        else render_catalogue(catalogue)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    if args.cache and not args.quiet:
        print(f"Catalogue cached at {args.cache}", file=sys.stderr)
    return 0


def command_search(args: argparse.Namespace) -> int:
    catalogue = _load_catalogue(args.cache)
    hits = search(catalogue, args.pattern, category=args.category)

    if args.format == "json":
        print(json.dumps(hits, indent=2))
        return 0

    print("=" * 72)
    print(f"MEMBERS MATCHING {args.pattern!r}")
    print("=" * 72)
    if not hits:
        print("Nothing matched. The archives were not opened.")
        return 0
    total = sum(hit["size_bytes"] for hit in hits)
    print(f"{ndos_report._plural(len(hits), 'file')}, {_bytes(total)} uncompressed")
    print()
    by_archive: Dict[str, List[Dict[str, Any]]] = {}
    for hit in hits:
        by_archive.setdefault(hit["archive"], []).append(hit)
    for archive, members in by_archive.items():
        print(f"  {Path(archive).name}")
        for member in members[: args.limit]:
            print(f"      {_bytes(member['size_bytes']):>10}  {member['name']}")
        if len(members) > args.limit:
            print(f"      ... and {len(members) - args.limit:,} more")
    print()
    print("-" * 72)
    print("Still nothing extracted. To get these files:")
    print(
        f"  {ndos_scan.invocation('ndos_archive')} plan {args.cache} "
        f"--dest DIR --name {args.pattern!r}"
    )
    print("-" * 72)
    return 0


def command_plan(args: argparse.Namespace) -> int:
    catalogue = _load_catalogue(args.cache)
    plan = plan_extraction(
        catalogue, args.dest, pattern=args.name,
        category=args.category, archive_filter=args.archive,
    )
    if args.format == "json":
        print(json.dumps(plan, indent=2))
    else:
        print(render_plan(plan), end="")
    if args.save:
        args.save.parent.mkdir(parents=True, exist_ok=True)
        args.save.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        print(f"Plan saved to {args.save}", file=sys.stderr)
    return 0


def command_extract(args: argparse.Namespace) -> int:
    if args.plan_file:
        plan = json.loads(args.plan_file.read_text(encoding="utf-8"))
    else:
        catalogue = _load_catalogue(args.cache)
        plan = plan_extraction(
            catalogue, args.dest, pattern=args.name,
            category=args.category, archive_filter=args.archive,
        )

    if not plan["action_count"]:
        print("Nothing matched; nothing to extract.", file=sys.stderr)
        return 0

    print(render_plan(plan), end="")

    if plan["enough_space"] is False and not args.force:
        print(
            "Refusing to start: not enough free space for this plan. "
            "Free some space, narrow the selection, or pass --force.",
            file=sys.stderr,
        )
        return 1

    if not args.yes:
        # Extraction writes data and can fill a disk, so it is confirmed
        # rather than assumed.
        try:
            answer = input(
                f"\nExtract {plan['action_count']} files "
                f"({_bytes(plan['bytes_to_write'])}) to {plan['destination']}? [y/N] "
            )
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was extracted.", file=sys.stderr)
            return 1

    result = apply_extraction(plan, overwrite=args.overwrite, progress=not args.quiet)
    print(
        f"\nExtracted {result['written_count']} files. "
        f"Skipped {len(result['skipped'])}, failed {len(result['failed'])}.",
        file=sys.stderr,
    )
    for failure in result["failed"][:5]:
        print(f"  failed: {failure['target']}: {failure['reason']}", file=sys.stderr)
    return 1 if result["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Look inside archives without extracting them.",
        epilog="Extraction always requires a reviewed plan and a confirmation.",
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect", help="Catalogue archive contents without extracting"
    )
    inspect_parser.add_argument("root", type=Path, help="Directory or archive file")
    inspect_parser.add_argument(
        "-c", "--cache", type=Path, default=Path("archives.json"),
        help="Where to store the catalogue (default: archives.json)",
    )
    inspect_parser.add_argument(
        "--include-tar", action="store_true",
        help="Also read .tar/.tar.gz, which must be streamed end to end and is slow",
    )
    inspect_parser.add_argument(
        "--refresh", action="store_true", help="Re-read archives even if cached"
    )
    inspect_parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    inspect_parser.add_argument("-o", "--output", type=Path)
    inspect_parser.add_argument("-q", "--quiet", action="store_true")
    inspect_parser.set_defaults(func=command_inspect)

    search_parser = subparsers.add_parser(
        "search", help="Find files inside catalogued archives"
    )
    search_parser.add_argument("cache", type=Path, help="Catalogue from inspect")
    search_parser.add_argument("pattern", help="Glob such as '*.avi', or a substring")
    search_parser.add_argument("--category", help="Restrict to one content category")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    search_parser.set_defaults(func=command_search)

    plan_parser = subparsers.add_parser(
        "plan", help="Show what extracting would write, without writing"
    )
    plan_parser.add_argument("cache", type=Path)
    plan_parser.add_argument("--dest", type=Path, required=True, help="Where files would go")
    plan_parser.add_argument("--name", help="Only members matching this glob or substring")
    plan_parser.add_argument("--category", help="Only members in this content category")
    plan_parser.add_argument("--archive", help="Only from archives whose path contains this")
    plan_parser.add_argument("--save", type=Path, help="Write the plan to a file")
    plan_parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    plan_parser.set_defaults(func=command_plan)

    extract_parser = subparsers.add_parser(
        "extract", help="Carry out an extraction, after confirmation"
    )
    extract_parser.add_argument("cache", type=Path, nargs="?")
    extract_parser.add_argument("--plan-file", type=Path, help="A plan saved earlier")
    extract_parser.add_argument("--dest", type=Path, help="Where files should go")
    extract_parser.add_argument("--name", help="Only members matching this glob or substring")
    extract_parser.add_argument("--category", help="Only members in this content category")
    extract_parser.add_argument("--archive", help="Only from archives whose path contains this")
    extract_parser.add_argument(
        "--yes", action="store_true", help="Skip the confirmation prompt"
    )
    extract_parser.add_argument(
        "--overwrite", action="store_true", help="Replace files that already exist"
    )
    extract_parser.add_argument(
        "--force", action="store_true", help="Proceed despite a low-space warning"
    )
    extract_parser.add_argument("-q", "--quiet", action="store_true")
    extract_parser.set_defaults(func=command_extract)

    args = parser.parse_args()
    if getattr(args, "func", None) is command_extract:
        if not args.plan_file and (not args.cache or not args.dest):
            parser.error("extract needs a cache and --dest, or --plan-file")
    try:
        return args.func(args)
    except (OSError, ValueError, json.JSONDecodeError, ArchiveError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
