#!/usr/bin/env python3
"""One command for every part of NDOS.

The modules each work on their own, but knowing that `ndos_archive.py inspect`
exists requires having been told. This gathers them behind a single command so
that `ndos --help` is enough to find everything:

    python3 ndos.py report /path/to/data
    python3 ndos.py organize apply /path/to/data -d ./project
    python3 ndos.py --help

Each subcommand is the module of the same name, so `ndos.py scan --help` shows
exactly what `ndos_scan.py --help` shows, and anything documented for one works
for the other.

Standard library only, and importable without installation.
"""

from __future__ import annotations

import importlib
import sys
from typing import Dict, List, Tuple

VERSION = "0.1.0"

#: Subcommand, module, and the one line shown by `ndos --help`. Ordered the way
#: the work runs: understand, structure, describe, use, hand off.
COMMANDS: Tuple[Tuple[str, str, str], ...] = (
    ("report", "ndos_report", "Summarise a directory you have inherited"),
    ("scan", "ndos_scan", "Write a read-only inventory of what is on disk"),
    ("archive", "ndos_archive", "Read inside archives without extracting them"),
    ("organize", "ndos_organize", "Rebuild the N-DOS layout from existing structure"),
    ("table", "ndos_table", "Round-trip lab metadata through spreadsheets"),
    ("tags", "ndos_tags", "Flag data validated, temporary, or safe to delete"),
    ("protect", "ndos_protect", "Make raw data read-only after acquisition"),
    ("query", "ndos_query", "Build a cohort, with the evidence behind each match"),
    ("prov", "ndos_prov", "Record what produced a result, and trace it back"),
    ("convert", "ndos_convert", "Hand off to BIDS and NWB workflows"),
    ("init", "ndos_init", "Create an NDOS project profile"),
)

BY_NAME: Dict[str, Tuple[str, str]] = {
    name: (module, summary) for name, module, summary in COMMANDS
}

USAGE = """NDOS — organise, describe and trace wet-lab and animal neuroscience data.

Usage:
  {program} <command> [options]
  {program} <command> --help     what that command accepts
  {program} --version

Commands:
{commands}

Start here if you have a directory nobody understands any more:
  {program} report /path/to/data

Nothing NDOS does modifies your data unless you ask it to, and the commands
that can write always show a plan and confirm first.
"""


def _render_usage(program: str) -> str:
    width = max(len(name) for name, _, _ in COMMANDS)
    lines = [
        f"  {name.ljust(width)}   {summary}" for name, _, summary in COMMANDS
    ]
    return USAGE.format(program=program, commands="\n".join(lines))


def main(argv: List[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    program = "ndos" if sys.argv[0].endswith(("ndos", "ndos.py")) else sys.argv[0]

    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_render_usage(program), end="")
        return 0
    if argv[0] in ("-V", "--version", "version"):
        print(f"ndos {VERSION}")
        return 0

    name = argv[0]
    if name not in BY_NAME:
        print(f"{program}: unknown command {name!r}", file=sys.stderr)
        matches = [
            candidate for candidate, _, _ in COMMANDS if candidate.startswith(name[:3])
        ]
        if matches:
            print(f"Did you mean: {', '.join(matches)}?", file=sys.stderr)
        print(f"Run '{program} --help' for the full list.", file=sys.stderr)
        return 2

    module_name, _ = BY_NAME[name]
    module = importlib.import_module(module_name)

    # Rewrite argv so each module's own --help reads as "ndos report ..."
    # rather than naming the file it happens to live in.
    saved = sys.argv
    sys.argv = [f"{program} {name}"] + argv[1:]
    try:
        return module.main()
    finally:
        sys.argv = saved


if __name__ == "__main__":
    raise SystemExit(main())
