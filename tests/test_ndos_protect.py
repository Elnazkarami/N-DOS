"""Tests for making raw data read-only.

The standard asks that raw data be "set as read-only after acquisition". A
recording is the one thing in a project that cannot be regenerated, and it is
usually lost to a script writing where it should have been reading.
"""

import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ndos_protect import apply_protection, survey


def _project(base: Path) -> Path:
    root = base / "study"
    session = root / "raw_data" / "M123" / "20250314"
    session.mkdir(parents=True)
    (session / "M123_20250314_raw.dat").write_bytes(b"irreplaceable")
    (session / "M123_20250314_video.avi").write_bytes(b"video")
    processed = root / "processed_data" / "M123" / "20250314"
    processed.mkdir(parents=True)
    (processed / "spikes.csv").write_text("sorted", encoding="utf-8")
    return root


class SurveyTests(unittest.TestCase):
    def test_it_reports_what_is_still_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))
            state = survey(root)

            self.assertEqual(state["file_count"], 2)
            self.assertEqual(state["writable_count"], 2)
            self.assertEqual(state["protected_count"], 0)

    def test_only_the_named_directories_are_covered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))
            # processed_data is expected to change; raw_data is not.
            self.assertEqual(survey(root)["file_count"], 2)
            self.assertEqual(
                survey(root, targets=("processed_data",))["file_count"], 1
            )


class ProtectionTests(unittest.TestCase):
    def test_protected_files_cannot_be_written(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))
            target = root / "raw_data" / "M123" / "20250314" / "M123_20250314_raw.dat"

            apply_protection(root)

            self.assertFalse(bool(target.stat().st_mode & stat.S_IWUSR))
            with self.assertRaises(PermissionError):
                target.open("w")
            # And the recording is still exactly what it was.
            self.assertEqual(target.read_bytes(), b"irreplaceable")

    def test_contents_are_never_altered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))
            before = {
                path: path.read_bytes()
                for path in root.rglob("*") if path.is_file()
            }

            apply_protection(root)

            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)

    def test_processed_data_is_left_writable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))
            apply_protection(root)

            spikes = root / "processed_data" / "M123" / "20250314" / "spikes.csv"
            self.assertTrue(bool(spikes.stat().st_mode & stat.S_IWUSR))

    def test_releasing_gives_write_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))
            target = root / "raw_data" / "M123" / "20250314" / "M123_20250314_raw.dat"
            apply_protection(root)

            apply_protection(root, release=True)

            self.assertTrue(bool(target.stat().st_mode & stat.S_IWUSR))
            target.write_bytes(b"now allowed")

    def test_protecting_twice_changes_nothing_the_second_time(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))

            first = apply_protection(root)
            second = apply_protection(root)

            self.assertEqual(first["changed_count"], 2)
            self.assertEqual(second["changed_count"], 0)

    def test_a_survey_after_protecting_reports_it_as_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))
            apply_protection(root)

            state = survey(root)

            # This is what --check reads to decide its exit code.
            self.assertEqual(state["writable_count"], 0)
            self.assertEqual(state["protected_count"], 2)

    def test_a_file_that_becomes_writable_again_is_noticed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _project(Path(directory))
            apply_protection(root)
            target = root / "raw_data" / "M123" / "20250314" / "M123_20250314_raw.dat"
            target.chmod(target.stat().st_mode | stat.S_IWUSR)

            state = survey(root)

            self.assertEqual(state["writable_count"], 1)
            # resolve(): on macOS /var is itself a symlink to /private/var.
            self.assertIn(str(target.resolve()), state["writable"])

    def test_links_are_left_alone(self):
        # A layout built by organize is links; the permission that matters
        # belongs to the original, which may not be ours to change.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = _project(base)
            real = base / "elsewhere.dat"
            real.write_bytes(b"original")
            (root / "raw_data" / "M123" / "20250314" / "linked.dat").symlink_to(real)

            apply_protection(root)

            self.assertTrue(bool(real.stat().st_mode & stat.S_IWUSR))


if __name__ == "__main__":
    unittest.main()
