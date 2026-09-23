"""Tests for the read-only scanner and project initialiser.

The safety guarantees are the point of this module, so they are tested
explicitly: a scan must never alter the tree it is looking at, and it must
never silently omit something it could not read.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ndos_init import initialize
import ndos_scan
from ndos_scan import MANIFEST_VERSION, scan


def _tree_state(root: Path):
    """Snapshot every path, size, and mtime below ``root``."""
    state = {}
    for current, _, filenames in os.walk(root):
        for filename in filenames:
            path = Path(current) / filename
            stat = path.stat()
            state[str(path)] = (stat.st_size, stat.st_mtime_ns)
    return state


class ScanTests(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        (root / "nested").mkdir()
        (root / "nested" / "recording.bin").write_bytes(b"signal")
        (root / "notes.txt").write_text("session notes", encoding="utf-8")
        (root / ".DS_Store").write_bytes(b"ignored")

    def test_scan_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture(root)

            first = scan(root)
            second = scan(root)

            # generated_at is expected to differ between runs; everything that
            # describes the data itself must not.
            for manifest in (first, second):
                manifest.pop("generated_at")
            self.assertEqual(first, second)

    def test_junk_files_are_excluded_and_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture(root)

            manifest = scan(root)

            self.assertEqual(manifest["file_count"], 2)
            self.assertEqual(
                [entry["path"] for entry in manifest["files"]],
                ["nested/recording.bin", "notes.txt"],
            )
            # Exclusion is reported rather than silent.
            excluded = [
                entry for entry in manifest["skipped"] if entry["reason"] == "excluded"
            ]
            self.assertEqual([entry["path"] for entry in excluded], [".DS_Store"])

    def test_scan_does_not_modify_the_source_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._fixture(root)
            before = _tree_state(root)

            scan(root)

            self.assertEqual(_tree_state(root), before)

    def test_checksums_are_present_and_stable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.bin").write_bytes(b"identical")
            (root / "b.bin").write_bytes(b"identical")
            (root / "c.bin").write_bytes(b"different")

            files = {entry["name"]: entry for entry in scan(root)["files"]}

            self.assertEqual(len(files["a.bin"]["sha256"]), 64)
            self.assertEqual(files["a.bin"]["sha256"], files["b.bin"]["sha256"])
            self.assertNotEqual(files["a.bin"]["sha256"], files["c.bin"]["sha256"])

    def test_no_checksum_mode_omits_digests(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.bin").write_bytes(b"data")

            manifest = scan(root, include_checksums=False)

            self.assertFalse(manifest["checksums"])
            self.assertEqual(len(manifest["files"]), 1)
            for entry in manifest["files"]:
                self.assertNotIn("sha256", entry)

    def test_symlinks_are_not_followed_but_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "real.txt").write_text("data", encoding="utf-8")
            try:
                (root / "link.txt").symlink_to(root / "real.txt")
            except (OSError, NotImplementedError):
                self.skipTest("symlinks unavailable on this platform")

            manifest = scan(root)

            self.assertEqual([e["path"] for e in manifest["files"]], ["real.txt"])
            self.assertEqual(
                [e["path"] for e in manifest["skipped"] if e["reason"] == "symlink"],
                ["link.txt"],
            )

    def test_totals_agree_with_the_file_list(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.bin").write_bytes(b"x" * 100)
            (root / "b.bin").write_bytes(b"y" * 250)

            manifest = scan(root)

            self.assertEqual(manifest["file_count"], len(manifest["files"]))
            self.assertEqual(
                manifest["total_bytes"],
                sum(entry["size_bytes"] for entry in manifest["files"]),
            )
            self.assertEqual(manifest["total_bytes"], 350)

    def test_paths_are_relative_and_never_escape_the_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a" / "b").mkdir(parents=True)
            (root / "a" / "b" / "deep.txt").write_text("x", encoding="utf-8")

            manifest = scan(root)

            for entry in manifest["files"]:
                self.assertFalse(entry["path"].startswith("/"))
                self.assertNotIn("..", entry["path"].split("/"))

    def test_manifest_is_json_serialisable(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = scan(Path(directory))
            parsed = json.loads(json.dumps(manifest))
            self.assertEqual(parsed["manifest_version"], MANIFEST_VERSION)

    def test_scan_rejects_a_non_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file.txt"
            path.write_text("x", encoding="utf-8")
            with self.assertRaises(ValueError):
                scan(path)


class SchemaTests(unittest.TestCase):
    """Validate real manifests against the published schema when possible."""

    def test_manifest_matches_published_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed; NDOS core stays stdlib-only")

        schema_path = Path(__file__).resolve().parent.parent / "schemas" / "manifest.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sub").mkdir()
            (root / "sub" / "rec.ap.bin").write_bytes(b"signal")
            (root / "no_extension").write_bytes(b"")
            (root / ".DS_Store").write_bytes(b"junk")

            jsonschema.validate(scan(root), schema)
            jsonschema.validate(scan(root, include_checksums=False), schema)


class InitTests(unittest.TestCase):
    """Starting a project, for a lab that is about to collect rather than
    one digging out an archive. The standard serves both."""

    def test_init_creates_the_layout_the_manuscript_defines(self):
        from ndos_init import DIRECTORIES, initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)

            for name, _ in DIRECTORIES:
                self.assertTrue((root / name).is_dir(), f"missing {name}/")
            self.assertTrue((root / "README.md").is_file())
            self.assertTrue((root / "project.toml").is_file())

    def test_the_readme_says_where_a_recording_goes(self):
        from ndos_init import initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)
            text = (root / "README.md").read_text(encoding="utf-8")

            self.assertIn("raw_data/<SubjectID>/<SessionID>/", text)
            self.assertIn("YYYYMMDD", text)

    def test_a_session_folder_is_named_by_the_convention(self):
        from ndos_init import add_session, initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)

            raw, created = add_session(root, "M123", "2025-03-14")

            # resolve() both sides: on macOS /var is itself a symlink.
            self.assertEqual(
                raw, (root / "raw_data" / "M123" / "20250314").resolve()
            )
            self.assertTrue(raw.is_dir())
            self.assertTrue(created)
            # The manuscript pairs each raw session with a processed one.
            self.assertTrue(
                (root / "processed_data" / "M123" / "20250314" / "temp").is_dir()
            )

    def test_a_second_recording_that_day_is_numbered(self):
        from ndos_init import add_session, initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)

            _, _ = add_session(root, "M123", "2025-03-14")
            second, _ = add_session(root, "M123", "2025-03-14", number=2)

            self.assertEqual(second.name, "20250314_02")

    def test_an_ambiguous_date_is_refused(self):
        from ndos_init import session_id

        with self.assertRaises(ValueError) as caught:
            session_id("14/03/2025")
        # The same reason table check gives: that form means two things.
        self.assertIn("YYYY-MM-DD", str(caught.exception))

    def test_a_date_that_does_not_exist_is_refused(self):
        from ndos_init import session_id

        with self.assertRaises(ValueError):
            session_id("2025-02-30")

    def test_a_subject_that_would_make_an_odd_folder_is_refused(self):
        from ndos_init import add_session, initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)
            for bad in ("../escape", "M 123", ""):
                with self.assertRaises(ValueError):
                    add_session(root, bad, "2025-03-14")

    def test_running_init_again_does_not_disturb_what_is_there(self):
        from ndos_init import initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)
            (root / "raw_data" / "M123").mkdir(parents=True)
            (root / "README.md").write_text("mine", encoding="utf-8")

            initialize(root)

            self.assertTrue((root / "raw_data" / "M123").is_dir())
            self.assertEqual((root / "README.md").read_text(encoding="utf-8"), "mine")

    def test_force_rewrites_the_generated_files_only(self):
        from ndos_init import initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)
            (root / "raw_data" / "keep.txt").write_text("data", encoding="utf-8")
            (root / "README.md").write_text("mine", encoding="utf-8")

            initialize(root, force=True)

            self.assertNotEqual((root / "README.md").read_text(encoding="utf-8"), "mine")
            self.assertTrue((root / "raw_data" / "keep.txt").is_file())

    def test_project_id_is_slugified_from_the_directory_name(self):
        from ndos_init import initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "My Study (2026)!"
            self.assertIn('id = "my-study-2026"', initialize(root).read_text())


class FreshCollectionTests(unittest.TestCase):
    """A project started with init, then collected into, then described."""

    def test_a_project_started_with_init_is_readable_by_the_rest(self):
        import ndos_table
        from ndos_init import add_session, initialize

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)
            raw, _ = add_session(root, "M123", "2025-03-14")
            (raw / "M123_20250314_raw.dat").write_bytes(b"signal")

            # The same command an archive user runs, on a project that was
            # never an archive.
            self.assertTrue(ndos_table.looks_like_project(root))
            manifest = ndos_table._load_manifest(root, quiet=True)
            rows = ndos_table.group_sessions(
                manifest, subject_depth=1, group_depth=2
            )
            subjects = {row["observed_folder_subject"] for row in rows}
            self.assertIn("M123", subjects)


class ProgressCallbackTests(unittest.TestCase):
    """What a caller without a terminal is told while a long scan runs.

    The interface passes `progress=False`, because it has no terminal to
    print to, and `on_progress`, because it has a page to update. Those are
    two different questions and one flag was answering both: asking for no
    terminal output also skipped the walk that counts the work up front, so
    the page got a file count climbing towards no total, with no time
    remaining -- on exactly the scans that take long enough to need them.
    """

    def _scan(self, root, **kwargs):
        seen = []
        ndos_scan.scan(root, on_progress=seen.append, **kwargs)
        return seen

    def _lab(self, directory, files=60):
        root = Path(directory) / "lab"
        root.mkdir()
        for i in range(files):
            (root / f"file_{i:03d}.dat").write_bytes(b"x" * 4096)
        return root

    def test_a_checksummed_scan_reports_a_total_to_a_caller_without_a_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._lab(directory)
            # Report on every file rather than every two seconds, so the test
            # does not depend on how fast the machine running it is.
            with mock.patch.object(ndos_scan, "PROGRESS_EVERY_SECONDS", 0.0):
                updates = self._scan(root, include_checksums=True, progress=False)

            self.assertTrue(updates, "a scan reported nothing at all")
            totals = {u["total_files"] for u in updates}
            self.assertNotIn(
                None, totals,
                "the page was given a file count with no total to count towards",
            )
            self.assertEqual(totals, {60})

    def test_it_also_says_how_much_longer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._lab(directory)
            with mock.patch.object(ndos_scan, "PROGRESS_EVERY_SECONDS", 0.0):
                updates = self._scan(root, include_checksums=True, progress=False)

            # The last update can legitimately have nothing left to do.
            self.assertTrue(
                any(u["seconds_remaining"] is not None for u in updates),
                "no update carried a time remaining",
            )

    def test_a_scan_without_checksums_does_not_pay_for_a_second_walk(self):
        # Nothing is read, so there is no duration to predict and no reason
        # to walk the tree twice to find out.
        with tempfile.TemporaryDirectory() as directory:
            root = self._lab(directory)
            with mock.patch.object(ndos_scan, "PROGRESS_EVERY_SECONDS", 0.0):
                updates = self._scan(root, include_checksums=False, progress=False)

            self.assertTrue(updates)
            self.assertTrue(all(u["total_files"] is None for u in updates))


if __name__ == "__main__":
    unittest.main()
