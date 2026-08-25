#!/usr/bin/env python3
"""Record what was run, on what, and what came out.

Provenance normally goes uncaptured because capturing it means instrumenting
analysis code, and nobody rewrites a working script to satisfy a data policy.
So this wraps the command instead:

    python3 ndos_prov.py run --input raw/ --output results/ -- python analyse.py

Nothing about `analyse.py` changes. NDOS checksums the inputs, watches the
output directories before and after, records the code version and environment,
and writes a run record. Later, `trace` walks backwards from any output file
to the raw data and the command that produced it.

Failed runs are recorded too. "This figure came from a script that exited 1"
is provenance worth having.

Standard library only. Run it directly with no installation.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import platform
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import ndos_scan

PROVENANCE_VERSION = "0.1"
GENERATOR_VERSION = "0.1.0"

#: Bytes of stdout/stderr kept with the record. Enough to diagnose a failure,
#: far too little to become a log store.
CAPTURE_LIMIT = 8192

DEFAULT_DIR = Path("provenance")


# --------------------------------------------------------------------------
# snapshots
# --------------------------------------------------------------------------

def _snapshot(paths: Sequence[Path]) -> Dict[str, Dict[str, Any]]:
    """Checksum every file below the given paths, keyed by absolute path."""
    state: Dict[str, Dict[str, Any]] = {}
    for target in paths:
        target = target.expanduser().resolve()
        if target.is_file():
            candidates = [target]
        elif target.is_dir():
            candidates = [p for p in sorted(target.rglob("*")) if p.is_file()]
        else:
            continue
        for path in candidates:
            if path.is_symlink():
                continue
            try:
                state[str(path)] = {
                    "sha256": ndos_scan._sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            except OSError:
                # Unreadable now; recorded as absent rather than guessed at.
                continue
    return state


def _diff(
    before: Dict[str, Dict[str, Any]], after: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Files the run created or changed, as generated artifacts."""
    generated = []
    for path, entry in sorted(after.items()):
        previous = before.get(path)
        if previous is None:
            change = "created"
        elif previous["sha256"] != entry["sha256"]:
            change = "modified"
        else:
            continue
        generated.append(
            {
                "path": path,
                "sha256": entry["sha256"],
                "size_bytes": entry["size_bytes"],
                "change": change,
            }
        )
    return generated


# --------------------------------------------------------------------------
# environment
# --------------------------------------------------------------------------

