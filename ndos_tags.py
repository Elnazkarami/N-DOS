#!/usr/bin/env python3
"""Flag files as validated, temporary, or safe to delete.

The N-DOS layout says each dataset may carry a JSON file with flags such as
`{"validated": true, "temp": false, "deletable": false}`. Those flags are what
make `flagged_data/` and `temp/` operable rather than merely named: without
them, nobody can answer "is this checked?" or "can I free this space?".

Tags live in a `tags.json` beside the data they describe, one per session, so
a session directory remains self-describing if it is moved or copied.

    set     flag files
    get     read the flags on a file
    list    find files by flag across a project
    sweep   plan the removal of temporary or deletable files

`sweep` never deletes on its own. The manuscript imagines a maintenance script
removing temporary files automatically; deletion driven by a hand-edited flag
is how a lab loses data it meant to keep, so this plans and confirms instead.

Standard library only. Run it directly with no installation.
"""

from __future__ import annotations

import argparse
import csv
import fnmatch
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ndos_scan

TAGS_VERSION = "0.1"
TAGS_FILE = "tags.json"

#: The flags named in the manuscript, with the meaning each carries.
FLAGS: Dict[str, str] = {
    "validated": "someone checked this and considers it good",
    "temp": "scratch output that exists only until validation",
    "deletable": "confirmed safe to remove",
}

#: Filenames and directories that are scratch by convention, so a lab does not
#: have to flag every intermediate a spike sorter produced by hand.
#: Directory names that mean scratch.
TEMP_DIRS = (
    "temp", "tmp", "scratch", "phy_output", ".phy", ".kilosort",
    "kilosort_tmp", "mountainsort_tmp",
)

#: Exact filenames that are scratch by convention. Deliberately narrow:
#: "recording.dat" would look like scratch and is very often real data.
TEMP_FILES = ("temp_wh.dat", "proc.dat", ".phy.log")


class TagError(Exception):
    """Tags could not be read or written."""


# --------------------------------------------------------------------------
# storage
# --------------------------------------------------------------------------

def tags_path(target: Path) -> Path:
    """Where the tags for a file live: beside it, one per directory."""
    target = target.expanduser()
    directory = target if target.is_dir() else target.parent
    return directory / TAGS_FILE


def read_tags(path: Path) -> Dict[str, Any]:
    """Load a tags file, or an empty one if it does not exist yet."""
    if not path.is_file():
        return {
            "tags_version": TAGS_VERSION,
            "generator": {"name": "ndos-tags", "version": TAGS_VERSION},
            "files": {},
        }
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TagError(f"could not read {path}: {error}")
    content.setdefault("files", {})
    return content


