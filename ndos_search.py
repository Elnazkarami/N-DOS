#!/usr/bin/env python3
"""Find things in a drive by what they say, not by where they sit.

`ndos query` answers questions about fields: species, target region, days since
an injection. It needs you to know which field holds the answer.

On an inherited drive you often do not. What you know is a word -- "CA1",
"GCaMP", the name of a construct -- and the thing that knows where it applies is
a surgery log in a spreadsheet nobody has opened in three years. NDOS already
counted that spreadsheet. It never read it.

This reads it, and the notes, and the protocol files, and the metadata tables,
and makes them searchable together, so one word can lead to the recordings it
describes.

    ndos search index /path/to/drive        # build the index, read-only
    ndos search find "CA1 AND injection"    # search it

Search ranks; it does not decide. A hit is a reason to look, not evidence that a
session qualifies -- that is what `ndos query` is for, and it is the one that
reports what cannot be ruled out. Every result here carries the file it came
from and the words that matched, so a wrong hit is visible as a wrong hit.

Standard library only, like the rest of NDOS: full-text search and its ranking
come from SQLite's FTS5, which ships with Python.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import ndos_organize
import ndos_report
import ndos_scan
import ndos_table

INDEX_VERSION = "0.1"
GENERATOR_VERSION = "0.1.0"

#: Default index filename. Written where you ask, never into the source.
DEFAULT_INDEX = "ndos-search.db"

#: Text files worth reading whole. Everything here is plain text in a known
#: encoding, so reading it costs one open and one decode.
TEXT_EXTENSIONS = frozenset({
    ".txt", ".md", ".rst", ".log", ".json", ".yaml", ".yml", ".xml",
    ".toml", ".ini", ".cfg", ".csv", ".tsv", ".tab", ".m", ".py", ".r",
})

#: Office formats that are a ZIP of XML, and so readable without a dependency.
#: .doc, .pdf, .odt and .rtf are deliberately absent: reading those needs a
#: third-party parser, and NDOS does not take dependencies for a convenience.
ZIP_XML_EXTENSIONS = frozenset({".docx", ".xlsx"})

#: Per-file limit on indexed text. A multi-gigabyte acquisition log would
#: otherwise be read into memory in full for no benefit: the first megabytes
#: say what kind of file it is, and the rest repeats itself.
MAX_TEXT_BYTES = 2 * 1024 * 1024

#: Total uncompressed bytes read from one archive member, so a small .docx that
#: claims to hold a terabyte cannot exhaust memory. The same defence
#: ndos_archive applies when it inspects a ZIP.
MAX_MEMBER_BYTES = 8 * 1024 * 1024

#: How a hit is known, reusing the vocabulary the rest of NDOS uses.
#: `observed` -- the text is in a file on disk, read directly.
#: `declared` -- a person entered it in a metadata table.
OBSERVED = "observed"
DECLARED = "declared"

#: Metadata columns worth indexing. `species` and `sex` are left out on
#: purpose: almost every row in a project shares them, so "mouse" would match
#: everything and rank nothing, and `ndos query -w species=mouse` answers that
#: precisely. The narrower vocabularies stay, because "find the injections" is
#: a reasonable thing to type.
FREE_TEXT_COLUMNS = frozenset({
    "notes", "task", "target_region", "construct_or_drug", "dose",
    "strain", "genotype", "source", "procedure_type", "session_type",
    "qc_status", "subject_id", "procedure_id",
})

#: Subject identifiers are short and look like ordinary words in running text,
#: so a bare scan for them is too noisy to be useful. This requires the id to
#: stand alone rather than sit inside a longer word.
def _subject_mentions(text: str, subjects: Iterable[str]) -> List[str]:
    """Which known animals a piece of text names.

    This is what turns a surgery log into a route to the recordings: the log
    says "CA1" and "M123", `animals.csv` says M123 is a mouse, and the sessions
    table says which folders are M123's.
    """
    found = []
    lowered = text.lower()
    for subject in subjects:
        if not subject or len(subject) < 2:
            continue
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(subject.lower())}(?![A-Za-z0-9])", lowered):
            found.append(subject)
    return sorted(set(found))


def _session_label(segments: Sequence[str]) -> str:
    """The SessionID for a path, in the form the rest of NDOS writes it.

    `_find_session` reports what it found -- an explicit label, or a date, or a
    date and time -- and `_session_id` turns a date into the YYYYMMDD form the
    standard uses. Doing that here rather than reimplementing it is what keeps
    one answer to "which session is this".
    """
    found, _ = ndos_organize._find_session(segments)
    if not found:
        return ""
    if found.get("label"):
        return str(found["label"])
    date = found.get("date")
    if not date:
        return ""
    return ndos_organize._session_id(date, found.get("suffix", "") or "")


def _read_text_file(path: Path) -> Optional[str]:
    """A text file's contents, or None if it cannot be read as text."""
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_TEXT_BYTES)
    except OSError:
        return None
    # A NUL byte in the first block is the usual sign of a binary file that
    # happens to carry a text extension.
    if b"\0" in raw[:4096]:
        return None
    return raw.decode("utf-8", errors="replace")


