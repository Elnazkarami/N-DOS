"""Tests for checking a project against the standard.

The point of a written standard is that a lab can tell whether they are
following it, so what matters here is that requirements and recommendations
stay separate and that the exit code means what it says.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ndos_init
from ndos_validate import REQUIRED_DIRECTORIES, SPEC_VERSION, validate


def _codes(result, level=None):
    return {
        finding["code"] for finding in result["findings"]
        if level is None or finding["level"] == level
    }


class StructureTests(unittest.TestCase):
    def test_a_project_made_by_init_conforms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            ndos_init.initialize(root)

            result = validate(root)

            self.assertTrue(result["conforms"])
            self.assertEqual(_codes(result, "requirement"), set())

    def test_missing_directories_are_a_requirement_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            (root / "raw_data").mkdir(parents=True)

            result = validate(root)

            self.assertFalse(result["conforms"])
            self.assertIn("missing-directories", _codes(result, "requirement"))
            self.assertIn("missing-readme", _codes(result, "requirement"))

    def test_the_checker_and_the_creator_agree_on_the_directories(self):
        # If these ever diverge, init would build something validate rejects.
        self.assertEqual(
            set(REQUIRED_DIRECTORIES),
            {name for name, _ in ndos_init.DIRECTORIES},
        )


class SessionTests(unittest.TestCase):
    def _project(self, base: Path) -> Path:
        root = base / "study"
        ndos_init.initialize(root)
        return root

    def test_a_badly_named_session_is_a_requirement_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(Path(directory))
            (root / "raw_data" / "M123" / "March14").mkdir(parents=True)

            result = validate(root)

            self.assertFalse(result["conforms"])
            self.assertIn("session-id-format", _codes(result, "requirement"))

    def test_both_session_id_forms_are_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(Path(directory))
            (root / "raw_data" / "M123" / "20250314").mkdir(parents=True)
            (root / "raw_data" / "M123" / "20250314_02").mkdir(parents=True)

            self.assertTrue(validate(root)["conforms"])

    def test_data_loose_in_raw_data_is_a_requirement_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(Path(directory))
            (root / "raw_data" / "stray.dat").write_bytes(b"x")

            result = validate(root)

            self.assertFalse(result["conforms"])
            self.assertIn("data-outside-a-session", _codes(result, "requirement"))

    def test_data_directly_under_a_subject_is_a_requirement_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(Path(directory))
            subject = root / "raw_data" / "M123"
            subject.mkdir(parents=True)
            (subject / "recording.dat").write_bytes(b"x")

            self.assertFalse(validate(root)["conforms"])

    def test_subjects_and_sessions_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(Path(directory))
            for subject in ("M123", "M124"):
                (root / "raw_data" / subject / "20250314").mkdir(parents=True)

            result = validate(root)

            self.assertEqual(result["subject_count"], 2)
            self.assertEqual(result["session_count"], 2)


class RecommendationTests(unittest.TestCase):
    """Recommendations never decide whether a project conforms."""

    def test_writable_raw_data_is_a_recommendation_not_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            ndos_init.initialize(root)
            session = root / "raw_data" / "M123" / "20250314"
            session.mkdir(parents=True)
            (session / "M123_20250314_raw.dat").write_bytes(b"x")

            result = validate(root)

            self.assertTrue(result["conforms"])
            self.assertIn("raw-data-writable", _codes(result, "recommendation"))

    def test_unconventional_filenames_are_a_recommendation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            ndos_init.initialize(root)
            session = root / "raw_data" / "M123" / "20250314"
            session.mkdir(parents=True)
            (session / "recording.dat").write_bytes(b"x")

            result = validate(root)

            self.assertTrue(result["conforms"])
            self.assertIn("file-naming", _codes(result, "recommendation"))

    def test_every_finding_says_how_to_fix_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            (root / "raw_data" / "M123" / "nope").mkdir(parents=True)

            for finding in validate(root)["findings"]:
                self.assertTrue(finding["fix"], finding["message"])

    def test_the_result_names_the_specification_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study"
            ndos_init.initialize(root)
            self.assertEqual(validate(root)["spec_version"], SPEC_VERSION)


class SpecificationTests(unittest.TestCase):
    def test_the_specification_exists_and_states_its_version(self):
        spec = Path(__file__).resolve().parent.parent / "SPECIFICATION.md"
        self.assertTrue(spec.is_file())
        text = spec.read_text(encoding="utf-8")
        self.assertIn(f"Version {SPEC_VERSION}", text)

    def test_every_required_directory_appears_in_the_specification(self):
        spec = (
            Path(__file__).resolve().parent.parent / "SPECIFICATION.md"
        ).read_text(encoding="utf-8")
        for name in REQUIRED_DIRECTORIES:
            self.assertIn(f"`{name}/`", spec, f"{name} is not in the specification")

    def test_the_specification_documents_every_data_type_the_code_knows(self):
        import ndos_organize

        spec = (
            Path(__file__).resolve().parent.parent / "SPECIFICATION.md"
        ).read_text(encoding="utf-8")
        standard = {label for label, _, _ in ndos_organize.TYPE_RULES}
        # timestamps is an implementation fallback, not one of the eight the
        # manuscript names.
        for label in standard - {"timestamps"}:
            self.assertIn(f"`{label}`", spec, f"{label} is not in the specification")


if __name__ == "__main__":
    unittest.main()