def write_tags(path: Path, content: Dict[str, Any]) -> None:
    content["tags_version"] = TAGS_VERSION
    content["updated_at"] = ndos_scan._utc_iso(
        datetime.now(tz=timezone.utc).timestamp()
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def get_tags(target: Path, root: Optional[Path] = None) -> Dict[str, Any]:
    """Flags recorded for one file, including any inferred from convention."""
    entry = dict(read_tags(tags_path(target))["files"].get(target.name, {}))
    if "temp" not in entry and looks_temporary(target, root):
        entry["temp"] = True
        entry["temp_inferred"] = True
    return entry


def looks_temporary(target: Path, root: Optional[Path] = None) -> bool:
    """Whether a path is scratch by convention rather than by declaration.

    Only the parts below ``root`` are considered. Judging the absolute path
    would mark every file in a project that happens to live under /tmp, or
    under any directory a user happened to name "temp".
    """
    target = Path(target)
    parts = target.parts
    if root is not None:
        try:
            parts = target.resolve().relative_to(Path(root).resolve()).parts
        except (ValueError, OSError):
            parts = target.parts
    directories = [part.lower() for part in parts[:-1]]
    return any(
        directory == hint or directory.startswith(hint + "_")
        for hint in TEMP_DIRS
        for directory in directories
    ) or target.name.lower() in TEMP_FILES


def set_tags(
    target: Path,
    flags: Dict[str, bool],
    note: Optional[str] = None,
    author: Optional[str] = None,
) -> Dict[str, Any]:
    """Record flags for a file, keeping who said so and when."""
    if not target.exists():
        raise TagError(f"no such file: {target}")
    unknown = set(flags) - set(FLAGS)
    if unknown:
        raise TagError(
            f"unknown flag(s) {', '.join(sorted(unknown))}. "
            f"Known flags: {', '.join(sorted(FLAGS))}"
        )

    path = tags_path(target)
    content = read_tags(path)
    entry = content["files"].setdefault(target.name, {})
    entry.update({name: bool(value) for name, value in flags.items()})
    if note:
        entry["note"] = note
    entry["updated_at"] = ndos_scan._utc_iso(
        datetime.now(tz=timezone.utc).timestamp()
    )
    if author:
        entry["author"] = author

    # Deleting data because a flag says so is irreversible, so the two
    # statements are kept apart: validated data is not scratch.
    if entry.get("deletable") and entry.get("validated"):
        entry["conflict"] = (
            "marked both validated and deletable; check before any sweep"
        )
    else:
        entry.pop("conflict", None)

    write_tags(path, content)
    return entry


# --------------------------------------------------------------------------
# querying
# --------------------------------------------------------------------------

def collect(root: Path) -> List[Dict[str, Any]]:
    """Every tagged file below a directory, with its flags."""
    root = root.expanduser().resolve()
    found: List[Dict[str, Any]] = []
    for path in sorted(root.rglob(TAGS_FILE)):
        try:
            content = read_tags(path)
        except TagError:
            continue
        for name, entry in sorted(content["files"].items()):
            target = path.parent / name
            found.append(
                {
                    "path": str(target),
                    "relative": str(target.relative_to(root))
                    if str(target).startswith(str(root)) else str(target),
                    "exists": target.exists(),
                    "size_bytes": target.stat().st_size if target.is_file() else 0,
                    "flags": entry,
                }
            )
    return found


def select(
    entries: Sequence[Dict[str, Any]],
    flag: Optional[str] = None,
    value: bool = True,
    pattern: Optional[str] = None,
) -> List[Dict[str, Any]]:
    chosen = []
    for entry in entries:
        if flag is not None and bool(entry["flags"].get(flag)) is not value:
            continue
        if pattern and not fnmatch.fnmatch(Path(entry["path"]).name, pattern):
            continue
        chosen.append(entry)
    return chosen


def plan_sweep(root: Path, include_inferred: bool = False) -> Dict[str, Any]:
    """What a cleanup would remove, and what it deliberately would not."""
    root = root.expanduser().resolve()
    tagged = collect(root)

    removable: List[Dict[str, Any]] = []
    withheld: List[Dict[str, Any]] = []

    for entry in tagged:
        flags = entry["flags"]
        if not entry["exists"]:
            continue
        wanted = flags.get("deletable") or flags.get("temp")
        if not wanted:
            continue
        if flags.get("validated"):
            # Never remove something a person has vouched for, whatever else
            # the flags say.
            withheld.append({**entry, "reason": "marked validated"})
            continue
        if flags.get("conflict"):
            withheld.append({**entry, "reason": flags["conflict"]})
            continue
        removable.append(
            {
                **entry,
                "because": "deletable" if flags.get("deletable") else "temp",
            }
        )

    inferred: List[Dict[str, Any]] = []
    if include_inferred:
        known = {entry["path"] for entry in tagged}
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name == TAGS_FILE:
                continue
            if str(path) in known or not looks_temporary(path, root):
                continue
            inferred.append(
                {
                    "path": str(path),
                    "relative": str(path.relative_to(root)),
                    "size_bytes": path.stat().st_size,
                    "because": "looks temporary by convention, not declared",
                }
            )

    return {
        "root": str(root),
        "generated_at": ndos_scan._utc_iso(
            datetime.now(tz=timezone.utc).timestamp()
        ),
        "removable": removable,
        "removable_bytes": sum(e["size_bytes"] for e in removable),
        "inferred": inferred,
        "inferred_bytes": sum(e["size_bytes"] for e in inferred),
        "withheld": withheld,
    }


def apply_sweep(plan: Dict[str, Any], include_inferred: bool = False) -> Dict[str, Any]:
    """Remove what a sweep plan listed. Called only after confirmation."""
    removed, failed = [], []
    targets = list(plan["removable"])
    if include_inferred:
        targets += plan["inferred"]
    for entry in targets:
        path = Path(entry["path"])
        try:
            path.unlink()
            removed.append(str(path))
        except OSError as error:
            failed.append({"path": str(path), "reason": str(error)})
    return {"removed": removed, "removed_count": len(removed), "failed": failed}


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

_bytes = ndos_scan._human_bytes


def render_list(entries: Sequence[Dict[str, Any]], root: Path) -> str:
    out: List[str] = []
    add = out.append
    add("=" * 72)
    add(f"NDOS TAGS ({len(entries)})")
    add("=" * 72)
    add(f"Under {root}")
    if not entries:
        add("")
        add("No tags recorded yet. Flag something with:")
        add(f"  {ndos_scan.invocation('ndos_tags')} set FILE --validated")
        return "\n".join(out) + "\n"

    add("")
    for entry in entries:
        flags = entry["flags"]
        marks = " ".join(
            f"{name}={str(bool(flags.get(name))).lower()}"
            for name in sorted(FLAGS) if name in flags
        )
        missing = "" if entry["exists"] else "  [FILE MISSING]"
        add(f"  {entry['relative']}{missing}")
        add(f"      {marks or '(no flags)'}")
        if flags.get("note"):
            add(f"      note: {flags['note']}")
        if flags.get("conflict"):
            add(f"      *** {flags['conflict']}")
    return "\n".join(out) + "\n"


def render_sweep(plan: Dict[str, Any], include_inferred: bool) -> str:
    out: List[str] = []
    add = out.append
    add("=" * 72)
    add("NDOS SWEEP PLAN")
    add("=" * 72)
    add(f"Under       : {plan['root']}")
    add(
        f"Would remove: {len(plan['removable'])} files, "
        f"{_bytes(plan['removable_bytes'])}"
    )
    if include_inferred:
        add(
            f"  plus      : {len(plan['inferred'])} untagged files that look "
            f"temporary, {_bytes(plan['inferred_bytes'])}"
        )
    add(f"Withheld    : {len(plan['withheld'])}")
    add("")

    if plan["removable"]:
        add("-" * 72)
        add("WOULD BE DELETED")
        add("-" * 72)
        for entry in plan["removable"][:20]:
            add(f"  {_bytes(entry['size_bytes']):>10}  {entry['relative']}")
            add(f"              flagged {entry['because']}")
        if len(plan["removable"]) > 20:
            add(f"  ... and {len(plan['removable']) - 20} more")
        add("")

    if include_inferred and plan["inferred"]:
        add("-" * 72)
        add("LOOK TEMPORARY BUT WERE NEVER FLAGGED")
        add("-" * 72)
        add("  Identified by naming convention alone. Nobody has confirmed these.")
        for entry in plan["inferred"][:10]:
            add(f"  {_bytes(entry['size_bytes']):>10}  {entry['relative']}")
        if len(plan["inferred"]) > 10:
            add(f"  ... and {len(plan['inferred']) - 10} more")
        add("")

    if plan["withheld"]:
        add("-" * 72)
        add("KEPT DESPITE THEIR FLAGS")
        add("-" * 72)
        for entry in plan["withheld"][:10]:
            add(f"  {entry['relative']}")
            add(f"      {entry['reason']}")
        add("")

    add("-" * 72)
    add("Nothing has been deleted. Deletion is irreversible; run 'sweep --apply'")
    add("only after reading the list above.")
    add("-" * 72)
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def command_set(args: argparse.Namespace) -> int:
    flags: Dict[str, bool] = {}
    for name in FLAGS:
        value = getattr(args, name)
        if value is not None:
            flags[name] = value
    if not flags and not args.note:
        print(
            "Nothing to set. Use --validated/--no-validated, --temp/--no-temp, "
            "--deletable/--no-deletable, or --note.",
            file=sys.stderr,
        )
        return 2

    for target in args.files:
        entry = set_tags(target, flags, note=args.note, author=args.author)
        if not args.quiet:
            shown = " ".join(
                f"{name}={str(bool(entry.get(name))).lower()}"
                for name in sorted(FLAGS) if name in entry
            )
            print(f"{target}: {shown}", file=sys.stderr)
            if entry.get("conflict"):
                print(f"  warning: {entry['conflict']}", file=sys.stderr)
    return 0


def command_get(args: argparse.Namespace) -> int:
    entry = get_tags(args.file, root=args.root)
    if args.format == "json":
        print(json.dumps(entry, indent=2, sort_keys=True))
        return 0
    if not entry:
        print(f"{args.file}: no flags recorded")
        return 0
    print(f"{args.file}")
    for name in sorted(entry):
        print(f"  {name}: {entry[name]}")
    return 0


def command_list(args: argparse.Namespace) -> int:
    entries = select(
        collect(args.root), flag=args.flag, value=not args.false, pattern=args.name
    )
    if args.format == "json":
        print(json.dumps(entries, indent=2))
    else:
        print(render_list(entries, args.root), end="")
    return 0


def build_index(root: Path) -> List[Dict[str, Any]]:
    """The validated files, as the reference index a pipeline can load.

    The standard asks each project to carry a table of the data that has been
    checked. That is the list an analysis should read, rather than globbing a
    directory and hoping everything in it is good.
    """
    rows = []
    for entry in select(collect(root), flag="validated"):
        if not entry["exists"]:
            continue
        flags = entry["flags"]
        if flags.get("temp") or flags.get("deletable"):
            continue  # validated but also scratch: not something to build on
        path = Path(entry["path"])
        parts = path.relative_to(Path(root).expanduser().resolve()).parts
        rows.append(
            {
                "path": entry["relative"],
                "role": parts[0] if parts else "",
                "subject": parts[1] if len(parts) > 2 else "",
                "session": parts[2] if len(parts) > 3 else "",
                "size_bytes": entry["size_bytes"],
                "validated_by": flags.get("author", ""),
                "validated_at": flags.get("updated_at", ""),
                "note": flags.get("note", ""),
            }
        )
    return sorted(rows, key=lambda row: row["path"])


def command_index(args: argparse.Namespace) -> int:
    rows = build_index(args.root)

    if args.format == "json":
        rendered = json.dumps(rows, indent=2) + "\n"
    else:
        buffer = io.StringIO()
        columns = [
            "path", "role", "subject", "session", "size_bytes",
            "validated_by", "validated_at", "note",
        ]
        writer = csv.DictWriter(buffer, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        rendered = buffer.getvalue()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8-sig")
        print(
            f"{len(rows)} validated files -> {args.output}", file=sys.stderr
        )
    else:
        print(rendered, end="")

    if not rows:
        print(
            "Nothing is marked validated yet. Flag data you have checked with "
            f"'{ndos_scan.invocation('ndos_tags')} set FILE --validated'.",
            file=sys.stderr,
        )
    return 0


def command_sweep(args: argparse.Namespace) -> int:
    plan = plan_sweep(args.root, include_inferred=args.include_untagged)
    print(render_sweep(plan, args.include_untagged), end="")

    if not args.apply:
        return 0

    count = len(plan["removable"]) + (
        len(plan["inferred"]) if args.include_untagged else 0
    )
    if not count:
        print("Nothing to remove.", file=sys.stderr)
        return 0

    if not args.yes:
        try:
            answer = input(f"\nPermanently delete {count} files? [y/N] ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("Cancelled. Nothing was deleted.", file=sys.stderr)
            return 1

    result = apply_sweep(plan, include_inferred=args.include_untagged)
    print(
        f"Deleted {result['removed_count']} files, {len(result['failed'])} failed.",
        file=sys.stderr,
    )
    return 1 if result["failed"] else 0


def _flag_pair(parser: argparse.ArgumentParser, name: str, help_text: str) -> None:
    parser.add_argument(
        f"--{name}", dest=name, action="store_true", default=None, help=help_text
    )
    parser.add_argument(
        f"--no-{name}", dest=name, action="store_false", help=f"clear {name}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Flag files as validated, temporary, or safe to delete.",
        epilog="Tags are stored in tags.json beside the data they describe.",
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    setter = subparsers.add_parser("set", help="Flag one or more files")
    setter.add_argument("files", type=Path, nargs="+")
    for name, description in FLAGS.items():
        _flag_pair(setter, name, description)
    setter.add_argument("--note", help="Why, in a sentence")
    setter.add_argument("--author", help="Who is saying so")
    setter.add_argument("-q", "--quiet", action="store_true")
    setter.set_defaults(func=command_set)

    getter = subparsers.add_parser("get", help="Show the flags on a file")
    getter.add_argument("file", type=Path)
    getter.add_argument(
        "--root", type=Path, help="Project root, so scratch is judged relative to it"
    )
    getter.add_argument("-f", "--format", choices=("text", "json"), default="text")
    getter.set_defaults(func=command_get)

    lister = subparsers.add_parser("list", help="Find tagged files in a project")
    lister.add_argument("root", type=Path, nargs="?", default=Path("."))
    lister.add_argument("--flag", choices=sorted(FLAGS), help="Only files with this flag")
    lister.add_argument(
        "--false", action="store_true", help="Match where the flag is false instead"
    )
    lister.add_argument("--name", help="Only filenames matching this glob")
    lister.add_argument("-f", "--format", choices=("text", "json"), default="text")
    lister.set_defaults(func=command_list)

    indexer = subparsers.add_parser(
        "index",
        help="Write the table of validated files a pipeline should read",
    )
    indexer.add_argument("root", type=Path, nargs="?", default=Path("."))
    indexer.add_argument(
        "-o", "--output", type=Path, help="Write here; stdout when omitted"
    )
    indexer.add_argument("-f", "--format", choices=("csv", "json"), default="csv")
    indexer.set_defaults(func=command_index)

    sweeper = subparsers.add_parser(
        "sweep", help="Plan removal of temporary or deletable files"
    )
    sweeper.add_argument("root", type=Path, nargs="?", default=Path("."))
    sweeper.add_argument(
        "--include-untagged", action="store_true",
        help="Also list files that look temporary but were never flagged",
    )
    sweeper.add_argument(
        "--apply", action="store_true", help="Actually delete, after confirmation"
    )
    sweeper.add_argument("--yes", action="store_true", help="Skip the confirmation")
    sweeper.set_defaults(func=command_sweep)

    args = parser.parse_args()
    try:
        return args.func(args)
    except (TagError, OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
