"""Tests for handing an N-DOS project to BIDS and NWB workflows.

NDOS prepares handoffs rather than reimplementing either standard, so what
matters here is that entities map correctly and that missing prerequisites are
reported rather than papered over.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ndos_convert import (
    _parse_name,
    plan_bids,
    plan_nwb,
    read_project,
    write_bids,
)


def _project(base: Path, files) -> Path:
    root = base / "project"
    for relative in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data", encoding="utf-8")
    return root


class ParsingTests(unittest.TestCase):
    def test_a_standard_name_splits_into_its_parts(self):
        self.assertEqual(
            _parse_name("A0634_20201122_video.avi"), ("A0634", "20201122", "video", "")
        )

    def test_a_discriminator_is_kept_separate_from_the_type(self):
        # "video-0" is a video; reading it as a type dropped 38 of 44 files.
        self.assertEqual(
            _parse_name("A0634_20201122_video-0.avi"),
            ("A0634", "20201122", "video", "0"),
        )

    def test_dots_inside_the_original_name_do_not_break_the_split(self):
        subject, session, data_type, acquisition = _parse_name(
            "A0634_20201122_position-Take-2020-11-22-06.32.30-PM.csv"
        )
        self.assertEqual((subject, session, data_type), ("A0634", "20201122", "position"))
        self.assertTrue(acquisition.startswith("Take"))


class BidsTests(unittest.TestCase):
    def _plan(self, base: Path, metadata=None):
        root = _project(
            base,
            [
                "raw_data/A0634/20201122/A0634_20201122_video-0.avi",
                "raw_data/A0634/20201122/A0634_20201122_raw-info.rhd",
                "processed_data/A0634/20201122/temp/A0634_20201122_temp_wh.dat",
            ],
        )
        return root, plan_bids(read_project(root), base / "bids", metadata or {})

    def test_entities_map_onto_bids_names(self):
        with tempfile.TemporaryDirectory() as directory:
            _, plan = self._plan(Path(directory))
            targets = sorted(Path(a["target"]).name for a in plan["actions"])
            self.assertEqual(
                targets,
                [
                    "sub-A0634_ses-20201122_acq-0_video.avi",
                    "sub-A0634_ses-20201122_acq-info_raw.rhd",
                ],
            )

    def test_datatype_directories_follow_bids(self):
        with tempfile.TemporaryDirectory() as directory:
            _, plan = self._plan(Path(directory))
            datatypes = {a["datatype"] for a in plan["actions"]}
            self.assertEqual(datatypes, {"beh", "ephys"})

    def test_scratch_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            _, plan = self._plan(Path(directory))
            # temp/ holds intermediates; they have no place in an export.
            self.assertFalse(any("temp" in a["source"] for a in plan["actions"]))

    def test_the_export_states_that_it_is_not_validated_bids(self):
        with tempfile.TemporaryDirectory() as directory:
            _, plan = self._plan(Path(directory))
            self.assertIn("not validated BIDS", plan["conformance"])
            self.assertIn("BEP032", plan["conformance"])

    def test_writing_produces_the_files_bids_requires(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, plan = self._plan(base)

            write_bids(plan, root)

            destination = base / "bids"
            self.assertTrue((destination / "dataset_description.json").is_file())
            self.assertTrue((destination / "participants.tsv").is_file())
            description = json.loads(
                (destination / "dataset_description.json").read_text(encoding="utf-8")
            )
            self.assertIn("BIDSVersion", description)

    def test_unrecorded_participant_values_are_written_as_na(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, plan = self._plan(base)
            write_bids(plan, root)

            rows = (base / "bids" / "participants.tsv").read_text(
                encoding="utf-8"
            ).splitlines()

            self.assertTrue(rows[1].startswith("sub-A0634"))
            self.assertIn("n/a", rows[1])

    def test_declared_metadata_reaches_participants_tsv(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, plan = self._plan(
                base, {"A0634": {"species": "mus musculus", "sex": "F"}}
            )
            write_bids(plan, root)

            rows = (base / "bids" / "participants.tsv").read_text(
                encoding="utf-8"
            ).splitlines()

            self.assertIn("mus musculus", rows[1])
            self.assertIn("F", rows[1])

    def test_exported_files_are_links_to_the_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, plan = self._plan(base)
            write_bids(plan, root)

            links = [
                p for p in (base / "bids").rglob("*")
                if p.is_symlink()
            ]
            self.assertTrue(links)
            self.assertTrue(links[0].resolve().is_file())


class NwbTests(unittest.TestCase):
    def _project_with(self, base: Path):
        root = _project(
            base, ["raw_data/A0634/20201122_143000/A0634_20201122_raw-info.rhd"]
        )
        return read_project(root)

    def test_a_plan_maps_metadata_onto_nwb_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self._project_with(Path(directory))
            plan = plan_nwb(
                project,
                {"A0634": {"species": "mus musculus", "sex": "F",
                           "date_of_birth": "2020-01-01"}},
            )

            conversion = plan["conversions"][0]
            self.assertEqual(conversion["subject"]["species"], "mus musculus")
            self.assertEqual(conversion["nwbfile"]["session_id"], "20201122_143000")
            self.assertEqual(conversion["missing_required"], [])

    def test_the_session_start_time_is_derived_from_the_session_id(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self._project_with(Path(directory))
            plan = plan_nwb(project, {})
            self.assertEqual(
                plan["conversions"][0]["nwbfile"]["session_start_time"],
                "2020-11-22T14:30:00",
            )

    def test_missing_prerequisites_are_reported_not_invented(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self._project_with(Path(directory))
            plan = plan_nwb(project, {})

            missing = plan["conversions"][0]["missing_required"]
            self.assertIn("species", missing)
            self.assertIn("sex", missing)
            self.assertTrue(plan["missing_required"])

    def test_the_plan_says_it_is_a_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = plan_nwb(self._project_with(Path(directory)), {})
            self.assertIn("NeuroConv", plan["note"])


if __name__ == "__main__":
    unittest.main()
