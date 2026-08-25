#!/usr/bin/env python3
"""Create a read-only NDOS file manifest.

This module never writes to, moves, renames, or opens for modification any file
below the scan root. It reads file contents only to compute checksums.

Standard library only. Run it directly with no installation:

    python3 ndos_scan.py /path/to/data --output manifest.json
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple


MANIFEST_VERSION = "0.2"
GENERATOR_NAME = "ndos-scan"
GENERATOR_VERSION = "0.2.0"

#: Filesystem clutter that is never part of a scientific record.
DEFAULT_EXCLUDES = (
    ".DS_Store",
    "._*",
    "Thumbs.db",
    "desktop.ini",
    ".Trashes",
    ".Spotlight-V100",
    ".fseventsd",
    "__pycache__",
    "*.pyc",
)

CHUNK_SIZE = 4 * 1024 * 1024

#: Filename used for the checksum cache when one is not named explicitly.
CACHE_FILE = ".ndos-scan-cache.json"
CACHE_VERSION = "0.1"

#: How often the cache is written out. A scan of a slow drive can run for
#: hours, and an interruption should cost minutes at most, not the whole run.
FLUSH_EVERY_FILES = 25
FLUSH_EVERY_SECONDS = 30.0

#: Progress is reported at most this often, so a slow scan does not turn into
#: a wall of output.
PROGRESS_EVERY_SECONDS = 2.0


def _utc_iso(timestamp: float) -> str:
    """Render a POSIX timestamp as a second-resolution UTC ISO 8601 string."""
    return (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_excluded(name: str, patterns: Tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk(
    root: Path, excludes: Tuple[str, ...], skipped: List[Dict[str, str]]
) -> Iterator[Path]:
    """Yield files below ``root`` in a stable order, recording what was skipped.

    Unreadable directories and excluded names are reported rather than dropped
    silently: an inventory that quietly omits data is worse than no inventory.
    """

    def on_error(error: OSError) -> None:
        skipped.append(
            {
                "path": _relative(Path(error.filename or str(root)), root),
                "reason": "unreadable-directory",
                "detail": error.strerror or "unknown error",
            }
        )

    for current, directories, filenames in os.walk(root, onerror=on_error):
        current_path = Path(current)

        kept_directories = []
        for directory in sorted(directories):
            full = current_path / directory
            if _is_excluded(directory, excludes):
                skipped.append(
                    {
                        "path": _relative(full, root),
                        "reason": "excluded",
                        "detail": "matched an exclude pattern",
                    }
                )
            elif full.is_symlink():
                skipped.append(
                    {
                        "path": _relative(full, root),
                        "reason": "symlink",
                        "detail": "directory symlink; not followed",
                    }
                )
            else:
                kept_directories.append(directory)
        # os.walk reads this list back, so prune in place to control traversal.
        directories[:] = kept_directories

        for filename in sorted(filenames):
            full = current_path / filename
            if _is_excluded(filename, excludes):
                skipped.append(
                    {
                        "path": _relative(full, root),
                        "reason": "excluded",
                        "detail": "matched an exclude pattern",
                    }
                )
                continue
            if full.is_symlink():
                skipped.append(
                    {
                        "path": _relative(full, root),
                        "reason": "symlink",
                        "detail": "file symlink; target not inventoried",
                    }
                )
                continue
            yield full


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def scan(
    root: Path,
    include_checksums: bool = True,
    excludes: Tuple[str, ...] = DEFAULT_EXCLUDES,
    progress: bool = False,
    cache_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Return a manifest of ``root`` without changing anything below it.

    When ``cache_path`` is given, checksums already computed for a file of the
    same size and modification time are reused, and new ones are written out as
    the scan proceeds. A scan of a slow drive can take hours; being interrupted
    should cost minutes, not the whole run.
    """
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Scan root is not a directory: {root}")

    files: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    total_bytes = 0

    cache = load_cache(cache_path) if cache_path else {}
    reused = 0
    hashed_bytes = 0
    pending = 0
    started = time.monotonic()
    last_flush = started
    last_report = started

    # Knowing the total up front is what makes a remaining-time estimate
    # possible; walking twice is cheap next to reading every byte.
    planned: List[Tuple[Path, int]] = []
    if include_checksums and progress:
        for path in _walk(root, excludes, []):
            try:
                planned.append((path, path.stat().st_size))
            except OSError:
                continue
    outstanding = sum(
        size for path, size in planned
        if not _cached_for(cache, _relative(path, root), size)
    )

    def flush() -> None:
        if cache_path:
            save_cache(cache_path, root, cache)

    try:
        for path in _walk(root, excludes, skipped):
            try:
                stat = path.stat()
            except OSError as error:
                skipped.append(
                    {
                        "path": _relative(path, root),
                        "reason": "unreadable-file",
                        "detail": error.strerror or "unknown error",
                    }
                )
                continue

            relative = _relative(path, root)
            entry: Dict[str, Any] = {
                "path": relative,
                "name": path.name,
                "extension": path.suffix.lower(),
                "size_bytes": stat.st_size,
                "modified": _utc_iso(stat.st_mtime),
                "role": "unknown",
            }

            if include_checksums:
                known = _cached_for(cache, relative, stat.st_size, entry["modified"])
                if known:
                    entry["sha256"] = known
                    reused += 1
                else:
                    try:
                        entry["sha256"] = _sha256(path)
                    except OSError as error:
                        skipped.append(
                            {
                                "path": relative,
                                "reason": "unreadable-file",
                                "detail": error.strerror or "unknown error",
                            }
                        )
                        continue
                    hashed_bytes += stat.st_size
                    pending += 1
                    if cache_path:
                        cache[relative] = {
                            "size_bytes": stat.st_size,
                            "modified": entry["modified"],
                            "sha256": entry["sha256"],
                        }

            files.append(entry)
            total_bytes += stat.st_size

            now = time.monotonic()
            if cache_path and (
                pending >= FLUSH_EVERY_FILES or now - last_flush >= FLUSH_EVERY_SECONDS
            ):
                flush()
                pending = 0
                last_flush = now

            if progress and now - last_report >= PROGRESS_EVERY_SECONDS:
                _report_progress(
                    len(files), len(planned) or None, total_bytes,
                    hashed_bytes, outstanding, now - started, reused,
                )
                last_report = now
    except KeyboardInterrupt:
        flush()
        if progress:
            print(
                f"\nInterrupted after {len(files)} files. "
                + (
                    f"Checksums so far are cached in {cache_path}; "
                    "re-run the same command to carry on from here."
                    if cache_path
                    else "Nothing was cached, so a re-run starts over. Pass "
                    "--cache next time to make a scan resumable."
                ),
                file=sys.stderr,
            )
        raise

    flush()
    files.sort(key=lambda entry: entry["path"])
    skipped.sort(key=lambda entry: (entry["reason"], entry["path"]))

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at": _utc_iso(datetime.now(tz=timezone.utc).timestamp()),
        "generator": {"name": GENERATOR_NAME, "version": GENERATOR_VERSION},
        "source_root": str(root),
        "checksums": include_checksums,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "files": files,
        "skipped": skipped,
    }
    if include_checksums and cache_path:
        manifest["extensions"] = {
            "cache": {"path": str(cache_path), "reused": reused}
        }
    return manifest


