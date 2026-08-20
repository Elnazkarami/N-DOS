"""Tests for reconstructing the N-DOS layout from an existing directory.

The layout reproduced here is the one defined by the manuscript:
raw_data/<SubjectID>/<SessionID>/acquisition_files, with SessionID formatted
as YYYYMMDD or YYYYMMDD_SessionNumber.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

import ndos_scan
from make_messy_lab import build
from ndos_organize import (
    FLAGGED,
    RAW,
    SCAFFOLD,
    apply_plan,
    build_plan,
    derive,
    undo,
)


def _manifest(paths, root="/src", sizes=None):
    return {
        "source_root": root,
        "files": [
            {
                "path": path,
                "name": path.split("/")[-1],
                "extension": ("." + path.rsplit(".", 1)[1]) if "." in path.split("/")[-1] else "",
                "size_bytes": (sizes or {}).get(path, 100),
            }
            for path in paths
        ],
    }


class DerivationTests(unittest.TestCase):
    def test_subject_and_date_become_the_manuscript_layout(self):
        placements = derive(_manifest(["A0634/2020_11_22/0.avi"]))
        self.assertEqual(
            placements[0]["target"],
            "raw_data/A0634/20201122/A0634_20201122_video.avi",
        )
        # The original name is kept, so a placement can always be traced back.
        self.assertEqual(placements[0]["original_name"], "0.avi")

    def test_a_cohort_folder_above_the_subject_is_not_mistaken_for_it(self):
        # A0600/A0634 is a range containing an animal; the deeper one is the
        # subject.
        placements = derive(_manifest(["A0600/A0634/2020_11_22/0.avi"]))
        self.assertEqual(placements[0]["subject"], "A0634")
        self.assertIn("cohort", " ".join(placements[0]["why"]))

    def test_a_date_in_the_filename_is_used_when_folders_have_none(self):
        # Sessions archived as 2020_11_20.zip carry the date nowhere else.
        placements = derive(_manifest(["A0600/A0634/2020_11_20.zip"]))
        self.assertEqual(
            placements[0]["target"],
            "raw_data/A0634/20201120/A0634_20201120_raw.zip",
        )

    def test_a_compound_filename_yields_date_and_time(self):
        placements = derive(_manifest(["A0634/A0634_201122_183220/info.rhd"]))
        self.assertEqual(placements[0]["subject"], "A0634")
        self.assertEqual(placements[0]["session"], "20201122")

    def test_several_recordings_in_a_day_are_numbered(self):
        placements = derive(
            _manifest(
                [
                    "M01/2025_03_14/09_00_00/a.avi",
                    "M01/2025_03_14/14_30_00/b.avi",
                ]
            )
        )
        sessions = sorted(p["session"] for p in placements)
        # YYYYMMDD_SessionNumber, ordered by acquisition time.
        self.assertEqual(sessions, ["20250314_01", "20250314_02"])

    def test_a_single_recording_in_a_day_needs_no_number(self):
        placements = derive(_manifest(["M01/2025_03_14/09_00_00/a.avi"]))
        self.assertEqual(placements[0]["session"], "20250314")

    def test_explicit_session_folders_are_honoured(self):
        placements = derive(_manifest(["sub-01/ses-03/rec.dat"]))
        self.assertEqual(placements[0]["session"], "ses-03")

    def test_role_words_in_the_path_decide_where_a_file_goes(self):
        placements = derive(
            _manifest(
                [
                    "M01/2025_03_14/processed/spikes.npy",
                    "M01/2025_03_14/figures/fig1.png",
                    "M01/2025_03_14/scripts/run.py",
                ]
            )
        )
        directories = sorted(p["target"].split("/")[0] for p in placements)
        self.assertEqual(directories, ["figures", "processed_data", "scripts"])

    def test_files_without_a_subject_go_to_flagged_data_not_nowhere(self):
        # A recording with no identifiable subject. (A stray .txt would go to
        # metadata/, which needs no subject, so it would not exercise this.)
        placements = derive(_manifest(["random/thing.bin"]))
        self.assertTrue(placements[0]["target"].startswith(f"{FLAGGED}/"))
        self.assertFalse(placements[0]["placed"])
        # The original structure is preserved inside flagged_data.
        self.assertIn("random/thing.bin", placements[0]["target"])

    def test_every_placement_explains_itself(self):
        for placement in derive(_manifest(["A0634/2020_11_22/0.avi"])):
            self.assertTrue(placement["why"])


class NamingTests(unittest.TestCase):
    """The manuscript's SubjectID_SessionID_type filename conventions."""

    def _name(self, path):
        return Path(derive(_manifest([path]))[0]["target"]).name

    def test_data_types_follow_the_naming_conventions(self):
        self.assertEqual(self._name("M01/2025_03_14/0.avi"), "M01_20250314_video.avi")
        self.assertEqual(
            self._name("M01/2025_03_14/notes.csv"), "M01_20250314_experimenter.csv"
        )
        self.assertEqual(
            self._name("M01/2025_03_14/Take 01.tak"), "M01_20250314_position.tak"
        )
        self.assertEqual(self._name("M01/2025_03_14/info.rhd"), "M01_20250314_raw.rhd")

    def test_an_unrecognised_type_keeps_the_original_descriptor(self):
        # Better an unfamiliar label than a confident wrong one, since the
        # filename is what everyone reads first.
        name = self._name("M01/2025_03_14/analogin.dat")
        self.assertEqual(name, "M01_20250314_analogin.dat")

    def test_a_dataset_level_folder_does_not_decide_a_file_far_below_it(self):
        # A top folder called "miniscope" once made an Intan .dat a "video".
        name = self._name("miniscope/M01/2025_03_14/ephys/amp/analogin.dat")
        self.assertNotIn("video", name)

    def test_files_sharing_a_type_are_distinguished_by_their_original_name(self):
        placements = derive(
            _manifest([f"M01/2025_03_14/{index}.avi" for index in range(3)])
        )
        names = sorted(Path(p["target"]).name for p in placements)
        self.assertEqual(
            names,
            [
                "M01_20250314_video-0.avi",
                "M01_20250314_video-1.avi",
                "M01_20250314_video-2.avi",
            ],
        )

    def test_a_lone_file_of_its_type_needs_no_discriminator(self):
        self.assertEqual(self._name("M01/2025_03_14/0.avi"), "M01_20250314_video.avi")

    def test_compound_extensions_survive_renaming(self):
        name = self._name("M01/2025_03_14/rec_g0_t0.imec0.ap.bin")
        self.assertTrue(name.endswith(".ap.bin"), name)

    def test_original_names_can_be_kept(self):
        placements = derive(
            _manifest(["M01/2025_03_14/0.avi"]), standard_names=False
        )
        self.assertEqual(Path(placements[0]["target"]).name, "0.avi")