def _git_state(directory: Path) -> Optional[Dict[str, Any]]:
    """The code version, when the working directory is a git repository."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=directory, capture_output=True, text=True, timeout=10,
        )
        if commit.returncode != 0:
            return None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=directory, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    state: Dict[str, Any] = {"commit": commit.stdout.strip()}
    if dirty is not None:
        # A dirty tree means the commit does not describe what actually ran.
        state["uncommitted_changes"] = dirty
    return state


def _environment(record_env: Sequence[str], anonymous: bool = False) -> Dict[str, Any]:
    """Describe the machine, without sweeping up credentials.

    Environment variables are captured only when explicitly named. Recording
    the whole environment would routinely bury API keys and tokens inside
    provenance files that are meant to be shared.
    """
    environment: Dict[str, Any] = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    # Hostname and username identify a person and a machine. Useful inside a
    # lab, unwanted in provenance attached to a public release.
    if not anonymous:
        environment["hostname"] = socket.gethostname()
        try:
            environment["user"] = getpass.getuser()
        except (KeyError, OSError):
            pass

    if record_env:
        environment["variables"] = {
            name: os.environ[name] for name in record_env if name in os.environ
        }
    return environment


# --------------------------------------------------------------------------
# running
# --------------------------------------------------------------------------

def _truncate(text: str) -> Dict[str, Any]:
    encoded = text.encode("utf-8", "replace")
    if len(encoded) <= CAPTURE_LIMIT:
        return {"text": text, "truncated": False}
    kept = encoded[-CAPTURE_LIMIT:].decode("utf-8", "replace")
    return {"text": kept, "truncated": True, "total_bytes": len(encoded)}


def record_run(
    command: Sequence[str],
    inputs: Sequence[Path] = (),
    outputs: Sequence[Path] = (),
    name: Optional[str] = None,
    record_env: Sequence[str] = (),
    cwd: Optional[Path] = None,
    echo: bool = True,
    anonymous: bool = False,
) -> Dict[str, Any]:
    """Run a command and return a provenance record describing it."""
    if not command:
        raise ValueError("no command given to run")

    working = (cwd or Path.cwd()).expanduser().resolve()
    input_paths = [Path(p) for p in inputs]
    output_paths = [Path(p) for p in outputs]

    used = _snapshot(input_paths)
    before = _snapshot(output_paths)

    started = datetime.now(tz=timezone.utc)
    try:
        completed = subprocess.run(
            list(command), cwd=str(working), capture_output=True, text=True
        )
        exit_code: Optional[int] = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
        failure = None
    except (OSError, subprocess.SubprocessError) as error:
        exit_code, stdout, stderr = None, "", ""
        failure = str(error)
    finished = datetime.now(tz=timezone.utc)

    if echo:
        if stdout:
            sys.stdout.write(stdout)
        if stderr:
            sys.stderr.write(stderr)

    after = _snapshot(output_paths)

    record: Dict[str, Any] = {
        "provenance_version": PROVENANCE_VERSION,
        "run_id": f"run-{uuid.uuid4().hex[:12]}",
        "name": name or Path(command[0]).name,
        "generator": {"name": "ndos-prov", "version": GENERATOR_VERSION},
        "command": list(command),
        "working_directory": str(working),
        "started_at": ndos_scan._utc_iso(started.timestamp()),
        "ended_at": ndos_scan._utc_iso(finished.timestamp()),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "exit_code": exit_code,
        "status": "succeeded" if exit_code == 0 else "failed",
        "environment": _environment(record_env, anonymous=anonymous),
        "used": [
            {"path": path, "sha256": entry["sha256"], "size_bytes": entry["size_bytes"]}
            for path, entry in sorted(used.items())
        ],
        "generated": _diff(before, after),
        "stdout": _truncate(stdout),
        "stderr": _truncate(stderr),
    }

    code = _git_state(working)
    if code:
        record["code"] = code
    if failure:
        record["error"] = failure

    return record


def write_record(record: Dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{record['run_id']}.json"
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return path


def load_records(directory: Path) -> List[Dict[str, Any]]:
    """Every run record in a provenance directory, oldest first."""
    if not directory.is_dir():
        return []
    records = []
    for path in sorted(directory.glob("run-*.json")):
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    records.sort(key=lambda record: record.get("started_at", ""))
    return records


# --------------------------------------------------------------------------
# tracing
# --------------------------------------------------------------------------

def _producers(records: Sequence[Dict[str, Any]]):
    """Index from a generated artifact to the runs that produced it.

    Keyed by content hash as well as path, so a file that has been moved or
    copied is still recognised as the same artifact.
    """
    by_hash: Dict[str, List[Dict[str, Any]]] = {}
    by_path: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        for artifact in record.get("generated", []):
            by_hash.setdefault(artifact["sha256"], []).append(record)
            by_path.setdefault(artifact["path"], []).append(record)
    return by_hash, by_path


def trace(
    target: Path, directory: Path, max_depth: int = 12
) -> Dict[str, Any]:
    """Walk backwards from an artifact to the runs and inputs behind it."""
    records = load_records(directory)
    by_hash, by_path = _producers(records)

    resolved = target.expanduser().resolve()
    digest = None
    if resolved.is_file():
        try:
            digest = ndos_scan._sha256(resolved)
        except OSError:
            digest = None

    def find(path: str, sha: Optional[str]) -> List[Dict[str, Any]]:
        """Which runs produced this artifact.

        Path is checked before content, because an idempotent step produces a
        file byte-identical to its own input — uppercasing already-uppercase
        text, re-encoding, normalising. Matching on content first would
        attribute such a result to the earlier run. The hash lookup remains as
        a fallback so a file that was moved or copied is still recognised.
        """
        if path in by_path:
            return by_path[path]
        if sha and sha in by_hash:
            return by_hash[sha]
        return []

    # A run that produced twelve files would otherwise be expanded twelve
    # times, once under each. Expanding it once keeps a real pipeline's trace
    # readable; later mentions point back to the first.
    expanded: Dict[str, bool] = {}

    def walk(path: str, sha: Optional[str], depth: int, chain) -> Dict[str, Any]:
        node: Dict[str, Any] = {"path": path, "sha256": sha}
        # Keyed on path, not content: an idempotent step yields a file whose
        # hash equals its input's, which is not a cycle.
        if path in chain:
            node["note"] = "cycle; not expanded again"
            return node

        producing = find(path, sha)
        if not producing:
            # Nothing generated it, so as far as NDOS knows it is raw input.
            node["origin"] = "not produced by any recorded run"
            return node
        if depth >= max_depth:
            node["note"] = f"stopped at depth {max_depth}"
            return node

        node["produced_by"] = []
        for record in producing:
            entry: Dict[str, Any] = {
                "run_id": record["run_id"],
                "name": record.get("name", ""),
                "command": record.get("command", []),
                "started_at": record.get("started_at", ""),
                "status": record.get("status", ""),
                "code": record.get("code"),
            }
            if expanded.get(record["run_id"]):
                entry["repeat"] = True
                entry["used"] = []
            else:
                expanded[record["run_id"]] = True
                entry["used"] = [
                    walk(item["path"], item.get("sha256"), depth + 1, chain | {path})
                    for item in record.get("used", [])
                ]
            node["produced_by"].append(entry)
        return node

    return {
        "target": str(resolved),
        "sha256": digest,
        "found_on_disk": resolved.exists(),
        "record_count": len(records),
        "tree": walk(str(resolved), digest, 0, frozenset()),
    }


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

def render_trace(result: Dict[str, Any]) -> str:
    out: List[str] = []
    add = out.append

    add("=" * 72)
    add("NDOS PROVENANCE TRACE")
    add("=" * 72)
    add(f"Target  : {result['target']}")
    if not result["found_on_disk"]:
        add("          (not on disk; matched by path only)")
    if result["sha256"]:
        add(f"sha256  : {result['sha256'][:16]}...")
    add(f"Records : {result['record_count']} runs searched")
    add("")

    def emit_artifact(node: Dict[str, Any], prefix: str, root: bool = False) -> None:
        if node.get("note"):
            add(f"{prefix}({node['note']})")
            return
        if "origin" in node:
            add(f"{prefix}[raw] {node['origin']}")
            return

        runs = node.get("produced_by", [])
        for index, run in enumerate(runs):
            last = index == len(runs) - 1
            connector = "└── " if last else "├── "
            child = prefix + ("    " if last else "│   ")
            marker = "✗" if run["status"] == "failed" else "→"
            add(
                f"{prefix}{connector}{marker} {run['name']}  "
                f"[{run['run_id']}]  {run['started_at']}"
            )
            add(f"{child}  $ {' '.join(run['command'])}")
            if run.get("code"):
                dirty = (
                    "  (uncommitted changes)"
                    if run["code"].get("uncommitted_changes") else ""
                )
                add(f"{child}  commit {run['code']['commit'][:10]}{dirty}")
            if run["status"] == "failed":
                add(f"{child}  this run FAILED; its outputs may be incomplete")
            if run.get("repeat"):
                add(f"{child}  (inputs shown above)")
                continue

            used = run.get("used", [])
            for position, item in enumerate(used):
                item_last = position == len(used) - 1
                item_connector = "└── " if item_last else "├── "
                name = Path(item["path"]).name or item["path"]
                add(f"{child}{item_connector}{name}")
                emit_artifact(item, child + ("    " if item_last else "│   "))

    tree = result["tree"]
    add(Path(tree["path"]).name or tree["path"])
    emit_artifact(tree, "", root=True)

    add("")
    add("-" * 72)
    add("[raw] marks an artifact no recorded run produced.")
    add("-" * 72)
    return "\n".join(out) + "\n"


def render_list(records: Sequence[Dict[str, Any]]) -> str:
    out: List[str] = []
    add = out.append
    add("=" * 72)
    add(f"NDOS RUNS ({len(records)})")
    add("=" * 72)
    if not records:
        add("No runs recorded yet.")
        add("")
        add("Wrap a command to record one:")
        add(
            f"  {ndos_scan.invocation('ndos_prov')} run --input raw/ "
            "--output results/ -- python analyse.py"
        )
        return "\n".join(out) + "\n"

    for record in records:
        mark = "ok  " if record.get("status") == "succeeded" else "FAIL"
        add(
            f"  {mark}  {record['started_at']}  {record['run_id']}  "
            f"{record.get('name', '')}"
        )
        add(f"          $ {' '.join(record.get('command', []))}")
        add(
            f"          used {len(record.get('used', []))}, "
            f"generated {len(record.get('generated', []))}, "
            f"{record.get('duration_seconds', 0)}s"
        )
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# cli
# --------------------------------------------------------------------------

def command_run(args: argparse.Namespace) -> int:
    if not args.command:
        print(
            "Nothing to run. Put the command after -- , for example:\n"
            f"  {ndos_scan.invocation('ndos_prov')} run --output results/ "
            "-- python analyse.py",
            file=sys.stderr,
        )
        return 2

    record = record_run(
        args.command,
        inputs=args.input,
        outputs=args.output,
        name=args.name,
        record_env=args.record_env,
        echo=not args.quiet,
        anonymous=args.anonymous,
    )
    path = write_record(record, args.dir)

    if not args.quiet:
        print(
            f"\nRecorded {record['run_id']} ({record['status']}): "
            f"used {len(record['used'])}, generated {len(record['generated'])} "
            f"-> {path}",
            file=sys.stderr,
        )
        if not args.output:
            print(
                "No --output directory was watched, so nothing was recorded as "
                "generated. Pass --output to capture what the run produced.",
                file=sys.stderr,
            )
    # Pass the wrapped command's exit code through, so this composes in scripts.
    return record["exit_code"] if isinstance(record["exit_code"], int) else 1


def command_trace(args: argparse.Namespace) -> int:
    result = trace(args.artifact, args.dir, max_depth=args.max_depth)
    rendered = (
        json.dumps(result, indent=2) + "\n" if args.format == "json"
        else render_trace(result)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def command_list(args: argparse.Namespace) -> int:
    records = load_records(args.dir)
    if args.format == "json":
        print(json.dumps(records, indent=2))
    else:
        print(render_list(records), end="")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Record and trace what produced a result.",
        epilog=(
            "Environment variables are never captured unless named with "
            "--record-env, so provenance files do not quietly collect secrets."
        ),
    )
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    run = subparsers.add_parser(
        "run", help="Run a command and record what it used and produced"
    )
    run.add_argument(
        "-d", "--dir", type=Path, default=DEFAULT_DIR,
        help=f"Where to write run records (default: {DEFAULT_DIR}/)",
    )
    run.add_argument(
        "-i", "--input", type=Path, action="append", default=[],
        help="File or directory the run reads; checksummed before it starts",
    )
    run.add_argument(
        "-o", "--output", type=Path, action="append", default=[],
        help="Directory to watch for what the run produces; repeatable",
    )
    run.add_argument("--name", help="Human-readable name for this run")
    run.add_argument(
        "--record-env", action="append", default=[], metavar="VAR",
        help="Environment variable to record; repeatable, none by default",
    )
    run.add_argument(
        "--anonymous", action="store_true",
        help="Omit hostname and username, for provenance you intend to share",
    )
    run.add_argument("-q", "--quiet", action="store_true")
    run.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="The command, after --",
    )
    run.set_defaults(func=command_run)

    trace_parser = subparsers.add_parser(
        "trace", help="Walk backwards from a result to the raw data behind it"
    )
    trace_parser.add_argument("artifact", type=Path, help="File to trace")
    trace_parser.add_argument("-d", "--dir", type=Path, default=DEFAULT_DIR)
    trace_parser.add_argument("-f", "--format", choices=("text", "json"), default="text")
    trace_parser.add_argument("-o", "--output", type=Path)
    trace_parser.add_argument("--max-depth", type=int, default=12)
    trace_parser.set_defaults(func=command_trace)

    listing = subparsers.add_parser("list", help="List recorded runs")
    listing.add_argument("-d", "--dir", type=Path, default=DEFAULT_DIR)
    listing.add_argument("-f", "--format", choices=("text", "json"), default="text")
    listing.set_defaults(func=command_list)

    args = parser.parse_args()
    if getattr(args, "command", None) and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    try:
        return args.func(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
