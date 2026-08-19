#!/usr/bin/env python3
Create N-DOS project scaffold.
Usage:
  python ndos_create.py /path/to/project [--force]

import argparse
from pathlib import Path

DEFAULT_DIRS = ["raw_data","processed_data","analysis","figures","scripts"]

def create_project(root: Path, force: bool=False):
    root.mkdir(parents=True, exist_ok=True)
    for d in DEFAULT_DIRS:
        p = root / d
        if p.exists() and not force:
            continue
        p.mkdir(parents=True, exist_ok=True)
    readme = root / "README.md"
    if not readme.exists() or force:
        readme.write_text("# N-DOS Project\n\nThis project follows the N-DOS layout.\n")
    print(f"[OK] Created/updated N-DOS scaffold at: {root}")

def main():
    ap = argparse.ArgumentParser(description="Create N-DOS scaffold")
    ap.add_argument("root", type=Path, help="Project root")
    ap.add_argument("--force", action="store_true", help="Overwrite existing items if present")
    args = ap.parse_args()
    create_project(args.root, args.force)

if __name__ == "__main__":
    main()
