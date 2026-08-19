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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple


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
) -> Dict[str, Any]:
    """Return a manifest of ``root`` without changing anything below it."""
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Scan root is not a directory: {root}")

    files: List[Dict[str, Any]] = []
    skipped: List[Dict[str, str]] = []
    total_bytes = 0

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

        entry: Dict[str, Any] = {
            "path": _relative(path, root),
            "name": path.name,
            "extension": path.suffix.lower(),
            "size_bytes": stat.st_size,
            "modified": _utc_iso(stat.st_mtime),
            "role": "unknown",
        }

        if include_checksums:
            try:
                entry["sha256"] = _sha256(path)
            except OSError as error:
                skipped.append(
                    {
                        "path": entry["path"],
                        "reason": "unreadable-file",
                        "detail": error.strerror or "unknown error",
                    }
                )
                continue

        files.append(entry)
        total_bytes += stat.st_size

        if progress and len(files) % 500 == 0:
            print(
                f"  ...{len(files)} files, {_human_bytes(total_bytes)}",
                file=sys.stderr,
            )

    files.sort(key=lambda entry: entry["path"])
    skipped.sort(key=lambda entry: (entry["reason"], entry["path"]))

    return {
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
        "-q", "--quiet", action="store_true", help="Suppress progress output"
    )
    args = parser.parse_args()

    excludes = DEFAULT_EXCLUDES + tuple(args.exclude)
    show_progress = not args.quiet

    if show_progress:
        print(f"Scanning {args.root} (read-only)...", file=sys.stderr)

    try:
        manifest = scan(
            args.root,
            include_checksums=not args.no_checksum,
            excludes=excludes,
            progress=show_progress,
        )
    except ValueError as error:
        parser.error(str(error))

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

    if manifest["skipped"] and show_progress:
        print(
            f"Skipped {len(manifest['skipped'])} entries; see the manifest "
            "'skipped' list for reasons.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