class SessionClusteringTests(unittest.TestCase):
    def test_systems_starting_moments_apart_are_one_session(self):
        # A miniscope at 18:32:25 and an Intan at 18:32:20 are one recording.
        placements = derive(
            _manifest(
                [
                    "M01/2025_03_14/18_32_25/a.avi",
                    "M01/2025_03_14/18_32_20/b.rhd",
                ]
            )
        )
        self.assertEqual({p["session"] for p in placements}, {"20250314"})

    def test_recordings_hours_apart_remain_separate_sessions(self):
        placements = derive(
            _manifest(
                [
                    "M01/2025_03_14/09_00_00/a.avi",
                    "M01/2025_03_14/17_00_00/b.avi",
                ]
            )
        )
        self.assertEqual(
            sorted(p["session"] for p in placements), ["20250314_01", "20250314_02"]
        )


class PlanTests(unittest.TestCase):
    def test_a_plan_accounts_for_every_file(self):
        manifest = _manifest(["A0634/2020_11_22/0.avi", "loose.txt"])
        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(manifest, Path(directory) / "out")
            self.assertEqual(plan["file_count"], 2)
            self.assertEqual(plan["placed_count"] + plan["unsorted_count"], 2)

    def test_redundant_copies_are_reported_not_renamed(self):
        # A lab that restructured once has the same recording twice.
        manifest = _manifest(
            ["A0634/2020_11_22/0.avi", "output/raw_data/A0634/2020_11_22/0.avi"]
        )
        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(manifest, Path(directory) / "out")

            self.assertEqual(len(plan["duplicates"]), 1)
            self.assertEqual(plan["collisions"], [])
            # Linked once, not twice under an invented name.
            self.assertEqual(len(plan["actions"]), 1)

    def test_different_files_wanting_one_name_are_both_kept(self):
        manifest = _manifest(
            ["A0634/2020_11_22/a/0.avi", "A0634/2020_11_22/b/0.avi"],
            sizes={"A0634/2020_11_22/a/0.avi": 100, "A0634/2020_11_22/b/0.avi": 999},
        )
        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(manifest, Path(directory) / "out")

            self.assertEqual(len(plan["collisions"]), 1)
            self.assertEqual(len(plan["actions"]), 2)
            targets = {Path(a["target"]).name for a in plan["actions"]}
            self.assertEqual(len(targets), 2)

    def test_link_mode_needs_no_disk_space(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                _manifest(["A0634/2020_11_22/0.avi"]), Path(directory) / "out"
            )
            self.assertEqual(plan["mode"], "link")
            self.assertEqual(plan["bytes_needed"], 0)

    def test_copy_mode_reports_the_space_it_needs(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                _manifest(["A0634/2020_11_22/0.avi"], sizes={"A0634/2020_11_22/0.avi": 500}),
                Path(directory) / "out",
                mode="copy",
            )
            self.assertEqual(plan["bytes_needed"], 500)

    def test_planning_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "out"
            build_plan(_manifest(["A0634/2020_11_22/0.avi"]), destination)
            self.assertFalse(destination.exists())


