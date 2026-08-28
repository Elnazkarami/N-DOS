#!/usr/bin/env python3
"""Make raw data read-only, and check that it stayed that way.

The standard says raw data should be "set as read-only after acquisition". A
recording is the one thing in a project that can never be regenerated, and the
usual way it is lost is not a disk failure but a script writing where it
should have been reading.

    ndos protect ./my-study            # what it would change
    ndos protect ./my-study --apply    # take away write permission
    ndos protect ./my-study --check    # has anything become writable again?
    ndos protect ./my-study --release  # give it back, deliberately

This changes file permissions and never file contents. Releasing is as easy as
protecting, on purpose: a protection people cannot undo is one they work around
by copying data somewhere unprotected.

Standard library only. Run it directly with no installation.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import ndos_scan

PROTECT_VERSION = "0.1"

#: Directories holding data that should not change once acquired.
DEFAULT_TARGETS = ("raw_data",)

#: Write bits, for owner, group and others.
WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


def _is_writable(path: Path) -> bool:
    try:
        return bool(path.stat().st_mode & WRITE_BITS)
    except OSError:
        return False


def _files(root: Path, targets: Sequence[str]) -> List[Path]:
    """Every file under the named subdirectories of a project."""
    root = root.expanduser().resolve()
    found: List[Path] = []
    for name in targets:
        directory = root / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            # Links are left alone: the permission that matters belongs to
            # whatever the link points at, which may not be ours to change.
            if path.is_file() and not path.is_symlink():
                found.append(path)
    return found


def survey(root: Path, targets: Sequence[str] = DEFAULT_TARGETS) -> Dict[str, Any]:
    """What is writable, and therefore still at risk."""
    files = _files(root, targets)
    writable = [path for path in files if _is_writable(path)]
    return {
        "root": str(Path(root).expanduser().resolve()),
        "targets": list(targets),
        "checked_at": ndos_scan._utc_iso(
            datetime.now(tz=timezone.utc).timestamp()
        ),
        "file_count": len(files),
        "writable_count": len(writable),
        "protected_count": len(files) - len(writable),
        "writable": [str(path) for path in writable],
        "bytes": sum(
            path.stat().st_size for path in files if path.exists()
        ),
    }


def apply_protection(
    root: Path, targets: Sequence[str] = DEFAULT_TARGETS, release: bool = False
) -> Dict[str, Any]:
    """Remove write permission, or give it back."""
    changed: List[str] = []
    failed: List[Dict[str, str]] = []

    for path in _files(root, targets):
        try:
            mode = path.stat().st_mode
            new = (mode | stat.S_IWUSR) if release else (mode & ~WRITE_BITS)
            if new == mode:
                continue
            os.chmod(path, new)
            changed.append(str(path))
        except OSError as error:
            failed.append({"path": str(path), "reason": error.strerror or str(error)})

    return {
        "released" if release else "protected": changed,
        "changed_count": len(changed),
        "failed": failed,
    }


def render(state: Dict[str, Any], release: bool = False) -> str:
    out: List[str] = []
    add = out.append
    add("=" * 72)
    add("NDOS RAW DATA PROTECTION")
    add("=" * 72)
    add(f"Project   : {state['root']}")
    add(f"Covering  : {', '.join(state['targets'])}")
    add(
        f"Files     : {state['file_count']:,}, "
        f"{ndos_scan._human_bytes(state['bytes'])}"
    )
    add(f"Writable  : {state['writable_count']:,}")
    add(f"Read-only : {state['protected_count']:,}")
    add("")

    if release:
        add("-" * 72)
        add(f"Would make {state['protected_count']:,} files writable again.")
        add("-" * 72)
        return "\n".join(out) + "\n"

    if not state["writable_count"]:
        add("-" * 72)
        add("Everything here is already read-only. Nothing to do.")
        add("-" * 72)
        return "\n".join(out) + "\n"

    add("-" * 72)
    add(f"WOULD BECOME READ-ONLY ({state['writable_count']:,})")
    add("-" * 72)
    for path in state["writable"][:15]:
        add(f"  {path}")
    if state["writable_count"] > 15:
        add(f"  ... and {state['writable_count'] - 15:,} more")
    add("")
    add("-" * 72)
    add("Permissions only; file contents are never touched. Nothing has")
    add("changed yet — add --apply to carry this out.")
    add("-" * 72)
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Make raw data read-only after acquisition, as the standard asks.",
        epilog=(
            "Permissions are changed; contents never are. --release undoes it, "
            "deliberately made as easy as applying it."
        ),
    )
    parser.add_argument("root", type=Path, help="N-DOS project directory")
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        metavar="DIR",
        help=f"Directory to cover; repeatable (default: {', '.join(DEFAULT_TARGETS)})",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Carry it out rather than describing it"
    )
    parser.add_argument(
        "--release", action="store_true", help="Make the files writable again"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if anything that should be read-only is writable",
    )
    parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation")
    args = parser.parse_args()

    targets = tuple(args.target) or DEFAULT_TARGETS
    root = args.root.expanduser()
    if not root.is_dir():
        parser.error(f"not a directory: {root}")

    state = survey(root, targets)
    if not state["file_count"]:
        print(
            f"No files under {', '.join(targets)} in {state['root']}. "
            "Is this an N-DOS project?",
            file=sys.stderr,
        )
        return 0

    if args.format == "json":
        print(json.dumps(state, indent=2))
    else:
        print(render(state, release=args.release), end="")

    if args.check:
        # Made for a cron job or a pre-publication check: silence means the
        # raw data is still as it was acquired.
        return 1 if state["writable_count"] else 0

    if not args.apply and not args.release:
        return 0

    if not args.yes:
        verb = "make writable again" if args.release else "make read-only"
        count = (
            state["protected_count"] if args.release else state["writable_count"]
        )
        if not count:
            return 0
        try:
            answer = input(f"\n{verb.capitalize()}: {count:,} files? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was changed.", file=sys.stderr)
            return 1

    result = apply_protection(root, targets, release=args.release)
    print(
        f"Changed {result['changed_count']:,} files. "
        f"{len(result['failed'])} could not be changed.",
        file=sys.stderr,
    )
    for failure in result["failed"][:5]:
        print(f"  {failure['path']}: {failure['reason']}", file=sys.stderr)
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
