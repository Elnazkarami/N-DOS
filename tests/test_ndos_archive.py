"""Tests for reading archives without extracting them.

Two properties matter most: nothing is ever written without a reviewed plan
and a confirmation, and a member whose name would escape the destination is
refused outright.
"""

import json
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

import ndos_archive
from make_messy_lab import ARCHIVE_PATH, build
from ndos_archive import (
    apply_extraction,
    composition,
    find_archives,
    inspect,
    inspect_archive,
    plan_extraction,
    search,
)


def _make_zip(path: Path, members) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members:
            archive.writestr(name, content)
    return path


class DiscoveryTests(unittest.TestCase):
    def test_archives_are_found_recursively(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(base / "a.zip", [("x.txt", "x")])
            _make_zip(base / "deep" / "b.zip", [("y.txt", "y")])
            (base / "not-an-archive.txt").write_text("plain", encoding="utf-8")

            found = {path.name for path in find_archives(base)}

            self.assertEqual(found, {"a.zip", "b.zip"})

    def test_resource_forks_are_not_mistaken_for_archives(self):
        # A real drive had `._session.zip` beside `session.zip`; opening it
        # only wastes a slow read to report a failure.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(base / "session.zip", [("x.txt", "x")])
            (base / "._session.zip").write_bytes(b"\x00\x05\x16\x07not a zip")

            found = [path.name for path in find_archives(base)]

            self.assertEqual(found, ["session.zip"])

    def test_tar_archives_are_excluded_unless_asked_for(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            payload = base / "payload.txt"
            payload.write_text("data", encoding="utf-8")
            with tarfile.open(base / "bundle.tar.gz", "w:gz") as archive:
                archive.add(payload, arcname="payload.txt")
            payload.unlink()

            # Streaming a tar end to end is expensive, so it is opt-in.
            self.assertEqual(inspect(base, progress=False)["archive_count"], 0)
            with_tar = inspect(base, include_tar=True, progress=False)
            self.assertEqual(with_tar["archive_count"], 1)
            self.assertEqual(with_tar["member_count"], 1)


class InspectionTests(unittest.TestCase):
    def test_members_are_listed_without_extracting(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            archive = _make_zip(
                base / "s.zip",
                [("ses/0.avi", "a" * 500), ("ses/notes.csv", "b" * 40)],
            )

            entry = inspect_archive(archive)

            self.assertEqual(entry["member_count"], 2)
            self.assertEqual(entry["uncompressed_bytes"], 540)
            self.assertEqual(len(entry["members"][0]["crc32"]), 8)
            # Nothing appeared on disk beside the archive.
            self.assertEqual(
                sorted(p.name for p in base.iterdir()), ["s.zip"]
            )

    def test_archive_clutter_is_not_catalogued(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = _make_zip(
                Path(directory) / "s.zip",
                [
                    ("ses/0.avi", "a"),
                    ("__MACOSX/ses/._0.avi", "junk"),
                    ("ses/.DS_Store", "junk"),
                ],
            )

            entry = inspect_archive(archive)

            self.assertEqual([m["name"] for m in entry["members"]], ["ses/0.avi"])

    def test_a_corrupt_archive_is_recorded_not_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / "broken.zip"
            broken.write_bytes(b"this is not a zip file at all")

            entry = inspect_archive(broken)

            self.assertIn("error", entry)
            self.assertEqual(entry["member_count"], 0)

    def test_a_catalogue_is_reused_when_the_archive_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(base / "s.zip", [("a.txt", "a")])
            cache = base / "cat.json"

            first = inspect(base, cache_path=cache, progress=False)
            second = inspect(base, cache_path=cache, progress=False)

            self.assertEqual(first["reused_from_cache"], 0)
            # Re-reading a 2 GB archive on a slow drive costs a minute; the
            # cache is what makes repeated runs usable.
            self.assertEqual(second["reused_from_cache"], 1)

    def test_a_changed_archive_is_re_read(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            path = _make_zip(base / "s.zip", [("a.txt", "a")])
            cache = base / "cat.json"
            inspect(base, cache_path=cache, progress=False)

            _make_zip(path, [("a.txt", "a"), ("b.txt", "b")])
            again = inspect(base, cache_path=cache, progress=False)

            self.assertEqual(again["reused_from_cache"], 0)
            self.assertEqual(again["member_count"], 2)

    def test_contents_are_grouped_the_way_files_on_disk_are(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(
                base / "s.zip",
                [("a.avi", "x" * 100), ("t.tak", "y" * 200), ("n.csv", "z" * 10)],
            )
            rows = {
                row["category"]: row for row in composition(
                    inspect(base, progress=False)
                )
            }

            self.assertIn("Imaging and video", rows)
            # OptiTrack takes were 81% of one real lab's archived data.
            self.assertIn("Motion capture and tracking", rows)
            self.assertIn("Tabular and behavioural", rows)


class SearchTests(unittest.TestCase):
    def _catalogue(self, base: Path):
        _make_zip(
            base / "one.zip",
            [("ses/0.avi", "a" * 10), ("ses/notes.csv", "b" * 10)],
        )
        _make_zip(base / "two.zip", [("ses/1.avi", "c" * 10)])
        return inspect(base, progress=False)

    def test_a_glob_finds_members_across_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            catalogue = self._catalogue(Path(directory))
            hits = search(catalogue, "*.avi")
            self.assertEqual(len(hits), 2)
            self.assertEqual({Path(h["archive"]).name for h in hits}, {"one.zip", "two.zip"})

    def test_a_plain_substring_also_works(self):
        with tempfile.TemporaryDirectory() as directory:
            catalogue = self._catalogue(Path(directory))
            self.assertEqual(len(search(catalogue, "notes")), 1)

    def test_searching_by_category(self):
        with tempfile.TemporaryDirectory() as directory:
            catalogue = self._catalogue(Path(directory))
            hits = search(catalogue, "*", category="Tabular and behavioural")
            self.assertEqual([Path(h["name"]).name for h in hits], ["notes.csv"])


class ExtractionSafetyTests(unittest.TestCase):
    """Extraction writes data, so every guard here is load-bearing."""

    def test_a_member_escaping_the_destination_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(
                base / "evil.zip",
                [("../../escaped.txt", "no"), ("fine.txt", "yes")],
            )
            catalogue = inspect(base, progress=False)

            plan = plan_extraction(catalogue, base / "out")

            self.assertEqual(len(plan["rejected"]), 1)
            self.assertIn("escapes", plan["rejected"][0]["reason"])
            self.assertEqual([a["member"] for a in plan["actions"]], ["fine.txt"])

    def test_planning_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(base / "s.zip", [("a.txt", "a")])
            catalogue = inspect(base, progress=False)
            destination = base / "out"

            plan_extraction(catalogue, destination)

            self.assertFalse(destination.exists())

    def test_extraction_writes_only_the_planned_members(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(
                base / "s.zip",
                [("ses/0.avi", "a" * 10), ("ses/notes.csv", "b" * 10)],
            )
            catalogue = inspect(base, progress=False)
            destination = base / "out"

            plan = plan_extraction(catalogue, destination, pattern="*.avi")
            result = apply_extraction(plan, progress=False)

            self.assertEqual(result["written_count"], 1)
            written = [p for p in destination.rglob("*") if p.is_file()]
            self.assertEqual([p.name for p in written], ["0.avi"])
            # Internal structure is preserved.
            self.assertTrue((destination / "ses" / "0.avi").is_file())

    def test_existing_files_are_skipped_unless_overwrite_is_given(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(base / "s.zip", [("a.txt", "fresh")])
            catalogue = inspect(base, progress=False)
            destination = base / "out"
            destination.mkdir()
            (destination / "a.txt").write_text("precious", encoding="utf-8")

            plan = plan_extraction(catalogue, destination)
            result = apply_extraction(plan, progress=False)

            self.assertEqual(result["written_count"], 0)
            self.assertEqual(len(result["skipped"]), 1)
            self.assertEqual(
                (destination / "a.txt").read_text(encoding="utf-8"), "precious"
            )

            result = apply_extraction(plan, overwrite=True, progress=False)
            self.assertEqual(result["written_count"], 1)
            self.assertEqual(
                (destination / "a.txt").read_text(encoding="utf-8"), "fresh"
            )

    def test_a_plan_reports_what_it_would_cost(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _make_zip(base / "s.zip", [("a.txt", "x" * 1000)])
            catalogue = inspect(base, progress=False)

            plan = plan_extraction(catalogue, base / "out")

            self.assertEqual(plan["bytes_to_write"], 1000)
            self.assertIsNotNone(plan["free_bytes"])
            self.assertTrue(plan["enough_space"])


class FixtureTests(unittest.TestCase):
    def test_the_bundled_fixture_contains_a_readable_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = build(Path(directory) / "lab", force=True)

            entry = inspect_archive(root / ARCHIVE_PATH)

            self.assertNotIn("error", entry)
            self.assertEqual(entry["member_count"], 4)
            names = {Path(m["name"]).name for m in entry["members"]}
            self.assertIn("0.avi", names)
            self.assertIn("metaData.json", names)


if __name__ == "__main__":
    unittest.main()