class ApplyTests(unittest.TestCase):
    def _real(self, base: Path):
        root = build(base / "lab", force=True)
        return ndos_scan.scan(root, include_checksums=True, progress=False)

    def test_linking_builds_the_scaffold_and_leaves_the_source_alone(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = self._real(base)
            before = sorted(p.name for p in (base / "lab").rglob("*"))
            destination = base / "project"

            plan = build_plan(manifest, destination)
            apply_plan(plan, progress=False)

            for name in SCAFFOLD:
                self.assertTrue((destination / name).is_dir(), name)
            self.assertTrue((destination / "README.md").is_file())
            # Source is untouched.
            self.assertEqual(sorted(p.name for p in (base / "lab").rglob("*")), before)

    def test_links_resolve_to_the_original_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = self._real(base)
            destination = base / "project"

            apply_plan(build_plan(manifest, destination), progress=False)

            links = [p for p in (destination / RAW).rglob("*") if p.is_symlink()]
            self.assertTrue(links)
            for link in links[:5]:
                self.assertTrue(link.resolve().is_file())
                # resolve() both sides: on macOS /var is itself a symlink.
                self.assertTrue(
                    str(link.resolve()).startswith(str((base / "lab").resolve()))
                )

    def test_copy_mode_produces_real_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = self._real(base)
            destination = base / "project"

            apply_plan(build_plan(manifest, destination, mode="copy"), progress=False)

            copies = [
                p for p in (destination / RAW).rglob("*")
                if p.is_file() and not p.is_symlink()
            ]
            self.assertTrue(copies)

    def test_flagged_files_get_a_note_explaining_why(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            destination = base / "project"
            plan = build_plan(_manifest(["mystery/thing.bin"]), destination)
            apply_plan(plan, progress=False)

            note = destination / FLAGGED / "flagged_notes.json"
            self.assertTrue(note.is_file())
            content = json.loads(note.read_text(encoding="utf-8"))
            self.assertEqual(len(content["files"]), 1)
            self.assertTrue(content["files"][0]["why"])

    def test_applying_twice_skips_rather_than_duplicating(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            manifest = self._real(base)
            destination = base / "project"
            plan = build_plan(manifest, destination)

            first = apply_plan(plan, progress=False)
            second = apply_plan(plan, progress=False)

            self.assertGreater(first["created_count"], 0)
            self.assertEqual(second["created_count"], 0)
            self.assertEqual(len(second["skipped"]), first["created_count"])


class UndoTests(unittest.TestCase):
    def test_undo_removes_everything_the_layout_created(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = build(base / "lab", force=True)
            manifest = ndos_scan.scan(root, include_checksums=False, progress=False)
            destination = base / "project"

            log = apply_plan(build_plan(manifest, destination), progress=False)
            result = undo(log, progress=False)

            self.assertGreater(result["removed"], 0)
            self.assertEqual(result["failed"], [])
            leftover = list(destination.rglob("*")) if destination.exists() else []
            self.assertEqual(leftover, [])

    def test_undo_after_a_move_puts_the_files_back(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "lab" / "A0634" / "2020_11_22"
            source.mkdir(parents=True)
            (source / "0.avi").write_bytes(b"recording")
            manifest = ndos_scan.scan(
                base / "lab", include_checksums=False, progress=False
            )
            destination = base / "project"

            log = apply_plan(
                build_plan(manifest, destination, mode="move"), progress=False
            )
            self.assertFalse((source / "0.avi").exists())

            result = undo(log, progress=False)

            self.assertEqual(result["restored"], 1)
            self.assertTrue((source / "0.avi").is_file())
            self.assertEqual((source / "0.avi").read_bytes(), b"recording")

    def test_undo_does_not_delete_a_readme_it_did_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            destination = base / "project"
            destination.mkdir()
            readme = destination / "README.md"
            readme.write_text("mine, not NDOS's", encoding="utf-8")

            log = apply_plan(
                build_plan(_manifest(["A0634/2020_11_22/0.avi"]), destination),
                progress=False,
            )
            undo(log, progress=False)

            self.assertTrue(readme.is_file())
            self.assertEqual(readme.read_text(encoding="utf-8"), "mine, not NDOS's")


if __name__ == "__main__":
    unittest.main()
