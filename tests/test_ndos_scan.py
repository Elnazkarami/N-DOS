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


class EstimateTests(unittest.TestCase):
    """Knowing a scan will take three hours is worth a few seconds of reading."""

    def _data(self, base: Path, count: int = 4, size: int = 200_000):
        for index in range(count):
            (base / f"rec{index}.bin").write_bytes(bytes(size))
        return base

    def test_an_estimate_measures_rather_than_guesses(self):
        from ndos_scan import estimate

        with tempfile.TemporaryDirectory() as directory:
            root = self._data(Path(directory))
            measured = estimate(root, sample_bytes=100_000)

            self.assertEqual(measured["file_count"], 4)
            self.assertEqual(measured["total_bytes"], 800_000)
            self.assertGreater(measured["bytes_per_second"], 0)
            self.assertIsNotNone(measured["seconds"])

    def test_an_estimate_discounts_what_is_already_cached(self):
        from ndos_scan import estimate

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            data = base / "data"
            data.mkdir()
            root = self._data(data)
            cache = base / "cache.json"

            scan(root, cache_path=cache)
            measured = estimate(root, sample_bytes=100_000, cache_path=cache)

            # Everything is cached, so nothing remains to read.
            self.assertEqual(measured["remaining_bytes"], 0)
            self.assertEqual(measured["cached_count"], 4)

    def test_durations_are_rendered_in_units_a_person_can_act_on(self):
        from ndos_scan import _human_duration

        self.assertEqual(_human_duration(45), "45s")
        self.assertEqual(_human_duration(600), "10 min")
        self.assertEqual(_human_duration(11250), "3h 07m")


class CacheTests(unittest.TestCase):
    """A cache that returned a stale checksum would corrupt everything downstream."""

    def _data(self, base: Path):
        root = base / "data"
        root.mkdir()
        (root / "a.bin").write_bytes(b"alpha" * 1000)
        (root / "b.bin").write_bytes(b"beta" * 1000)
        return root

    def test_a_cached_scan_matches_an_uncached_one_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = self._data(base)

            fresh = scan(root)
            scan(root, cache_path=base / "cache.json")
            cached = scan(root, cache_path=base / "cache.json")

            self.assertEqual(
                {f["path"]: f["sha256"] for f in fresh["files"]},
                {f["path"]: f["sha256"] for f in cached["files"]},
            )

    def test_the_second_scan_reuses_what_the_first_computed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = self._data(base)
            cache = base / "cache.json"

            first = scan(root, cache_path=cache)
            second = scan(root, cache_path=cache)

            self.assertEqual(first["extensions"]["cache"]["reused"], 0)
            self.assertEqual(second["extensions"]["cache"]["reused"], 2)

    def test_a_changed_file_is_re_read_not_served_from_cache(self):
        import time

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = self._data(base)
            cache = base / "cache.json"
            scan(root, cache_path=cache)

            time.sleep(1.1)  # so the modification time genuinely differs
            (root / "a.bin").write_bytes(b"rewritten entirely")
            manifest = scan(root, cache_path=cache)

            digest = {f["path"]: f["sha256"] for f in manifest["files"]}["a.bin"]
            expected = hashlib.sha256(b"rewritten entirely").hexdigest()
            self.assertEqual(digest, expected)
            self.assertEqual(manifest["extensions"]["cache"]["reused"], 1)

    def test_a_file_of_the_same_size_but_different_mtime_is_re_read(self):
        import time

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "data"
            root.mkdir()
            (root / "a.bin").write_bytes(b"first")
            cache = base / "cache.json"
            scan(root, cache_path=cache)

            time.sleep(1.1)
            (root / "a.bin").write_bytes(b"secnd")  # same length, new contents
            manifest = scan(root, cache_path=cache)

            digest = {f["path"]: f["sha256"] for f in manifest["files"]}["a.bin"]
            self.assertEqual(digest, hashlib.sha256(b"secnd").hexdigest())

    def test_a_corrupt_cache_is_ignored_rather_than_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = self._data(base)
            cache = base / "cache.json"
            cache.write_text("{ not json at all", encoding="utf-8")

            manifest = scan(root, cache_path=cache)

            self.assertEqual(manifest["file_count"], 2)
            self.assertEqual(manifest["extensions"]["cache"]["reused"], 0)

    def test_a_cache_from_an_older_format_is_ignored(self):
        from ndos_scan import load_cache

        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.json"
            cache.write_text(
                json.dumps({"cache_version": "0.0", "entries": {"a": {}}}),
                encoding="utf-8",
            )
            self.assertEqual(load_cache(cache), {})

    def test_the_cache_is_written_atomically(self):
        from ndos_scan import save_cache

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            cache = base / "cache.json"
            save_cache(cache, base, {"a.bin": {"size_bytes": 1, "sha256": "x" * 64}})

            self.assertTrue(cache.is_file())
            # No temporary file survives a completed write.
            self.assertEqual(list(base.glob("*.tmp")), [])

    def test_scanning_without_a_cache_writes_no_cache_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = self._data(base)

            manifest = scan(root)

            self.assertNotIn("extensions", manifest)
            self.assertEqual(list(base.glob("*.json")), [])