def _cached_for(
    cache: Dict[str, Dict[str, Any]],
    relative: str,
    size: int,
    modified: Optional[str] = None,
) -> Optional[str]:
    """A cached checksum, but only if the file looks untouched since.

    Size and modification time together are what a filesystem can tell us
    cheaply. They can miss a change made within the same second that preserved
    the size; re-run without --cache if that matters.
    """
    entry = cache.get(relative)
    if not entry or entry.get("size_bytes") != size:
        return None
    if modified is not None and entry.get("modified") != modified:
        return None
    return entry.get("sha256")


def _report_progress(
    done: int,
    total: Optional[int],
    total_bytes: int,
    hashed_bytes: int,
    outstanding: int,
    elapsed: float,
    reused: int,
) -> None:
    counted = f"{done:,}" + (f"/{total:,}" if total else "")
    parts = [f"  {counted} files", _human_bytes(total_bytes)]
    if hashed_bytes and elapsed > 0:
        rate = hashed_bytes / elapsed
        parts.append(f"{_human_bytes(int(rate))}/s")
        left = outstanding - hashed_bytes
        if left > 0 and rate > 0:
            parts.append(f"~{_human_duration(left / rate)} left")
    if reused:
        parts.append(f"{reused:,} from cache")
    print(" · ".join(parts), file=sys.stderr)


