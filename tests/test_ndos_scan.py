"""Tests for the read-only scanner and project initialiser.

The safety guarantees are the point of this module, so they are tested
explicitly: a scan must never alter the tree it is looking at, and it must
never silently omit something it could not read.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ndos_init import initialize
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
    def test_init_creates_a_profile_without_touching_source_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "animal-study"

            project_file = initialize(root)

            self.assertTrue(project_file.is_file())
            self.assertIn('source_mode = "read-only"', project_file.read_text())
            self.assertTrue((root / "manifests").is_dir())
            # NDOS owns its own directories; it never creates a home for data.
            self.assertFalse((root / "raw_data").exists())

    def test_init_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            initialize(root)

            with self.assertRaises(FileExistsError):
                initialize(root)

            self.assertTrue(initialize(root, force=True).is_file())

    def test_project_id_is_slugified_from_the_directory_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "My Study (2026)!"
            content = initialize(root).read_text()
            self.assertIn('id = "my-study-2026"', content)


if __name__ == "__main__":
    unittest.main()
