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
import ndos_validate
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

    def test_a_session_not_named_as_a_date_is_a_recommendation(self):
        # The manuscript says SessionID is "typically" a date. Some data
        # records a session without recording when it happened, and inventing
        # a date it does not have would be worse than keeping ses-01.
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(Path(directory))
            (root / "raw_data" / "M123" / "ses-01").mkdir(parents=True)

            result = validate(root)

            self.assertTrue(result["conforms"])
            self.assertIn("session-id-not-a-date", _codes(result, "recommendation"))

    def test_an_ambiguous_date_in_a_session_is_a_requirement_failure(self):
        # 03/04/2025 names two different days depending on the reader.
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(Path(directory))
            (root / "raw_data" / "M123" / "03.04.2025").mkdir(parents=True)

            result = validate(root)

            self.assertFalse(result["conforms"])
            self.assertIn("ambiguous-date", _codes(result, "requirement"))

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
        # No exemptions. `timestamps` was one for a while -- the code assigned
        # it and the specification did not list it -- which is the same gap
        # that let `imaging` and `histology` be unnameable while the Scope
        # section claimed both.
        for label, _, _ in ndos_organize.TYPE_RULES:
            self.assertIn(f"`{label}`", spec, f"{label} is not in the specification")

    def test_every_session_type_the_vocabulary_allows_can_name_a_file(self):
        """The Scope claims calcium imaging and histology; the types must too.

        A lab could declare a `calcium imaging` session and then find no
        `<type>` for the files in it, because the type list was entirely
        electrophysiology and behaviour.
        """
        import ndos_organize
        import ndos_table

        types = {label for label, _, _ in ndos_organize.TYPE_RULES}
        nameable = {
            "electrophysiology": {"raw", "lfp", "spikes"},
            "calcium imaging": {"imaging"},
            "behaviour": {"behavior", "task", "position", "video"},
            "histology": {"histology"},
        }
        for session_type, expected in nameable.items():
            self.assertIn(session_type, ndos_table.VOCABULARIES["session_type"])
            self.assertTrue(
                expected & types,
                f"a {session_type!r} session has no file type to name its data",
            )


class DuplicateSessionTests(unittest.TestCase):
    """Conformance rule 3: a SessionID is unique within its subject.

    The rule was stated in SPECIFICATION.md and not enforced: the checker
    collected session names into a dict and never read it back.
    """

    def _project(self, directory, *sessions):
        import ndos_init

        root = Path(directory) / "study"
        ndos_init.initialize(root)
        for name in sessions:
            session = root / "raw_data" / "M123" / name
            session.mkdir(parents=True)
            (session / f"M123_{name}_raw.dat").write_bytes(b"signal")
        return root

    def _codes(self, result):
        return {f["code"] for f in result["findings"]}

    def test_one_session_written_two_ways_is_a_requirement_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory, "20250314", "2025-03-14")
            result = ndos_validate.validate(root)

        self.assertIn("duplicate-session-id", self._codes(result))
        self.assertFalse(result["conforms"])

    def test_names_differing_only_by_case_collide(self):
        # Two directories here, one directory after a copy onto a
        # case-insensitive disk, which is where a recording goes missing.
        self.assertEqual(
            ndos_validate._canonical_session("Ses-01"),
            ndos_validate._canonical_session("ses_01"),
        )

    def test_genuinely_different_sessions_are_left_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory, "20250314", "20250315")
            result = ndos_validate.validate(root)

        self.assertNotIn("duplicate-session-id", self._codes(result))

    def test_the_finding_names_both_spellings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._project(directory, "20250314", "2025-03-14")
            result = ndos_validate.validate(root)

        message = next(
            f["message"] for f in result["findings"]
            if f["code"] == "duplicate-session-id"
        )
        self.assertIn("20250314", message)
        self.assertIn("2025-03-14", message)


if __name__ == "__main__":
    unittest.main()
