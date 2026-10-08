"""Tests for ndos_search.

The thing being tested is not "does FTS5 work" -- SQLite's tests cover that.
It is whether a word a researcher remembers leads to the data it describes,
and whether a hit is honest about how it is known.
"""

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ndos_search  # noqa: E402
import ndos_table  # noqa: E402

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def write_docx(path: Path, paragraphs):
    """A real .docx: a ZIP whose word/document.xml holds the text."""
    body = "".join(
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="{WORD_NS}">'
            f"<w:body>{body}</w:body></w:document>",
        )


def write_xlsx(path: Path, strings):
    """A real .xlsx: the words live in the shared-strings table."""
    items = "".join(f"<si><t>{value}</t></si>" for value in strings)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "xl/sharedStrings.xml",
            f'<?xml version="1.0"?><sst xmlns="{SHEET_NS}" '
            f'count="{len(strings)}">{items}</sst>',
        )


class ExtractionTests(unittest.TestCase):
    """Reading words out of the formats a lab actually leaves lying around."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_word_document_is_read_without_a_dependency(self):
        path = self.root / "notes.docx"
        write_docx(path, ["Perfusion notes, M123.", "GCaMP6f in dorsal CA1."])
        text = ndos_search.extract_text(path)
        self.assertIn("CA1", text)
        self.assertIn("M123", text)

    def test_a_spreadsheet_is_read_without_a_dependency(self):
        path = self.root / "surgery_log.xlsx"
        write_xlsx(path, ["subject_id", "M123", "injection", "CA1"])
        text = ndos_search.extract_text(path)
        self.assertIn("CA1", text)

    def test_plain_text_is_read(self):
        path = self.root / "notes.txt"
        path.write_text("Rig 2, alternation task, clean theta.\n", encoding="utf-8")
        self.assertIn("theta", ndos_search.extract_text(path))

    def test_a_binary_file_wearing_a_text_extension_is_refused(self):
        """The synthetic fixtures do exactly this, and so do real drives."""
        path = self.root / "data.csv"
        path.write_bytes(b"surglog-ndos-fixture-" + b"\0" * 2048)
        self.assertIsNone(ndos_search.extract_text(path))

    def test_formats_needing_a_parser_are_left_alone(self):
        # Reading these would mean taking a dependency, which NDOS does not do
        # for a convenience. Saying so is better than a silent empty result.
        for name in ("scan.pdf", "old.doc", "notes.odt"):
            path = self.root / name
            path.write_bytes(b"%PDF-1.4 whatever")
            self.assertIsNone(ndos_search.extract_text(path), name)

    def test_a_damaged_office_file_does_not_raise(self):
        path = self.root / "broken.docx"
        path.write_bytes(b"this is not a zip")
        self.assertIsNone(ndos_search.extract_text(path))


class SearchTests(unittest.TestCase):
    """Indexing a drive and finding things in it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.lab = self.root / "lab"
        (self.lab / "histology").mkdir(parents=True)
        (self.lab / "raw_data" / "M123" / "20250314").mkdir(parents=True)
        self.index = self.root / "index.db"

        write_docx(
            self.lab / "histology" / "notes.docx",
            ["Perfusion notes, M123.", "GCaMP6f expression in dorsal CA1."],
        )
        write_xlsx(
            self.lab / "surgery_log.xlsx",
            ["subject_id", "M123", "injection", "CA1", "M124", "CA3"],
        )
        (self.lab / "raw_data" / "M123" / "20250314" / "notes.txt").write_text(
            "Rig 2. Animal M123 ran the alternation task.\n", encoding="utf-8"
        )

        metadata = self.lab / "metadata"
        metadata.mkdir()
        (metadata / ndos_table.ANIMALS_FILE).write_text(
            "subject_id,species,strain,sex,date_of_birth,genotype,source,notes\n"
            "M123,mus musculus,C57BL/6J,F,2024-11-01,WT,Jackson,implanted\n"
            "M124,mus musculus,C57BL/6J,M,2024-11-01,WT,Jackson,\n",
            encoding="utf-8",
        )
        (metadata / ndos_table.PROCEDURES_FILE).write_text(
            "procedure_id,subject_id,procedure_date,procedure_type,target_region,"
            "construct_or_drug,dose,notes\n"
            "P01,M123,2025-02-01,injection,dorsal CA1,AAV9-GCaMP6f,300nl,\n",
            encoding="utf-8",
        )
        (metadata / ndos_table.SESSIONS_FILE).write_text(
            "ndos_id,observed_path,observed_file_count,observed_bytes,subject_id,"
            "session_date,session_type,task,qc_status,notes\n"
            "ndos-aaa,raw_data/M123/20250314,1,64,M123,2025-03-14,"
            "electrophysiology,alternation,pass,clean theta\n",
            encoding="utf-8",
        )

        self.summary = ndos_search.build(self.lab, self.index, quiet=True)

    def paths(self, query, limit=20):
        return [hit["path"] for hit in ndos_search.find(self.index, query, limit)["hits"]]

    def test_indexing_changes_nothing_in_the_source(self):
        before = {
            path: path.stat().st_mtime_ns
            for path in sorted(self.lab.rglob("*")) if path.is_file()
        }
        ndos_search.build(self.lab, self.root / "second.db", quiet=True)
        after = {
            path: path.stat().st_mtime_ns
            for path in sorted(self.lab.rglob("*")) if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertNotIn(
            self.index.name, [p.name for p in self.lab.rglob("*")],
            "the index was written into the directory being indexed",
        )

    def test_a_word_in_a_spreadsheet_is_findable(self):
        self.assertIn("surgery_log.xlsx", self.paths("CA1"))

    def test_a_word_in_a_word_document_is_findable(self):
        self.assertIn("histology/notes.docx", self.paths("perfusion"))

    def test_a_document_says_which_animals_it_names(self):
        """This is the chain: a log mentioning CA1 also names the animals."""
        hit = next(
            h for h in ndos_search.find(self.index, "CA1")["hits"]
            if h["path"] == "surgery_log.xlsx"
        )
        self.assertEqual(hit["mentions"], ["M123", "M124"])

    def test_a_document_under_a_session_inherits_it(self):
        hit = next(
            h for h in ndos_search.find(self.index, "alternation")["hits"]
            if h["path"].endswith("notes.txt")
        )
        self.assertEqual(hit["subject"], "M123")
        self.assertEqual(hit["session"], "20250314")

    def test_a_hit_records_how_it_is_known(self):
        kinds = {
            hit["path"]: hit["evidence"]
            for hit in ndos_search.find(self.index, "CA1")["hits"]
        }
        # Read from a file on disk.
        self.assertEqual(kinds["surgery_log.xlsx"], ndos_search.OBSERVED)
        # Entered by a person in a table.
        self.assertEqual(kinds[ndos_table.PROCEDURES_FILE], ndos_search.DECLARED)

    def test_a_metadata_table_is_not_indexed_twice(self):
        """Once structurally and once as plain CSV would return a row twice."""
        paths = self.paths("CA1")
        self.assertEqual(paths.count(ndos_table.PROCEDURES_FILE), 1)
        self.assertNotIn(f"metadata/{ndos_table.PROCEDURES_FILE}", paths)

    def test_boolean_operators_work(self):
        both = self.paths("CA1 AND injection")
        self.assertIn("surgery_log.xlsx", both)
        self.assertNotIn("histology/notes.docx", both)

    def test_a_quoted_phrase_works(self):
        self.assertIn(ndos_table.PROCEDURES_FILE, self.paths('"dorsal CA1"'))

    def test_punctuation_a_person_would_type_does_not_break_it(self):
        # Bare `-` and `:` are FTS5 syntax errors; "CA1-injection" is a
        # reasonable thing to type.
        for query in ("CA1-injection", "AAV9-GCaMP6f", "C57BL/6J"):
            ndos_search.find(self.index, query)  # must not raise

    def test_a_suffixed_name_is_found_by_its_stem(self):
        """GCaMP6f is one token, so an exact search for GCaMP misses it.

        Lab vocabulary is full of these, so a search that found nothing
        exactly is widened to a prefix -- and says that it did.
        """
        result = ndos_search.find(self.index, "GCaMP")
        self.assertTrue(result["hits"])
        self.assertTrue(result["widened"])
        self.assertIn("*", result["expression"])

    def test_widening_does_not_happen_when_there_is_an_exact_match(self):
        result = ndos_search.find(self.index, "CA1")
        self.assertFalse(result["widened"])
        self.assertNotIn("*", result["expression"])

    def test_species_is_left_out_so_it_cannot_match_everything(self):
        """`ndos query -w species=mouse` answers this precisely instead."""
        self.assertEqual(self.paths("musculus"), [])

    def test_a_word_nobody_wrote_returns_nothing(self):
        self.assertEqual(self.paths("optogenetics"), [])

    def test_an_empty_query_is_refused_in_words(self):
        with self.assertRaises(ValueError):
            ndos_search.find(self.index, "   ")

    def test_searching_a_missing_index_says_how_to_build_one(self):
        with self.assertRaises(ValueError) as caught:
            ndos_search.find(self.root / "absent.db", "CA1")
        self.assertIn("ndos search index", str(caught.exception))

    def test_the_summary_counts_what_it_read(self):
        self.assertEqual(self.summary["metadata_rows_indexed"], 4)
        self.assertGreaterEqual(self.summary["documents_indexed"], 3)
        self.assertEqual(self.summary["known_subjects"], 2)

    def test_rebuilding_replaces_rather_than_doubles(self):
        again = ndos_search.build(self.lab, self.index, quiet=True)
        self.assertEqual(
            again["documents_indexed"], self.summary["documents_indexed"]
        )
        self.assertEqual(self.paths("CA1").count("surgery_log.xlsx"), 1)

    def test_results_are_ranked_not_merely_listed(self):
        hits = ndos_search.find(self.index, "CA1")["hits"]
        scores = [hit["score"] for hit in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_the_output_refuses_to_be_mistaken_for_a_cohort(self):
        """Search ranks; it does not decide. The rendering has to say so."""
        text = ndos_search.render_find(ndos_search.find(self.index, "CA1"))
        self.assertIn("not a cohort", text)
        self.assertIn("ndos query", text)

    def test_indexing_something_that_is_not_a_directory_is_refused(self):
        with self.assertRaises(ValueError):
            ndos_search.build(
                self.lab / "surgery_log.xlsx", self.root / "x.db", quiet=True
            )


class CommandLineTests(unittest.TestCase):
    def test_help_works(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, str(ROOT / "ndos_search.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("index", result.stdout)
        self.assertIn("find", result.stdout)

    def test_the_dispatcher_knows_about_it(self):
        import ndos

        self.assertIn("search", [name for name, _, _ in ndos.COMMANDS])


class NameMatchTests(unittest.TestCase):
    """Finding files by their name, whatever is inside them.

    Without this, search reached the notes about an experiment and not the
    experiment: on a realistic drive the great majority of files are .bin,
    .avi, .tif and .dat, which no text search can open and which are the
    actual data. Measured on the messy-lab fixture, 3% of files were
    reachable before and 91% after -- the remainder being .DS_Store and
    Thumbs.db, which the scanner excludes on purpose.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.lab = self.root / "lab"
        session = self.lab / "raw_data" / "M01" / "20250314"
        session.mkdir(parents=True)
        # Binary acquisition data: unreadable, and the point of the exercise.
        for name in ("M01_20250314_raw.bin", "M01_20250314_raw.meta",
                     "M01_20250314_video.avi"):
            (session / name).write_bytes(b"\0" * 512)
        (self.lab / "surgery_log.xlsx").write_bytes(b"\0" * 256)
        backup = self.lab / "backup" / "raw_data" / "M01" / "20250314"
        backup.mkdir(parents=True)
        (backup / "M01_20250314_raw.bin").write_bytes(b"\0" * 512)

        self.index = self.root / "index.db"
        self.summary = ndos_search.build(self.lab, self.index, quiet=True)

    def test_a_file_is_findable_by_a_word_in_its_name(self):
        """`surgery_log.xlsx` is unreadable binary; its name is still a fact."""
        result = ndos_search.find(self.index, "surgery")
        self.assertEqual(result["name_match_count"], 1)
        self.assertIn(
            "surgery_log.xlsx",
            result["directories"][0]["examples"],
        )

    def test_binary_acquisition_data_is_reachable(self):
        result = ndos_search.find(self.index, "bin")
        self.assertGreaterEqual(result["name_match_count"], 2)

    def test_an_extension_is_searchable(self):
        self.assertGreaterEqual(
            ndos_search.find(self.index, "avi")["name_match_count"], 1
        )

    def test_a_scanner_category_is_searchable(self):
        """So "find the video files" works without knowing the extension."""
        self.assertGreaterEqual(
            ndos_search.find(self.index, "Imaging")["name_match_count"], 1
        )

    def test_name_matches_are_summarised_by_directory_not_listed(self):
        """240 files under one folder should say so, not print 240 rows."""
        result = ndos_search.find(self.index, "M01")
        folders = {entry["directory"] for entry in result["directories"]}
        self.assertIn("raw_data/M01/20250314", folders)
        for entry in result["directories"]:
            self.assertLessEqual(len(entry["examples"]), 3)

    def test_a_duplicate_copy_shows_as_its_own_directory(self):
        """Seeing backup/ beside the original is the point of the summary."""
        folders = [
            entry["directory"]
            for entry in ndos_search.find(self.index, "M01")["directories"]
        ]
        self.assertTrue(
            any(folder.startswith("backup/") for folder in folders), folders
        )

    def test_a_directory_carries_the_subject_and_session_it_belongs_to(self):
        entry = next(
            e for e in ndos_search.find(self.index, "M01")["directories"]
            if e["directory"] == "raw_data/M01/20250314"
        )
        self.assertEqual(entry["subject"], "M01")
        self.assertEqual(entry["session"], "20250314")

    def test_directories_are_reported_with_forward_slashes(self):
        """An index built on Windows must read the same as one built anywhere.

        `str(Path(...).parent)` gave backslashes, which only the Windows CI
        jobs noticed. Manifests use forward slashes on every platform and so
        must this.
        """
        for entry in ndos_search.find(self.index, "M01")["directories"]:
            self.assertNotIn("\\", entry["directory"])

    def test_bigger_directories_come_first(self):
        counts = [
            entry["file_count"]
            for entry in ndos_search.find(self.index, "M01")["directories"]
        ]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_names_and_documents_are_reported_separately(self):
        """Ranking a filename against a document would compare nothing useful."""
        (self.lab / "notes.txt").write_text(
            "M01 ran the task on the first day.\n", encoding="utf-8"
        )
        ndos_search.build(self.lab, self.index, quiet=True)
        result = ndos_search.find(self.index, "M01")

        self.assertTrue(result["directories"], "no name matches")
        self.assertTrue(result["hits"], "no document matches")
        self.assertTrue(all(hit["kind"] != "path" for hit in result["hits"]))
        text = ndos_search.render_find(result)
        self.assertIn("FILES WHOSE NAME OR PATH MATCHES", text)
        self.assertIn("DOCUMENTS AND RECORDS MENTIONING IT", text)

    def test_every_file_the_scanner_saw_is_reachable(self):
        import ndos_scan

        manifest = ndos_scan.scan(self.lab, include_checksums=False, progress=False)
        self.assertEqual(self.summary["files_named"], manifest["file_count"])

    def test_a_word_in_no_name_and_no_document_still_finds_nothing(self):
        result = ndos_search.find(self.index, "optogenetics")
        self.assertEqual(result["name_match_count"], 0)
        self.assertEqual(result["hits"], [])
        self.assertIn("Nothing matched", ndos_search.render_find(result))


class ChainTests(unittest.TestCase):
    """Word to document to animal to recordings.

    Search telling you a surgery log names M123 leaves you looking M123 up by
    hand. The join already exists -- sessions.csv carries the subject and the
    observed path -- it just was not being followed.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.lab = self.root / "lab"
        (self.lab / "histology").mkdir(parents=True)
        write_xlsx(
            self.lab / "surgery_log.xlsx",
            ["subject_id", "M123", "injection", "CA1", "M124", "CA3"],
        )

        metadata = self.lab / "metadata"
        metadata.mkdir()
        (metadata / ndos_table.ANIMALS_FILE).write_text(
            "subject_id,species,strain,sex,date_of_birth,genotype,source,notes\n"
            "M123,mus musculus,C57BL/6J,F,2024-11-01,WT,Jackson,\n"
            "M124,mus musculus,C57BL/6J,M,2024-11-01,WT,Jackson,\n",
            encoding="utf-8",
        )
        # M123 has two sessions. M124 is named in the log and has none, which
        # is the gap between what the notes say and what is on the drive.
        (metadata / ndos_table.SESSIONS_FILE).write_text(
            "ndos_id,observed_path,observed_file_count,observed_bytes,subject_id,"
            "session_date,session_type,task,qc_status,notes\n"
            "ndos-a,raw_data/M123/20250314,12,640,M123,2025-03-14,"
            "electrophysiology,alternation,pass,\n"
            "ndos-b,raw_data/M123/20250321,1,64,M123,2025-03-21,"
            "electrophysiology,alternation,fail,\n",
            encoding="utf-8",
        )
        self.summary = ndos_search.build(self.lab, self.root / "i.db", quiet=True)
        self.index = self.root / "i.db"

    def hit(self, query, path):
        return next(
            h for h in ndos_search.find(self.index, query)["hits"]
            if h["path"] == path
        )

    def test_a_document_leads_to_the_recordings_of_the_animal_it_names(self):
        animals = {
            a["subject"]: a
            for a in self.hit("CA1", "surgery_log.xlsx")["recordings"]
        }
        self.assertEqual(animals["M123"]["session_count"], 2)
        self.assertEqual(
            [s["path"] for s in animals["M123"]["sessions"]],
            ["raw_data/M123/20250314", "raw_data/M123/20250321"],
        )

    def test_a_session_carries_what_is_known_about_it(self):
        session = self.hit("CA1", "surgery_log.xlsx")["recordings"][0]["sessions"][0]
        self.assertEqual(session["date"], "2025-03-14")
        self.assertEqual(session["file_count"], "12")
        self.assertEqual(session["session_type"], "electrophysiology")
        self.assertEqual(session["qc_status"], "pass")

    def test_an_animal_named_with_no_data_is_reported_rather_than_dropped(self):
        """The log says M124 was injected and the drive holds nothing for it."""
        animals = {
            a["subject"]: a
            for a in self.hit("CA1", "surgery_log.xlsx")["recordings"]
        }
        self.assertIn("M124", animals)
        self.assertEqual(animals["M124"]["session_count"], 0)

        text = ndos_search.render_find(ndos_search.find(self.index, "CA1"))
        self.assertIn("M124 has no sessions recorded", text)

    def test_the_rendering_shows_the_paths(self):
        text = ndos_search.render_find(ndos_search.find(self.index, "CA1"))
        self.assertIn("M123 has 2 sessions", text)
        self.assertIn("raw_data/M123/20250314", text)

    def test_one_file_is_not_one_files(self):
        text = ndos_search.render_find(ndos_search.find(self.index, "CA1"))
        self.assertIn("1 file,", text)
        self.assertNotIn("1 files", text)

    def test_the_map_is_stored_in_the_index_not_read_at_search_time(self):
        """So a moved or deleted metadata folder does not break search."""
        import shutil

        shutil.rmtree(self.lab / "metadata")
        animals = {
            a["subject"]: a
            for a in self.hit("CA1", "surgery_log.xlsx")["recordings"]
        }
        self.assertEqual(animals["M123"]["session_count"], 2)

    def test_the_summary_counts_the_sessions_it_linked(self):
        self.assertEqual(self.summary["sessions_linked"], 2)

    def test_only_a_few_sessions_are_listed_per_animal(self):
        """Forty animals with twenty sessions each is not a useful printout."""
        self.assertLessEqual(
            ndos_search.RECORDINGS_PER_SUBJECT, 5
        )
        animal = self.hit("CA1", "surgery_log.xlsx")["recordings"][0]
        self.assertLessEqual(
            len(animal["sessions"]), ndos_search.RECORDINGS_PER_SUBJECT
        )

    def test_a_drive_with_no_metadata_still_searches(self):
        bare = self.root / "bare"
        (bare / "histology").mkdir(parents=True)
        (bare / "histology" / "notes.txt").write_text(
            "CA1 overview scan.\n", encoding="utf-8"
        )
        index = self.root / "bare.db"
        summary = ndos_search.build(bare, index, quiet=True)
        self.assertEqual(summary["sessions_linked"], 0)
        hits = ndos_search.find(index, "CA1")["hits"]
        self.assertTrue(hits)
        self.assertEqual(hits[0]["recordings"], [])


class TagTests(unittest.TestCase):
    """Flags a person set, reachable through search.

    `ndos tags` records that somebody checked a recording, or that a folder is
    scratch agreed safe to remove. None of that reached search, so a hit gave
    no hint whether you had found real data or something queued for deletion.
    """

    def setUp(self):
        import ndos_init
        import ndos_tags

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.project = self.root / "study"
        ndos_init.initialize(self.project)
        raw, _ = ndos_init.add_session(self.project, "M123", "2025-03-14")
        self.recording = raw / "M123_20250314_raw.dat"
        self.recording.write_bytes(b"signal")

        scratch = self.project / "processed_data" / "M123" / "20250314" / "temp"
        scratch.mkdir(parents=True, exist_ok=True)
        self.junk = scratch / "temp_wh.dat"
        self.junk.write_bytes(b"x")
        # No flag of its own, in a conventionally named scratch folder.
        self.draft = scratch / "CA1_draft.npy"
        self.draft.write_bytes(b"x")

        ndos_tags.set_tags(
            self.recording, {"validated": True},
            note="checked against the rig log",
        )
        ndos_tags.set_tags(
            self.junk, {"temp": True, "deletable": True}, note="kilosort scratch",
        )

        self.index = self.root / "i.db"
        self.summary = ndos_search.build(self.project, self.index, quiet=True)

    def folder(self, query, name):
        return next(
            entry
            for entry in ndos_search.find(self.index, query)["directories"]
            if name in entry["directory"]
        )

    def test_a_flag_is_searchable(self):
        result = ndos_search.find(self.index, "deletable")
        self.assertEqual(result["name_match_count"], 1)
        self.assertIn("temp_wh.dat", result["directories"][0]["examples"])

    def test_validated_is_searchable(self):
        self.assertEqual(
            ndos_search.find(self.index, "validated")["name_match_count"], 1
        )

    def test_the_note_is_searchable(self):
        """The note is the only place a person explains a judgement."""
        result = ndos_search.find(self.index, '"rig log"')
        self.assertEqual(result["name_match_count"], 1)

    def test_an_unrelated_search_still_reports_the_flags(self):
        """Finding CA1 and not noticing it is scratch is the real mistake."""
        text = ndos_search.render_find(ndos_search.find(self.index, "CA1"))
        self.assertIn("looks-like-scratch", text)

    def test_a_flag_set_by_a_person_is_not_confused_with_an_inference(self):
        flagged = self.folder("deletable", "temp")["tags"]
        self.assertIn("deletable", flagged)
        self.assertNotIn("looks-like-scratch", flagged)

        inferred = self.folder("looks-like-scratch", "temp")["tags"]
        self.assertIn("looks-like-scratch", inferred)
        self.assertNotIn("deletable", inferred)

    def test_a_scratch_name_alone_is_only_an_inference(self):
        """CA1_draft.npy carries no flag; NDOS noticed the folder it is in."""
        result = ndos_search.find(self.index, "looks-like-scratch")
        self.assertEqual(result["name_match_count"], 1)
        self.assertIn("CA1_draft.npy", result["directories"][0]["examples"])

    def test_ndos_own_records_are_not_called_scratch(self):
        """tags.json sits inside scratch folders and is not scratch."""
        for entry in ndos_search.find(self.index, "looks-like-scratch")["directories"]:
            for name in entry["examples"]:
                self.assertNotIn(name, ndos_search.OWN_FILES)

    def test_ndos_own_records_are_not_indexed_as_lab_documents(self):
        """Searching a flag returned tags.json itself: NDOS talking to itself."""
        hits = ndos_search.find(self.index, "deletable")["hits"]
        self.assertEqual([h["path"] for h in hits if "tags.json" in h["path"]], [])

    def test_a_directory_where_everything_is_flagged_says_all(self):
        self.assertIn("all validated", ndos_search.render_find(
            ndos_search.find(self.index, "M123_20250314_raw")
        ))

    def test_the_summary_counts_flagged_files(self):
        self.assertEqual(self.summary["files_flagged"], 2)

    def test_the_name_match_count_is_the_number_of_files(self):
        """It reported the animals named by the last hit instead.

        `named` held the name-match rows and was then reused inside the hit
        loop for the animals a document mentions, so the count silently
        became a different, plausible-looking number.
        """
        result = ndos_search.find(self.index, "dat")
        self.assertEqual(
            result["name_match_count"],
            sum(entry["file_count"] for entry in result["directories"]),
        )




if __name__ == "__main__":
    unittest.main()
