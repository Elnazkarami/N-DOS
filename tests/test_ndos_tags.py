"""Tests for validated / temp / deletable flags.

The flags exist so that "is this checked?" and "can I free this space?" have
answers. Since one of those answers leads to deletion, the guards around it
carry most of the weight here.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ndos_tags
from ndos_tags import (
    TAGS_FILE,
    TagError,
    apply_sweep,
    collect,
    get_tags,
    looks_temporary,
    plan_sweep,
    select,
    set_tags,
)


def _file(base: Path, relative: str, content: str = "data") -> Path:
    path = base / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class SetAndGetTests(unittest.TestCase):
    def test_flags_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = _file(base, "spikes.npy")

            set_tags(target, {"validated": True}, note="curated", author="elnaz")
            entry = get_tags(target)

            self.assertTrue(entry["validated"])
            self.assertEqual(entry["note"], "curated")
            self.assertEqual(entry["author"], "elnaz")

    def test_tags_live_beside_the_data_they_describe(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = _file(base, "session/spikes.npy")

            set_tags(target, {"validated": True})

            # So a session directory stays self-describing when it is moved.
            self.assertTrue((base / "session" / TAGS_FILE).is_file())

    def test_flags_can_be_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _file(Path(directory), "a.npy")
            set_tags(target, {"temp": True})
            self.assertTrue(get_tags(target)["temp"])

            set_tags(target, {"temp": False})
            self.assertFalse(get_tags(target)["temp"])

    def test_an_unknown_flag_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _file(Path(directory), "a.npy")
            with self.assertRaises(TagError) as caught:
                set_tags(target, {"publishable": True})
            self.assertIn("Known flags", str(caught.exception))

    def test_tagging_a_missing_file_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(TagError):
                set_tags(Path(directory) / "nope.npy", {"validated": True})

    def test_validated_and_deletable_together_is_flagged_as_a_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _file(Path(directory), "a.npy")
            entry = set_tags(target, {"validated": True, "deletable": True})
            self.assertIn("conflict", entry)

    def test_multiple_files_share_one_tags_file(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            first = _file(base, "s/a.npy")
            second = _file(base, "s/b.npy")

            set_tags(first, {"validated": True})
            set_tags(second, {"temp": True})

            content = json.loads((base / "s" / TAGS_FILE).read_text(encoding="utf-8"))
            self.assertEqual(sorted(content["files"]), ["a.npy", "b.npy"])


class TemporaryDetectionTests(unittest.TestCase):
    def test_a_temp_directory_marks_its_contents(self):
        self.assertTrue(looks_temporary(Path("s/temp/x.dat")))
        self.assertTrue(looks_temporary(Path("s/phy_output/x.npy")))

    def test_known_scratch_filenames_are_recognised(self):
        self.assertTrue(looks_temporary(Path("s/temp_wh.dat")))

    def test_ordinary_data_is_not_temporary(self):
        self.assertFalse(looks_temporary(Path("s/lfp.npy")))
        self.assertFalse(looks_temporary(Path("s/recording.dat")))

    def test_directories_above_the_project_are_ignored(self):
        # A project living under /tmp must not have every file called scratch.
        path = Path("/tmp/project/raw_data/M01/lfp.npy")
        self.assertTrue(looks_temporary(path))
        self.assertFalse(looks_temporary(path, root=Path("/tmp/project")))

    def test_inferred_temporariness_is_marked_as_inferred(self):
        with tempfile.TemporaryDirectory() as directory:
            target = _file(Path(directory), "s/temp/x.dat")
            entry = get_tags(target)
            self.assertTrue(entry["temp"])
            # Nobody declared this; the tool guessed from the path.
            self.assertTrue(entry["temp_inferred"])


class CollectionTests(unittest.TestCase):
    def _project(self, base: Path):
        good = _file(base, "processed_data/M01/20250314/spikes.npy")
        scratch = _file(base, "processed_data/M01/20250314/temp/temp_wh.dat")
        set_tags(good, {"validated": True})
        set_tags(scratch, {"temp": True, "deletable": True})
        return good, scratch

    def test_tagged_files_are_found_across_a_project(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._project(base)
            self.assertEqual(len(collect(base)), 2)

    def test_selecting_by_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._project(base)
            entries = collect(base)

            validated = select(entries, flag="validated")
            self.assertEqual([Path(e["path"]).name for e in validated], ["spikes.npy"])

            temp = select(entries, flag="temp")
            self.assertEqual([Path(e["path"]).name for e in temp], ["temp_wh.dat"])

    def test_a_tagged_file_that_has_since_vanished_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            good, _ = self._project(base)
            good.unlink()

            missing = [e for e in collect(base) if not e["exists"]]
            self.assertEqual(len(missing), 1)


class SweepTests(unittest.TestCase):
    """Deletion is irreversible, so these are the important ones."""

    def _project(self, base: Path):
        keep = _file(base, "s/lfp.npy")
        scratch = _file(base, "s/temp/temp_wh.dat", "x" * 100)
        set_tags(keep, {"validated": True})
        set_tags(scratch, {"temp": True})
        return keep, scratch

    def test_a_sweep_plan_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            keep, scratch = self._project(base)

            plan = plan_sweep(base)

            self.assertTrue(keep.is_file())
            self.assertTrue(scratch.is_file())
            self.assertEqual(len(plan["removable"]), 1)
            self.assertEqual(plan["removable_bytes"], 100)

    def test_validated_files_are_never_swept(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            target = _file(base, "s/a.npy")
            # Contradictory flags: validated must win.
            set_tags(target, {"validated": True, "temp": True, "deletable": True})

            plan = plan_sweep(base)

            self.assertEqual(plan["removable"], [])
            self.assertEqual(len(plan["withheld"]), 1)
            apply_sweep(plan)
            self.assertTrue(target.is_file())

    def test_untagged_scratch_is_listed_separately_and_only_on_request(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _file(base, "s/temp/never_declared.dat")

            self.assertEqual(plan_sweep(base)["inferred"], [])
            opted_in = plan_sweep(base, include_inferred=True)
            self.assertEqual(len(opted_in["inferred"]), 1)

    def test_applying_a_sweep_removes_exactly_what_was_listed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            keep, scratch = self._project(base)

            result = apply_sweep(plan_sweep(base))

            self.assertEqual(result["removed_count"], 1)
            self.assertFalse(scratch.exists())
            self.assertTrue(keep.is_file())

    def test_inferred_files_are_not_removed_unless_included(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            guessed = _file(base, "s/temp/never_declared.dat")
            plan = plan_sweep(base, include_inferred=True)

            apply_sweep(plan, include_inferred=False)
            self.assertTrue(guessed.is_file())

            apply_sweep(plan, include_inferred=True)
            self.assertFalse(guessed.exists())


class OrganizeIntegrationTests(unittest.TestCase):
    def test_scratch_is_routed_tagged_and_then_findable_by_a_sweep(self):
        import ndos_organize

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _file(base, "src/M01/2025_03_14/temp/temp_wh.dat", "y" * 50)
            _file(base, "src/M01/2025_03_14/processed/spikes.npy")
            manifest = __import__("ndos_scan").scan(
                base / "src", include_checksums=False, progress=False
            )
            project = base / "project"

            ndos_organize.apply_plan(
                ndos_organize.build_plan(manifest, project), progress=False
            )

            scratch = project / "processed_data" / "M01" / "20250314" / "temp"
            self.assertTrue(scratch.is_dir())
            # Tagged where it landed, without anyone remembering to do it.
            plan = plan_sweep(project)
            self.assertEqual(len(plan["removable"]), 1)
            self.assertIn("temp", plan["removable"][0]["relative"])

    def test_a_processed_session_records_how_it_was_derived(self):
        import ndos_organize

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _file(base, "src/M01/2025_03_14/processed/spikes_v2.npy")
            manifest = __import__("ndos_scan").scan(
                base / "src", include_checksums=False, progress=False
            )
            project = base / "project"

            ndos_organize.apply_plan(
                ndos_organize.build_plan(manifest, project), progress=False
            )

            record = json.loads(
                (project / "processed_data" / "M01" / "20250314"
                 / "derived_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(record["subject_id"], "M01")
            self.assertTrue(record["files"][0]["why"])
            # The version marker survived renaming.
            self.assertIn("_v2", record["files"][0]["name"])


if __name__ == "__main__":
    unittest.main()


class ValidatedIndexTests(unittest.TestCase):
    """The reference index the standard asks each project to carry.

    "A table listing validated, high-quality data files — effectively a
    reference index for automated pipelines." An analysis should read this
    rather than globbing a directory and hoping.
    """

    def _project(self, base: Path):
        good = _file(base, "processed_data/M123/20250314/spikes.csv", "sorted")
        draft = _file(base, "processed_data/M123/20250314/attempt.csv", "maybe")
        scratch = _file(base, "processed_data/M123/20250314/temp/temp_wh.dat", "x")
        set_tags(good, {"validated": True}, note="curated in Phy", author="elnaz")
        set_tags(scratch, {"validated": True, "temp": True})
        return good, draft, scratch

    def test_only_validated_files_are_listed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._project(base)

            rows = ndos_tags.build_index(base)

            self.assertEqual([row["path"] for row in rows],
                             ["processed_data/M123/20250314/spikes.csv"])

    def test_scratch_is_excluded_even_when_marked_validated(self):
        # Validated and temporary at once is not something to build on.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._project(base)
            rows = ndos_tags.build_index(base)
            self.assertFalse(any("temp" in row["path"] for row in rows))

    def test_the_index_carries_who_validated_it_and_when(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._project(base)

            row = ndos_tags.build_index(base)[0]

            self.assertEqual(row["validated_by"], "elnaz")
            self.assertEqual(row["note"], "curated in Phy")
            self.assertTrue(row["validated_at"])

    def test_index_paths_use_posix_separators_everywhere(self):
        # The index is loaded by pipelines and shared between machines; a
        # backslash path is unusable off the machine that wrote it.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._project(base)
            for row in ndos_tags.build_index(base):
                self.assertNotIn("\\", row["path"])
                self.assertIn("/", row["path"])

    def test_the_index_breaks_the_path_into_role_subject_session(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self._project(base)

            row = ndos_tags.build_index(base)[0]

            self.assertEqual(row["role"], "processed_data")
            self.assertEqual(row["subject"], "M123")
            self.assertEqual(row["session"], "20250314")

    def test_a_validated_file_that_has_since_vanished_is_not_listed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            good, _, _ = self._project(base)
            good.unlink()

            self.assertEqual(ndos_tags.build_index(base), [])

    def test_a_project_with_nothing_validated_yields_an_empty_index(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            _file(base, "processed_data/M123/20250314/spikes.csv")
            self.assertEqual(ndos_tags.build_index(base), [])
