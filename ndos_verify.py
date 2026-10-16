#!/usr/bin/env python3
"""Check that a transferred dataset arrived intact.

NDOS does not move data between machines. rsync, rclone, DataLad, datashuttle
and your institution's tooling already do that, and better than a
reimplementation would. What none of them tells you is whether what arrived is
still usable.

    ndos scan /source -o before.json          # checksums are on by default
    # ... move it with whatever you already use ...
    ndos verify before.json /destination

There is no separate command to write the manifest: `ndos scan --output` is
the manifest, and it checksums by default.

Three answers, not two
----------------------
A comparison that found no mismatch has not necessarily verified anything. If
the source manifest carried no checksum for a file, or either side skipped a
path, then "no mismatch detected" is the honest result and "verified" is not.

    VERIFIED      every expected file was matched by checksum       exit 0
    FAILED        at least one file is missing or definitely changed exit 1
    INCONCLUSIVE  no mismatch found, and something could not be
                  checked, so the transfer is not proven            exit 3

That distinction is the same one `ndos query` makes between excluded and
cannot-be-ruled-out, applied to this tool's own output. A verifier that
reported success when it had nothing to verify against would be the exact
failure this project argues against.

Exit 2 is reserved for a usage or I/O error, as elsewhere in NDOS.

What this does not cover
------------------------
Manifests inventory files, so empty directories are not compared, and symlinks
are recorded but not followed -- a symlink on either side makes the result
INCONCLUSIVE rather than silently passing. Paths excluded by pattern are out
of scope and do not count against the result. Permissions are not compared: a transfer tool
may legitimately change them. Modification times are reported where they
differ and never cause a failure, because preserving bytes while changing
mtimes is normal and correct behaviour for a copy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set

import ndos_organize
import ndos_scan

VERIFY_VERSION = "0.1"

VERIFIED = "VERIFIED"
FAILED = "FAILED"
INCONCLUSIVE = "INCONCLUSIVE"

#: Exit codes. 2 stays an error, which is what it means in every other module.
EXIT = {VERIFIED: 0, FAILED: 1, INCONCLUSIVE: 3}

#: Records a lab or NDOS keeps beside the data. Losing one of these loses what
#: somebody decided, which re-copying the data does not restore.
SIDECAR_NAMES = frozenset({
    "tags.json", "derived_metadata.json", "project.toml", "metadata.yaml",
    # The three linked tables. Everything in them was typed by a person who
    # knew something the filesystem does not, and re-copying the data does not
    # bring any of it back.
    "animals.csv", "procedures.csv", "sessions.csv",
})


def _is_sidecar(name: str) -> bool:
    return name in SIDECAR_NAMES or name.endswith("_metadata.yaml")


SUPPORTED_MANIFEST_VERSIONS = frozenset({"0.1", "0.2"})

#: A sha256 is 64 hex characters. Anything else in that field is not a digest,
#: and comparing against it would produce an authoritative-looking answer from
#: a record that cannot support one.
_HEX64 = __import__("re").compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The manifest cannot be trusted to verify anything against."""


def _check_manifest(document: Dict[str, Any]) -> None:
    """Refuse a manifest before comparing against it.

    A verifier is an integrity tool, so a malformed integrity record has to be
    an error rather than an input. Two entries for one path silently kept
    whichever came last, and an entry with no path raised a bare KeyError from
    the middle of the comparison -- both of which could end in a confident
    verdict drawn from a record nobody checked.
    """
    version = document.get("manifest_version")
    if version is not None and str(version) not in SUPPORTED_MANIFEST_VERSIONS:
        raise ManifestError(
            f"manifest_version {version!r} is not one this version reads "
            f"({', '.join(sorted(SUPPORTED_MANIFEST_VERSIONS))})"
        )

    files = document.get("files")
    if not isinstance(files, list):
        raise ManifestError("the manifest's `files` is not a list")

    seen: Set[str] = set()
    for position, entry in enumerate(files):
        where = f"files[{position}]"
        if not isinstance(entry, dict):
            raise ManifestError(f"{where} is not an object")
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ManifestError(f"{where} has no usable path")
        if path in seen:
            raise ManifestError(
                f"{path!r} appears twice. One of the two would be silently "
                "ignored, and the result would not say which."
            )
        seen.add(path)

        size = entry.get("size_bytes")
        if size is not None and (not isinstance(size, int) or size < 0):
            raise ManifestError(f"{where} ({path}) has a size of {size!r}")

        digest = entry.get("sha256")
        if digest is not None and not (
            isinstance(digest, str) and _HEX64.match(digest)
        ):
            raise ManifestError(
                f"{where} ({path}) has {digest!r} where a sha256 belongs"
            )