def _read_zip_xml(path: Path) -> Optional[str]:
    """Text from a .docx or .xlsx, which are ZIPs of XML.

    Only the parts that hold words are read: the document body for Word, and
    the shared-strings table plus inline cell text for Excel. Formatting,
    styles and relationships are skipped -- they are large and say nothing a
    person searched for.
    """
    wanted = {
        ".docx": ("word/document.xml",),
        ".xlsx": ("xl/sharedStrings.xml",),
    }.get(path.suffix.lower())
    if not wanted:
        return None

    pieces: List[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            members = [name for name in wanted if name in names]
            # An .xlsx with no shared strings keeps its text inline in the
            # sheets instead, so fall back to those.
            if path.suffix.lower() == ".xlsx" and not members:
                members = sorted(
                    name for name in names
                    if name.startswith("xl/worksheets/") and name.endswith(".xml")
                )[:20]
            for name in members:
                info = archive.getinfo(name)
                if info.file_size > MAX_MEMBER_BYTES:
                    continue
                with archive.open(name) as stream:
                    data = stream.read(MAX_MEMBER_BYTES)
                try:
                    root = ET.fromstring(data)
                except ET.ParseError:
                    continue
                # itertext() walks every element's text, which is what the
                # words are; the tag names are namespaced and uninteresting.
                pieces.append(" ".join(t.strip() for t in root.itertext() if t.strip()))
    except (zipfile.BadZipFile, OSError, KeyError):
        return None

    text = "\n".join(piece for piece in pieces if piece)
    return text or None


def extract_text(path: Path) -> Optional[str]:
    """Readable text from one file, or None if there is none to be had."""
    extension = path.suffix.lower()
    if extension in ZIP_XML_EXTENSIONS:
        return _read_zip_xml(path)
    if extension in TEXT_EXTENSIONS:
        return _read_text_file(path)
    return None


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    return db


def _create(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE sources (
            id       INTEGER PRIMARY KEY,
            kind     TEXT NOT NULL,   -- document | metadata
            evidence TEXT NOT NULL,   -- observed | declared
            path     TEXT NOT NULL,   -- where it came from
            locator  TEXT,            -- which row or field inside it
            subject  TEXT,            -- the animal, where it is known
            session  TEXT,            -- the session, where it is known
            mentions TEXT             -- animals this text names, comma separated
        );
        -- Contentless would save space but lose snippet(), and a hit without
        -- the words that matched is not a citation.
        CREATE VIRTUAL TABLE search USING fts5(body);
        """
    )


def _supports_fts5() -> bool:
    probe = sqlite3.connect(":memory:")
    try:
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        probe.close()


def _add(
    db: sqlite3.Connection,
    *,
    kind: str,
    evidence: str,
    path: str,
    body: str,
    locator: str = "",
    subject: str = "",
    session: str = "",
    mentions: Sequence[str] = (),
) -> None:
    cursor = db.execute(
        "INSERT INTO sources (kind, evidence, path, locator, subject, session, mentions)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (kind, evidence, path, locator, subject, session, ",".join(mentions)),
    )
    db.execute(
        "INSERT INTO search (rowid, body) VALUES (?, ?)", (cursor.lastrowid, body)
    )


def _known_subjects(metadata_dir: Optional[Path]) -> List[str]:
    if metadata_dir is None:
        return []
    animals = metadata_dir / ndos_table.ANIMALS_FILE
    if not animals.is_file():
        return []
    try:
        rows = ndos_table.read_table(animals)
    except OSError:
        return []
    return [row.get("subject_id", "").strip() for row in rows if row.get("subject_id")]


def _find_metadata_dir(root: Path) -> Optional[Path]:
    for candidate in (root / "metadata", root):
        if (candidate / ndos_table.SESSIONS_FILE).is_file():
            return candidate
    return None


def _index_metadata(
    db: sqlite3.Connection, metadata_dir: Path, subjects: Sequence[str]
) -> Tuple[int, List[str]]:
    """Index what people have entered, row by row.

    Each row becomes one searchable record rather than one per cell, because a
    person looking for "CA1 in a mouse" wants the row where both are true, and
    FTS5 can only require two words to co-occur inside one record.
    """
    added = 0
    seen: List[str] = []
    tables = (
        (ndos_table.ANIMALS_FILE, "subject_id", ""),
        (ndos_table.PROCEDURES_FILE, "subject_id", "procedure_id"),
        (ndos_table.SESSIONS_FILE, "subject_id", "ndos_id"),
    )
    for filename, subject_column, id_column in tables:
        path = metadata_dir / filename
        if not path.is_file():
            continue
        try:
            rows = ndos_table.read_table(path)
        except OSError:
            continue
        seen.append(path)
        for number, row in enumerate(rows, start=2):  # line 1 is the header
            parts = [
                f"{column} {value}"
                for column, value in row.items()
                if value and value.strip() and column in FREE_TEXT_COLUMNS
            ]
            if not parts:
                continue
            locator = row.get(id_column, "") if id_column else ""
            _add(
                db,
                kind="metadata",
                evidence=DECLARED,
                path=filename,
                body="\n".join(parts),
                locator=locator or f"line {number}",
                subject=row.get(subject_column, "").strip(),
                session=row.get("observed_path", "").strip(),
            )
            added += 1
    return added, [str(path) for path in seen]


def _index_documents(
    db: sqlite3.Connection,
    root: Path,
    files: Sequence[Dict[str, Any]],
    subjects: Sequence[str],
    exclude: frozenset = frozenset(),
    on_progress: Optional[Any] = None,
) -> Tuple[int, int]:
    """Index the readable documents a scan found. Returns (indexed, skipped).

    `exclude` holds the metadata tables, which the structural pass has already
    indexed row by row. Reading them again as plain CSV would return the same
    row twice -- once knowing which procedure it is and that a person declared
    it, once knowing neither.
    """
    indexed = skipped = 0
    for entry in files:
        relative = entry.get("path", "")
        if relative in exclude:
            continue
        extension = (entry.get("extension") or "").lower()
        if extension not in TEXT_EXTENSIONS and extension not in ZIP_XML_EXTENSIONS:
            continue
        path = root / relative
        text = extract_text(path)
        if not text or not text.strip():
            skipped += 1
            continue

        # Where the document sits often says which animal it is about. These
        # are the same two functions ndos_organize uses to decide that, called
        # on the same segment list, so a search result and a rebuilt layout
        # cannot disagree about which folder is a subject.
        segments = list(Path(relative).parts[:-1])
        subject = ndos_organize._find_subject(segments)[0] or ""
        session = _session_label(segments)

        _add(
            db,
            kind="document",
            evidence=OBSERVED,
            path=relative,
            body=text,
            locator=ndos_scan._human_bytes(entry.get("size_bytes", 0)),
            subject=subject,
            session=session,
            mentions=_subject_mentions(text, subjects),
        )
        indexed += 1
        if on_progress and indexed % 25 == 0:
            on_progress({"indexed": indexed, "skipped": skipped})
    return indexed, skipped


PATH = "path"


def _index_paths(
    db: sqlite3.Connection,
    files: Sequence[Dict[str, Any]],
) -> int:
    """Make every file findable by its name, whatever is inside it.

    Without this, search reaches the notes about an experiment and not the
    experiment: on a realistic drive the great majority of files are .bin,
    .avi, .tif, .dat -- nothing a text search can open, and the actual data.
    Searching `surgery` also found nothing while `surgery_log.xlsx` sat in the
    root, because nothing indexed the name.

    FTS5's default tokenizer splits on every non-alphanumeric character, so
    inserting the path as-is makes each of `raw_data`, `M123`, `20250314`,
    `raw` and `dat` a separate searchable word for free. The extension and the
    scanner's category go in too, so "find the video files" works.
    """
    added = 0
    for entry in files:
        relative = entry.get("path", "")
        if not relative:
            continue
        extension = (entry.get("extension") or "").lower()
        category = ndos_report.categorise(extension, entry.get("name", ""))
        segments = list(Path(relative).parts[:-1])
        _add(
            db,
            kind=PATH,
            evidence=OBSERVED,
            path=relative,
            body=f"{relative} {extension} {category}",
            locator=ndos_scan._human_bytes(entry.get("size_bytes", 0)),
            subject=ndos_organize._find_subject(segments)[0] or "",
            session=_session_label(segments),
        )
        added += 1
    return added


def build(
    source: Path,
    index_path: Path,
    manifest: Optional[Dict[str, Any]] = None,
    quiet: bool = False,
    on_progress: Optional[Any] = None,
) -> Dict[str, Any]:
    """Build a search index for a directory, reading and changing nothing in it.

    The index is written where you ask. It is derived data and can be deleted
    and rebuilt at any time; nothing else depends on it.
    """
    if not _supports_fts5():
        raise RuntimeError(
            "this Python's SQLite was built without FTS5, so full-text search "
            "is unavailable. Everything else in NDOS still works."
        )
    if not source.is_dir():
        raise ValueError(f"not a directory: {source}")

    if manifest is None:
        manifest = ndos_scan.scan(
            source, include_checksums=False, progress=not quiet,
            follow_symlinks=ndos_table.looks_like_project(source),
        )

    if index_path.exists():
        index_path.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)

    db = _connect(index_path)
    try:
        _create(db)
        metadata_dir = _find_metadata_dir(source)
        subjects = _known_subjects(metadata_dir)

        declared, indexed_tables = (
            _index_metadata(db, metadata_dir, subjects)
            if metadata_dir else (0, [])
        )
        # The manifest records paths relative to the source root, so the
        # exclusion list has to be in the same terms.
        exclude = frozenset(
            Path(table).relative_to(source).as_posix()
            for table in indexed_tables
            if Path(table).is_relative_to(source)
        )
        documents, unreadable = _index_documents(
            db, source, manifest.get("files", []), subjects, exclude, on_progress
        )
        named = _index_paths(db, manifest.get("files", []))

        summary = {
            "index_version": INDEX_VERSION,
            "generator": ndos_scan.invocation("ndos_search"),
            "generated_at": ndos_scan._utc_iso(
                datetime.now(tz=timezone.utc).timestamp()
            ),
            "source_root": str(source),
            "documents_indexed": documents,
            "documents_unreadable": unreadable,
            "metadata_rows_indexed": declared,
            "files_named": named,
            "known_subjects": len(subjects),
        }
        for key, value in summary.items():
            db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)", (key, str(value))
            )
        db.commit()
        return summary
    finally:
        db.close()


def _escape_query(text: str) -> str:
    """Make a person's words safe for FTS5 without taking away its operators.

    `AND`, `OR`, `NOT`, quoted phrases and `*` prefixes are worth keeping --
    they are why this is better than grep. But a bare `-` or `:` is a syntax
    error, and "CA1-injection" is a thing a person would reasonably type.
    """
    if any(token in text for token in (" AND ", " OR ", " NOT ", '"')):
        return text
    words = [word for word in re.split(r"[^\w*]+", text) if word]
    if not words:
        raise ValueError("nothing to search for")
    return " ".join(f'"{word}"' if not word.endswith("*") else word for word in words)


#: How many name matches to read before summarising. A search for a common
#: token on a million-file drive should not pull a million rows into memory to
#: count them; the directory summary is accurate up to here and says when it
#: stopped.
NAME_MATCH_CAP = 5000


def _by_directory(rows: Sequence[sqlite3.Row]) -> List[Dict[str, Any]]:
    """Name matches, collapsed to the directories holding them."""
    folders: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        parent = str(Path(row["path"]).parent)
        if parent == ".":
            parent = "(root)"
        entry = folders.setdefault(
            parent,
            {
                "directory": parent,
                "file_count": 0,
                "examples": [],
                "subject": row["subject"] or "",
                "session": row["session"] or "",
            },
        )
        entry["file_count"] += 1
        if len(entry["examples"]) < 3:
            entry["examples"].append(Path(row["path"]).name)
    return sorted(
        folders.values(), key=lambda e: (-e["file_count"], e["directory"])
    )


def _wideneable(expression: str) -> bool:
    """Whether widening to a prefix search is safe and meaningful."""
    return "*" not in expression and not any(
        token in expression for token in (" AND ", " OR ", " NOT ")
    )


def _as_prefix(expression: str) -> str:
    """Turn each quoted word into a prefix term: "gcamp" -> gcamp*."""
    words = re.findall(r'"([^"]+)"', expression) or expression.split()
    return " ".join(f"{word}*" for word in words)


def find(
    index_path: Path, query: str, limit: int = 20
) -> Dict[str, Any]:
    """Search the index. Results are ranked, not judged."""
    if not index_path.is_file():
        raise ValueError(
            f"no index at {index_path}. Build one with: ndos search index <path>"
        )
    db = _connect(index_path)

    def run(expression: str, kinds: Sequence[str], cap: int) -> List[sqlite3.Row]:
        placeholders = ",".join("?" * len(kinds))
        try:
            return db.execute(
                f"""
                SELECT s.kind, s.evidence, s.path, s.locator, s.subject,
                       s.session, s.mentions,
                       snippet(search, 0, '[', ']', ' … ', 14) AS snippet,
                       bm25(search) AS score
                FROM search JOIN sources s ON s.id = search.rowid
                WHERE search MATCH ? AND s.kind IN ({placeholders})
                ORDER BY score
                LIMIT ?
                """,
                (expression, *kinds, cap),
            ).fetchall()
        except sqlite3.OperationalError as error:
            raise ValueError(f"could not read {query!r} as a search: {error}")

    try:
        expression = _escape_query(query)
        rows = run(expression, ("document", "metadata"), limit)

        # Lab vocabulary is full of suffixed names -- GCaMP6f, AAV9, C57BL/6J --
        # and FTS5 treats each as one token, so an exact search for "GCaMP"
        # misses "GCaMP6f" entirely. Rather than make every search a prefix
        # search, which would let "CA1" match "CA123", widen only when the exact
        # form found nothing, and say so in the result.
        widened = False
        if not rows and _wideneable(expression):
            wider = _as_prefix(expression)
            if wider != expression:
                found = run(wider, ("document", "metadata"), limit)
                if found:
                    rows, expression, widened = found, wider, True

        # Names are searched separately and summarised by directory. A drive
        # where 240 files sit under raw_data/M123 should say so, not list 240
        # rows: the useful answer is which parts of the tree are involved.
        named = run(expression, (PATH,), NAME_MATCH_CAP)
        if not named and not widened and _wideneable(expression):
            wider = _as_prefix(expression)
            if wider != expression:
                named = run(wider, (PATH,), NAME_MATCH_CAP)
                if named:
                    expression, widened = wider, True
        directories = _by_directory(named)

        meta = {
            row["key"]: row["value"]
            for row in db.execute("SELECT key, value FROM meta")
        }
        hits = [
            {
                "kind": row["kind"],
                "evidence": row["evidence"],
                "path": row["path"],
                "locator": row["locator"],
                "subject": row["subject"],
                "session": row["session"],
                "mentions": [m for m in (row["mentions"] or "").split(",") if m],
                "snippet": " ".join(row["snippet"].split()),
                "score": round(-row["score"], 3),
            }
            for row in rows
        ]
        return {
            "index_version": meta.get("index_version", INDEX_VERSION),
            "source_root": meta.get("source_root", ""),
            "query": query,
            "expression": expression,
            "widened": widened,
            "match_count": len(hits),
            "limit": limit,
            "hits": hits,
            "name_match_count": len(named),
            "name_matches_capped": len(named) >= NAME_MATCH_CAP,
            "directories": directories,
        }
    finally:
        db.close()


def render_build(summary: Dict[str, Any]) -> str:
    rows = [
        ("Files findable by name", summary["files_named"]),
        ("Documents read", summary["documents_indexed"]),
        ("Metadata rows", summary["metadata_rows_indexed"]),
        ("Known animals", summary["known_subjects"]),
    ]
    width = max(len(label) for label, _ in rows)
    lines = [
        "=" * 72,
        "NDOS SEARCH INDEX",
        "=" * 72,
        f"Source    : {summary['source_root']}",
        f"Built     : {summary['generated_at']}",
        "",
    ]
    lines += [f"{label:<{width}} : {value}" for label, value in rows]
    if summary["documents_unreadable"]:
        lines.append(
            f"{'Contents unreadable':<{width}} : "
            f"{summary['documents_unreadable']} (binary, empty, or a format "
            "needing a parser NDOS does not bundle -- the names are still "
            "searchable)"
        )
    lines += ["", 'Search it with: ndos search find "<words>"']
    return "\n".join(lines)


def render_find(result: Dict[str, Any]) -> str:
    """Two kinds of answer, kept apart.

    A file whose name contains the word and a document that discusses it are
    different claims, and ranking them against each other is meaningless: a
    note mentioning CA1 fifty times would outrank a folder full of CA1
    recordings, or the reverse, depending on nothing of interest.
    """
    if not result["hits"] and not result["directories"]:
        return (
            f"Nothing matched {result['query']!r}.\n\n"
            "Searched as: " + result["expression"] + "\n"
            "A word absent from the index is not a word absent from the data: "
            "file names are indexed in full, but of their contents only text "
            "files, Word and Excel documents and the metadata tables are read. "
            "PDFs are not."
        )

    lines = [
        "=" * 72,
        f"Results for {result['query']!r}",
        "=" * 72,
    ]
    if result.get("widened"):
        lines.append(
            "  No exact match, so this searched for words starting with it: "
            + result["expression"]
        )

    if result["directories"]:
        total = result["name_match_count"]
        capped = " (counted up to the cap)" if result["name_matches_capped"] else ""
        lines += [
            "",
            "-" * 72,
            f"FILES WHOSE NAME OR PATH MATCHES — {total} file(s){capped}",
            "-" * 72,
        ]
        for folder in result["directories"][:12]:
            lines.append("")
            lines.append(f"  {folder['directory']}/    {folder['file_count']} file(s)")
            lines.append("      e.g. " + ", ".join(folder["examples"]))
            trail = []
            if folder["subject"]:
                trail.append(f"subject {folder['subject']}")
            if folder["session"]:
                trail.append(f"session {folder['session']}")
            if trail:
                lines.append("      " + " · ".join(trail))
        if len(result["directories"]) > 12:
            lines.append("")
            lines.append(
                f"  … and {len(result['directories']) - 12} more directories"
            )

    if result["hits"]:
        lines += [
            "",
            "-" * 72,
            f"DOCUMENTS AND RECORDS MENTIONING IT — {result['match_count']}",
            "-" * 72,
        ]
        for hit in result["hits"]:
            where = hit["path"]
            if hit["locator"]:
                where += f"  ({hit['locator']})"
            lines.append("")
            lines.append(f"  {where}")
            lines.append(f"      {hit['snippet']}")
            trail = []
            if hit["subject"]:
                trail.append(f"subject {hit['subject']}")
            if hit["session"]:
                trail.append(f"session {hit['session']}")
            if hit["mentions"]:
                trail.append("names " + ", ".join(hit["mentions"]))
            if trail:
                lines.append("      " + " · ".join(trail))
            lines.append(f"      {hit['evidence']}, from {hit['kind']}")

    lines += [
        "",
        "-" * 72,
        "These are places to look, not a cohort. A document mentioning CA1 does",
        "not establish that a session targeted it. To select sessions on",
        "recorded evidence -- and see which cannot be ruled out -- use:",
        "  ndos query <linked.json> -w 'target_region~CA1'",
    ]
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ndos search",
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Search ranks; it does not decide. Use `ndos query` to select\n"
            "sessions on recorded evidence."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    builder = subparsers.add_parser(
        "index", help="Build a search index for a directory (read-only)"
    )
    builder.add_argument("source", type=Path, help="Directory to index")
    builder.add_argument(
        "-i", "--index", type=Path, default=Path(DEFAULT_INDEX),
        help=f"Where to write the index (default: ./{DEFAULT_INDEX})",
    )
    builder.add_argument("-q", "--quiet", action="store_true")

    finder = subparsers.add_parser("find", help="Search an index")
    finder.add_argument("query", help="Words to look for; AND, OR, NOT and \"phrases\" work")
    finder.add_argument(
        "-i", "--index", type=Path, default=Path(DEFAULT_INDEX),
        help=f"Index to search (default: ./{DEFAULT_INDEX})",
    )
    finder.add_argument("-n", "--limit", type=int, default=20, help="Maximum results")
    finder.add_argument(
        "--format", choices=("text", "json"), default="text",
        help="Output format",
    )

    args = parser.parse_args(argv)

    try:
        if args.command == "index":
            summary = build(args.source, args.index, quiet=args.quiet)
            if not args.quiet:
                print(render_build(summary))
            return 0

        result = find(args.index, args.query, args.limit)
        if args.format == "json":
            print(json.dumps(result, indent=2))
        else:
            print(render_find(result))
        return 0 if (result["hits"] or result["directories"]) else 1
    except (ValueError, RuntimeError) as error:
        print(f"ndos search: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
