#!/usr/bin/env python3
"""Initialize an NDOS project without migrating source data."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


PROJECT_DIRECTORIES = ("manifests", "provenance", "features", "exports")


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
        'source_mode = "read-only"\n'
        'raw_data = "external"\n'
    )


def initialize(root: Path, project_id: str | None = None, force: bool = False) -> Path:
    """Create an NDOS project profile and owned directories."""
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    project_file = root / "project.toml"
    if project_file.exists() and not force:
        raise FileExistsError(f"Project already initialized: {project_file}")

    name = root.name
    project_file.write_text(
        _project_toml(name, project_id or _project_id(name)), encoding="utf-8"
    )
    for directory in PROJECT_DIRECTORIES:
        (root / directory).mkdir(exist_ok=True)
    return project_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize an NDOS project.")
    parser.add_argument("root", type=Path, help="NDOS project directory")
    parser.add_argument("--project-id", help="Stable logical project identifier")
    parser.add_argument(
        "--force", action="store_true", help="Replace an existing project.toml"
    )
    args = parser.parse_args()

    try:
        project_file = initialize(args.root, args.project_id, args.force)
    except (FileExistsError, OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Initialized NDOS project: {project_file.parent}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())