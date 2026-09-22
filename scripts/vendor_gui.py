#!/usr/bin/env python3
"""Build the interface and copy the result into the package.

The interface ships built. That is what lets `pip install ndos` be the whole
install on a machine with no Node and no network: the browser gets a bundle
that was compiled here, not on the lab's computer.

The cost of shipping a build is that it can go stale. Someone edits
gui/src, runs the tests, sees them pass, and ships a package whose interface
is a previous version of itself -- with nothing to say so, because the
committed bundle is unreadable and its filenames are hashes.

So the bundle records what it was built from. This script writes
ndos_gui_static/BUILD.json with a fingerprint of the sources, and --check
recomputes that fingerprint and fails if the sources have moved on. The check
needs no Node, so it runs everywhere the tests do rather than only where a
toolchain happens to be installed.

    python3 scripts/vendor_gui.py            # build and copy
    python3 scripts/vendor_gui.py --check    # is the shipped copy current?
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUI = ROOT / "gui"
DIST = GUI / "dist"
TARGET = ROOT / "ndos_gui_static"
RECORD = TARGET / "BUILD.json"

#: Everything the build reads. A change to any of it means the shipped bundle
#: is no longer what these sources produce. package-lock.json is in the list
#: because a dependency bump changes the output just as surely as an edit to a
#: component does.
SOURCES = (
    "src",
    "public",
    "index.html",
    "vite.config.ts",
    "tsconfig.json",
    "package.json",
    "package-lock.json",
)

#: Written by the copy, not by the build, so they are not part of the source
#: fingerprint and must survive being overwritten.
KEEP = {"__init__.py", "BUILD.json"}

IGNORE = {"__pycache__", ".DS_Store", "node_modules"}


def _files() -> list[Path]:
    """Every source file the build reads, in a stable order."""
    found: list[Path] = []
    for name in SOURCES:
        path = GUI / name
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found.extend(
                p
                for p in path.rglob("*")
                if p.is_file() and not (IGNORE & set(p.parts))
            )
    return sorted(found)


def fingerprint() -> str:
    """One hash over the sources, covering names as well as contents.

    A renamed file with identical contents is a different build, so the path
    goes into the hash beside the bytes.
    """
    digest = hashlib.sha256()
    for path in _files():
        digest.update(path.relative_to(GUI).as_posix().encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _tool_version(*command: str) -> str:
    try:
        out = subprocess.run(command, capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:
        return "unknown"


def build() -> None:
    if not (GUI / "node_modules").is_dir():
        print("installing interface dependencies (npm ci)")
        subprocess.run(["npm", "ci"], cwd=GUI, check=True)
    print("building the interface (npm run build)")
    subprocess.run(["npm", "run", "build"], cwd=GUI, check=True)


def vendor() -> None:
    if not DIST.is_dir():
        raise SystemExit(f"the build produced nothing at {DIST}")

    # Replace the contents rather than the directory: __init__.py is what makes
    # this a package, and a wheel carries only what belongs to one.
    for existing in TARGET.iterdir():
        if existing.name in KEEP:
            continue
        shutil.rmtree(existing) if existing.is_dir() else existing.unlink()
    for item in DIST.iterdir():
        destination = TARGET / item.name
        if item.is_dir():
            shutil.copytree(item, destination)
        else:
            shutil.copy2(item, destination)

    RECORD.write_text(
        json.dumps(
            {
                "sources": fingerprint(),
                "built": datetime.now(tz=timezone.utc)
                .replace(microsecond=0)
                .isoformat()
                .replace("+00:00", "Z"),
                "node": _tool_version("node", "--version"),
                "npm": _tool_version("npm", "--version"),
            },
            indent=2,
        )
        + "\n"
    )
    count = sum(1 for p in TARGET.rglob("*") if p.is_file())
    print(f"copied {count} files into {TARGET.relative_to(ROOT)}")


def check() -> int:
    if not RECORD.is_file():
        print(
            f"{RECORD.relative_to(ROOT)} is missing, so there is no way to tell "
            "what the shipped interface was built from.\n"
            "Run: python3 scripts/vendor_gui.py",
            file=sys.stderr,
        )
        return 1

    recorded = json.loads(RECORD.read_text()).get("sources")
    current = fingerprint()
    if recorded != current:
        print(
            "The interface in ndos_gui_static/ was built from different sources "
            "than the ones in gui/.\n"
            f"  shipped: {recorded}\n"
            f"  gui/:    {current}\n"
            "Rebuild and re-vendor it, then commit the result:\n"
            "  python3 scripts/vendor_gui.py",
            file=sys.stderr,
        )
        return 1

    print(f"the shipped interface matches gui/ ({current[:12]})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the shipped interface is current, building nothing",
    )
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="copy whatever is already in gui/dist instead of building first",
    )
    args = parser.parse_args(argv)

    if args.check:
        return check()
    if not args.no_build:
        build()
    vendor()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