def _human_duration(seconds: float) -> str:
    """A duration a person can act on: whether to wait, or come back later."""
    if seconds < 1:
        return "under a second"
    if seconds < 90:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 90:
        return f"{minutes:.0f} min"
    hours = int(minutes // 60)
    remainder = int(minutes % 60)
    return f"{hours}h {remainder:02d}m"


def load_cache(path: Path) -> Dict[str, Dict[str, Any]]:
    """Previously computed checksums, if any survive from an earlier run."""
    if not path or not path.is_file():
        return {}
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if content.get("cache_version") != CACHE_VERSION:
        return {}
    entries = content.get("entries")
    return entries if isinstance(entries, dict) else {}


def save_cache(path: Path, root: Path, entries: Dict[str, Dict[str, Any]]) -> None:
    """Write the cache atomically, so an interrupt cannot corrupt it."""
    if not path:
        return
    payload = {
        "cache_version": CACHE_VERSION,
        "root": str(root),
        "updated_at": _utc_iso(datetime.now(tz=timezone.utc).timestamp()),
        "entries": entries,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        # A cache that cannot be written is a lost optimisation, not a failure.
        pass


def estimate(
    root: Path,
    excludes: Tuple[str, ...] = DEFAULT_EXCLUDES,
    sample_bytes: int = 24 * 1024 * 1024,
    cache_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """How long a checksummed scan would take, measured rather than guessed.

    Reading a sample costs a few seconds and is worth it: on a drive that
    sustains 4 MB/s, a 45 GB scan takes three hours, and nobody should
    discover that an hour in.
    """
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Scan root is not a directory: {root}")

    skipped: List[Dict[str, str]] = []
    sizes: List[Tuple[Path, int]] = []
    for path in _walk(root, excludes, skipped):
        try:
            sizes.append((path, path.stat().st_size))
        except OSError:
            continue

    total_bytes = sum(size for _, size in sizes)
    cached = load_cache(cache_path) if cache_path else {}
    remaining = 0
    for path, size in sizes:
        entry = cached.get(_relative(path, root))
        if not (entry and entry.get("size_bytes") == size):
            remaining += size

    # Sample the largest files: they dominate the total, and their read speed
    # is what actually determines how long this takes.
    read = 0
    elapsed = 0.0
    for path, _ in sorted(sizes, key=lambda item: -item[1]):
        if read >= sample_bytes:
            break
        try:
            start = time.monotonic()
            with path.open("rb") as stream:
                while read < sample_bytes:
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    read += len(chunk)
            elapsed += time.monotonic() - start
        except OSError:
            continue

    rate = read / elapsed if elapsed > 0 and read else None
    return {
        "root": str(root),
        "file_count": len(sizes),
        "total_bytes": total_bytes,
        "remaining_bytes": remaining,
        "cached_count": len(sizes) - sum(
            1 for path, size in sizes
            if not (cached.get(_relative(path, root), {}).get("size_bytes") == size)
        ),
        "sampled_bytes": read,
        "bytes_per_second": rate,
        "seconds": (remaining / rate) if rate else None,
    }


def invocation(module: str) -> str:
    """How this was invoked, so printed hints match what the user typed.

    Run through the `ndos` dispatcher, argv[0] is "ndos organize"; run
    directly it is the script path. A hint telling someone to type a different
    command from the one that just worked is a small but real papercut.
    """
    program = sys.argv[0]
    if " " in program:
        return program
    return f"python3 {module}.py"


def _human_bytes(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Scan a directory and write a read-only NDOS JSON manifest.",
        epilog="This command never modifies, moves, or deletes source files.",
    )
    parser.add_argument("root", type=Path, help="Directory to inventory")
    parser.add_argument(
        "-o", "--output", type=Path, help="Manifest path; stdout when omitted"
    )
    parser.add_argument(
        "--no-checksum",
        action="store_true",
        help="Skip content checksums (much faster; disables duplicate detection)",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="Additional name pattern to skip; repeatable",
    )
    parser.add_argument(
        "--cache",
        nargs="?",
        const=CACHE_FILE,
        metavar="PATH",
        help=(
            f"Reuse and store checksums so an interrupted scan can carry on "
            f"(default file: {CACHE_FILE})"
        ),
    )
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="Measure how long a checksummed scan would take, then stop",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true", help="Suppress progress output"
    )
    args = parser.parse_args()

    excludes = DEFAULT_EXCLUDES + tuple(args.exclude)
    show_progress = not args.quiet
    cache_path = Path(args.cache) if args.cache else None

    if args.estimate:
        try:
            measured = estimate(args.root, excludes=excludes, cache_path=cache_path)
        except ValueError as error:
            parser.error(str(error))
        print(f"{measured['file_count']:,} files, {_human_bytes(measured['total_bytes'])}")
        if cache_path and measured["cached_count"]:
            print(
                f"{measured['cached_count']:,} already checksummed in "
                f"{cache_path}; {_human_bytes(measured['remaining_bytes'])} left to read"
            )
        if measured["bytes_per_second"]:
            print(
                f"This drive reads at about "
                f"{_human_bytes(int(measured['bytes_per_second']))}/s"
            )
            print(
                f"A checksummed scan would take roughly "
                f"{_human_duration(measured['seconds'])}."
            )
            if measured["seconds"] and measured["seconds"] > 600 and not cache_path:
                print()
                print(
                    "That is long enough to be worth making resumable: add "
                    "--cache and an interruption will cost minutes rather than "
                    "starting over."
                )
        else:
            print("Could not measure a read speed; nothing readable to sample.")
        return 0

    if show_progress:
        print(f"Scanning {args.root} (read-only)...", file=sys.stderr)

    try:
        manifest = scan(
            args.root,
            include_checksums=not args.no_checksum,
            excludes=excludes,
            progress=show_progress,
            cache_path=cache_path,
        )
    except ValueError as error:
        parser.error(str(error))
    except KeyboardInterrupt:
        return 130

    rendered = json.dumps(manifest, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        if show_progress:
            print(
                f"Wrote {manifest['file_count']} files "
                f"({_human_bytes(manifest['total_bytes'])}) to {args.output}",
                file=sys.stderr,
            )
    else:
        print(rendered, end="")

    reused = manifest.get("extensions", {}).get("cache", {}).get("reused", 0)
    if reused and show_progress:
        print(
            f"Reused {reused:,} checksums from {cache_path}.", file=sys.stderr
        )
    if (
        show_progress
        and not args.no_checksum
        and not cache_path
        and manifest["total_bytes"] > 5 * 1024 ** 3
    ):
        print(
            f"Tip: that was {_human_bytes(manifest['total_bytes'])}. Add --cache "
            "next time and a repeat or interrupted scan will not re-read it all. "
            f"'{invocation('ndos_scan')} --estimate' says how long it will take.",
            file=sys.stderr,
        )

    if manifest["skipped"] and show_progress:
        print(
            f"Skipped {len(manifest['skipped'])} entries; see the manifest "
            "'skipped' list for reasons.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