def _by_path(document: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {entry["path"]: entry for entry in document.get("files", [])}


#: Why a scan skipped a path, and whether that leaves a transfer unproven.
#:
#: `excluded` does not: the path matched an exclude pattern, so it was never
#: meant to travel, and counting it would make every clean transfer of a
#: directory containing a .DS_Store come back INCONCLUSIVE -- which would make
#: the verdict useless and train people to ignore it.
#:
#: The rest do. A file that could not be read at the source is a file whose
#: contents were never known, and a symlink is recorded without being
#: followed, so its target was never in the manifest to compare.
SKIPS_THAT_LEAVE_DOUBT = frozenset({
    "unreadable-file", "unreadable-directory", "symlink",
})


def _skipped(document: Dict[str, Any]) -> Dict[str, str]:
    """Paths a scan could not account for, excluding ones it was told to ignore."""
    return {
        entry.get("path", ""): entry.get("reason", "skipped")
        for entry in document.get("skipped", [])
        if entry.get("path") and entry.get("reason") in SKIPS_THAT_LEAVE_DOUBT
    }


def _tool_directories(paths: Sequence[str]) -> Dict[str, str]:
    """Which directories were written by a tool, and which tool.

    Reuses the markers `ndos_organize` matches on, so a directory treated as
    one payload when a layout is built is treated as one payload here.

    This recognises the *shape* a tool writes. It does not judge whether the
    original output was itself complete — only whether it is complete relative
    to the manifest.
    """
    members: Dict[str, Set[str]] = {}
    for path in paths:
        members.setdefault(Path(path).parent.as_posix(), set()).add(Path(path).name)

    found = {}
    for directory, names in members.items():
        for label, markers in ndos_organize.TOOL_OUTPUTS:
            if all(marker in names for marker in markers):
                found[directory] = label
                break
    return found


def verify(
    before: Dict[str, Any],
    destination: Path,
    strict_extra: bool = False,
) -> Dict[str, Any]:
    """Compare a source manifest against what is now at the destination."""
    if not destination.is_dir():
        raise ValueError(f"not a directory: {destination}")
    _check_manifest(before)

    after = ndos_scan.scan(
        destination, include_checksums=True, progress=False, follow_symlinks=False
    )

    source_files, arrived = _by_path(before), _by_path(after)
    source_paths, arrived_paths = set(source_files), set(arrived)
    source_skipped, destination_skipped = _skipped(before), _skipped(after)

    missing = sorted(source_paths - arrived_paths)
    unexpected = sorted(arrived_paths - source_paths)

    changed: List[Dict[str, Any]] = []
    unverifiable: List[Dict[str, Any]] = []
    verified_count = 0
    retimed: List[str] = []

    for path in sorted(source_paths & arrived_paths):
        source, target = source_files[path], arrived[path]
        # Per entry, not from the manifest's global flag: `checksums: true`
        # does not guarantee every file object carries a hash.
        expected, actual = source.get("sha256"), target.get("sha256")
        same_size = source.get("size_bytes") == target.get("size_bytes")

        if expected and actual:
            if expected == actual:
                verified_count += 1
                if source.get("modified") != target.get("modified"):
                    retimed.append(path)
            else:
                changed.append({
                    "path": path, "reason": "checksum differs",
                    "expected": expected, "found": actual,
                    "size_before": source.get("size_bytes"),
                    "size_after": target.get("size_bytes"),
                })
        elif not same_size:
            # No hash to compare, but a different size is a definite change.
            changed.append({
                "path": path, "reason": "size differs and no checksum to compare",
                "size_before": source.get("size_bytes"),
                "size_after": target.get("size_bytes"),
            })
        else:
            unverifiable.append({
                "path": path,
                "reason": (
                    "no checksum in the source manifest"
                    if not expected else "no checksum could be read at the destination"
                ),
            })

    for path, reason in sorted(source_skipped.items()):
        unverifiable.append({"path": path, "reason": f"skipped at the source: {reason}"})
    for path, reason in sorted(destination_skipped.items()):
        unverifiable.append(
            {"path": path, "reason": f"skipped at the destination: {reason}"}
        )

    # Group missing files by the tool directory they belong to. A Kilosort
    # sorting short one file is unopenable, and an ungrouped list of absent
    # paths does not say so.
    incomplete: List[Dict[str, Any]] = []
    absent = set(missing)
    altered = {entry["path"] for entry in changed}
    unproven = {entry["path"] for entry in unverifiable}
    for directory, label in sorted(_tool_directories(sorted(source_paths)).items()):
        expected_here = {
            p for p in source_paths if Path(p).parent.as_posix() == directory
        }
        lost = sorted(expected_here & absent)
        if lost and len(lost) < len(expected_here):
            incomplete.append({
                "directory": directory,
                "tool": label,
                "missing": lost,
                "source_file_count": len(expected_here),
                # Only files that matched by checksum. Counting a corrupted or
                # unchecked file as verified would say "3 of 4 verified" about
                # a directory where two files are wrong.
                "verified": len(
                    expected_here - absent - altered - unproven
                ),
                "changed": sorted(expected_here & altered),
            })

    records_left = [p for p in missing if _is_sidecar(Path(p).name)]

    # Deliberate exclusions do not affect the verdict -- that is decided above
    # -- but `--exclude '*.bin'` should not let a transfer read VERIFIED
    # without saying that the recordings were never in scope.
    excluded = sorted(
        entry.get("path", "")
        for entry in before.get("skipped", [])
        if entry.get("reason") == "excluded" and entry.get("path")
    )

    # A manifest of nothing cannot prove a transfer. Reporting VERIFIED here
    # would be the exact contradiction this command is built around, and it is
    # reachable by scanning an empty mount or excluding everything.
    nothing_to_compare = not source_paths
    if nothing_to_compare:
        unverifiable.append({
            "path": before.get("source_root", "(the manifest)"),
            "reason": "the manifest records no files, so there is nothing to verify",
        })

    definite = len(missing) + len(changed) + (len(unexpected) if strict_extra else 0)
    if definite:
        result = FAILED
    elif unverifiable:
        result = INCONCLUSIVE
    else:
        result = VERIFIED

    return {
        "verify_version": VERIFY_VERSION,
        "generator": ndos_scan.invocation("ndos_verify"),
        "checked_at": ndos_scan._utc_iso(datetime.now(tz=timezone.utc).timestamp()),
        "source_root": before.get("source_root", ""),
        "destination": str(destination),
        "strict_extra": strict_extra,
        "result": result,
        "counts": {
            "source_files": len(source_paths),
            "verified": verified_count,
            "missing": len(missing),
            "changed": len(changed),
            "unverifiable": len(unverifiable),
            "unexpected": len(unexpected),
            "incomplete_tool_directories": len(incomplete),
            "records_left_behind": len(records_left),
            "modification_times_changed": len(retimed),
            "excluded_from_scope": len(excluded),
        },
        "missing": missing,
        "changed": changed,
        "unverifiable": unverifiable,
        "unexpected": unexpected,
        "incomplete": incomplete,
        "records_left_behind": records_left,
        "excluded_from_scope": excluded,
    }


def render(result: Dict[str, Any], verbose: bool = False) -> str:
    counts = result["counts"]
    width = max(len(k) for k in
                ("Source files", "Verified", "Missing", "Changed",
                 "Unverifiable", "Unexpected"))
    lines = [
        "=" * 72,
        "TRANSFER VERIFICATION",
        "=" * 72,
        f"From : {result['source_root']}",
        f"To   : {result['destination']}",
        "",
        f"{'Source files':<{width}} : {counts['source_files']:>8,}",
        f"{'Verified':<{width}} : {counts['verified']:>8,}",
        f"{'Missing':<{width}} : {counts['missing']:>8,}",
        f"{'Changed':<{width}} : {counts['changed']:>8,}",
        f"{'Unverifiable':<{width}} : {counts['unverifiable']:>8,}",
        f"{'Unexpected':<{width}} : {counts['unexpected']:>8,}",
        "",
        f"RESULT: {result['result']}",
    ]

    if result["result"] == VERIFIED:
        lines.append("")
        if counts.get("excluded_from_scope"):
            # Otherwise `--exclude '*.bin'` reads as a clean bill of health on
            # a comparison the recordings were never part of.
            lines.append(
                "  Every expected file was matched by checksum — within the "
                "scope this manifest declares."
            )
            lines.append(
                f"  {counts['excluded_from_scope']} path(s) were excluded from "
                "that scope and were never compared."
            )
        else:
            lines.append("  Every expected file was matched by checksum.")
        if counts["unexpected"]:
            lines.append(
                f"  {counts['unexpected']} file(s) at the destination were not in "
                "the manifest. Normal if it already held other data; "
                "--strict-extra makes it a failure."
            )
        if counts["modification_times_changed"]:
            lines.append(
                f"  {counts['modification_times_changed']} file(s) have a different "
                "modification time. The bytes are identical, which is what matters."
            )
        return "\n".join(lines + ["", "=" * 72])

    if result["result"] == INCONCLUSIVE:
        lines += [
            "",
            "  No mismatch was found, and that is not the same as verified:",
            f"  {counts['unverifiable']} file(s) could not be checked.",
        ]

    def section(title: str, note: str, items: Sequence[Any], show) -> None:
        if not items:
            return
        lines.append("")
        lines.append("-" * 72)
        lines.append(f"{title} ({len(items)})")
        lines.append("-" * 72)
        lines.append(f"  {note}")
        limit = len(items) if verbose else 10
        for item in items[:limit]:
            lines.append("  " + show(item))
        if len(items) > limit:
            lines.append(f"  … and {len(items) - limit} more (-v to list)")

    section(
        "CHANGED", "Arrived with different contents. This is data loss.",
        result["changed"], lambda c: f"{c['path']}  ({c['reason']})",
    )
    section(
        "INCOMPLETE TOOL-NATIVE DIRECTORY",
        "Present, and short of what the manifest recorded. The tool that "
        "wrote it may not be able to read it back.",
        result["incomplete"],
        lambda i: (
            f"{i['tool']}: {i['directory']}/\n"
            f"      {i['verified']} of {i['source_file_count']} source files verified\n"
            "      missing: " + ", ".join(Path(m).name for m in i["missing"][:5])
            + ("\n      changed: " + ", ".join(Path(c).name for c in i["changed"][:5])
               if i.get("changed") else "")
        ),
    )
    section("MISSING", "In the manifest, absent from the destination.",
            result["missing"], lambda p: p)
    section(
        "RECORDS LEFT BEHIND",
        "The data arrived; what somebody decided about it did not.",
        result["records_left_behind"], lambda p: p,
    )
    section(
        "UNVERIFIABLE", "No mismatch, and no proof either.",
        result["unverifiable"], lambda u: f"{u['path']}  ({u['reason']})",
    )
    if verbose:
        section("NOT IN THE MANIFEST", "Normal if the destination already held data.",
                result["unexpected"], lambda p: p)

    lines += ["", "=" * 72]
    if result["result"] == FAILED:
        lines.append(
            "Re-copy the missing and changed files from the source."
        )
    else:
        # Re-copying does not help when the manifest had nothing to compare
        # against, which is the usual cause of this verdict.
        lines.append(
            "Re-copying will not resolve this. Either the source manifest "
            "carried no\nchecksums -- rebuild it with `ndos scan <source> -o "
            "<file>` -- or paths could\nnot be read at one end and need "
            "looking at."
        )
    lines.append("NDOS did not modify either location.")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ndos verify",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Write the manifest with `ndos scan /source -o before.json`, which\n"
            "checksums by default. NDOS does not move data: use rsync, rclone,\n"
            "DataLad or datashuttle for that, and this to check the result.\n\n"
            "Exit: 0 verified, 1 failed, 3 inconclusive, 2 error."
        ),
    )
    parser.add_argument("manifest", type=Path, help="Manifest written before the transfer")
    parser.add_argument("destination", type=Path)
    parser.add_argument(
        "--strict-extra", action="store_true",
        help="Treat files at the destination that are not in the manifest as a "
             "failure, rather than reporting them",
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="List every affected file")
    parser.add_argument("-o", "--output", type=Path, metavar="JSON",
                        help="Also write the report here")

    args = parser.parse_args(argv)

    try:
        if not args.manifest.is_file():
            raise ValueError(f"no manifest at {args.manifest}")
        before = json.loads(args.manifest.read_text(encoding="utf-8"))
        if "files" not in before:
            raise ValueError(f"{args.manifest} is not an NDOS manifest")

        result = verify(before, args.destination, strict_extra=args.strict_extra)

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(render(result, verbose=args.verbose))
        return EXIT[result["result"]]
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"ndos verify: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
