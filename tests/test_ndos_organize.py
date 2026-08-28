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


class OverrideTests(unittest.TestCase):
    """Telling NDOS where the subject and session are, when it cannot tell.

    Real layouts exist that no heuristic will read correctly. A user who can
    see the mistake has to be able to say so, or their only option is to stop.
    """

    LAYOUT = ["study7/cohortB/rat14/day3/rec.dat"]

    def test_an_unreadable_layout_is_flagged_when_guessing(self):
        placement = derive(_manifest(self.LAYOUT))[0]
        self.assertFalse(placement["placed"])

    def test_naming_the_levels_places_it_correctly(self):
        placement = derive(
            _manifest(self.LAYOUT), subject_depth=2, session_depth=3
        )[0]

        self.assertTrue(placement["placed"])
        self.assertEqual(placement["subject"], "rat14")
        self.assertEqual(placement["session"], "day3")
        self.assertTrue(placement["target"].startswith("raw_data/rat14/day3/"))

    def test_an_override_says_it_was_told_rather_than_guessed(self):
        placement = derive(
            _manifest(self.LAYOUT), subject_depth=2, session_depth=3
        )[0]
        self.assertIn("as you specified", " ".join(placement["why"]))

    def test_a_named_session_level_holding_a_date_is_still_normalised(self):
        placement = derive(
            _manifest(["lab/M01/2025_03_14/rec.dat"]),
            subject_depth=1, session_depth=2,
        )[0]
        # Told where to look, but the date is still read as a date.
        self.assertEqual(placement["session"], "20250314")

    def test_a_named_session_level_holding_a_compound_name_is_parsed(self):
        placement = derive(
            _manifest(["lab/A0634/A0634_201122_183220/rec.dat"]),
            subject_depth=1, session_depth=2,
        )[0]
        self.assertEqual(placement["session"], "20201122")

    def test_a_path_too_shallow_for_the_named_level_falls_back(self):
        # A recording, not a note: notes go to metadata/ and need no subject.
        placements = derive(
            _manifest(["M01/2025_03_14/rec.dat", "loose.dat"]),
            subject_depth=0, session_depth=1,
        )
        by_source = {p["source"]: p for p in placements}
        self.assertEqual(by_source["M01/2025_03_14/rec.dat"]["subject"], "M01")
        # Nothing at that level here; it is flagged, not crashed or mislabelled.
        self.assertFalse(by_source["loose.dat"]["placed"])

    def test_overrides_reach_the_plan(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                _manifest(self.LAYOUT), Path(directory) / "out",
                subject_depth=2, session_depth=3,
            )
            self.assertEqual(plan["placed_count"], 1)
            self.assertEqual(plan["subjects"], ["rat14"])


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


class PilotFindingsTests(unittest.TestCase):
    """Reported from a run against a real 609 GB drive, 2026-08-27.

    Each of these was found by someone using the tool rather than building it,
    which is why they are pinned here.
    """

    def test_an_archive_named_subject_and_date_is_read(self):
        # Every session in one lab was archived as A3302-190809.zip, and all
        # 287 of them were flagged: the animal was in the filename, not a
        # folder, and the year had two digits.
        placement = derive(_manifest(["Gilberto/A3200/A3302-190809.zip"]))[0]

        self.assertTrue(placement["placed"])
        self.assertEqual(placement["subject"], "A3302")
        self.assertEqual(placement["session"], "20190809")

    def test_the_animal_in_the_filename_beats_the_cohort_in_the_folder(self):
        # A3200 is the group; A3302 is the animal. Trusting the folder would
        # have labelled every session with its cohort.
        placement = derive(_manifest(["Gilberto/A3200/A3302-190809.zip"]))[0]
        self.assertNotEqual(placement["subject"], "A3200")
        self.assertIn("filename", " ".join(placement["why"]))

    def test_a_two_digit_year_resolves_to_this_century(self):
        placement = derive(_manifest(["lab/A3303-191021.zip"]))[0]
        self.assertEqual(placement["session"], "20191021")

    def test_the_older_folder_convention_still_works(self):
        placement = derive(_manifest(["lab/A3302/2019_08_09/rec.dat"]))[0]
        self.assertEqual(placement["subject"], "A3302")
        self.assertEqual(placement["session"], "20190809")

    def test_a_successful_apply_does_not_tell_you_to_run_apply(self):
        from ndos_organize import render_plan

        with tempfile.TemporaryDirectory() as directory:
            plan = build_plan(
                _manifest(["M01/2025_03_14/rec.dat"]), Path(directory) / "out"
            )
            planning = render_plan(plan)
            applying = render_plan(plan, footer=False)

            self.assertIn("run 'apply'", planning)
            self.assertNotIn("run 'apply'", applying)
            self.assertNotIn("Nothing has been created", applying)


class ToolOutputTests(unittest.TestCase):
    """Directories an analysis tool reads back by name.

    Phy, Kilosort and SpikeInterface open a sorting by looking for
    `spike_times.npy` and `params.py`. Renaming those to the N-DOS convention
    means the sorting can no longer be opened, which is the opposite of what
    organising it is for.
    """

    PHY = [
        "M123/2025_03_14/phy_output/params.py",
        "M123/2025_03_14/phy_output/spike_times.npy",
        "M123/2025_03_14/phy_output/spike_clusters.npy",
        "M123/2025_03_14/phy_output/channel_positions.npy",
        "M123/2025_03_14/phy_output/cluster_info.tsv",
    ]

    def test_a_sorting_folder_keeps_every_filename(self):
        placements = derive(_manifest(self.PHY))
        for placement in placements:
            self.assertEqual(
                Path(placement["target"]).name, placement["original_name"]
            )

    def test_it_lands_under_the_session_it_belongs_to(self):
        placements = derive(_manifest(self.PHY))
        for placement in placements:
            self.assertTrue(
                placement["target"].startswith(
                    "processed_data/M123/20250314/phy_output/"
                ),
                placement["target"],
            )

    def test_channel_positions_is_not_retyped_as_behavioural_tracking(self):
        # _position is the naming convention's behavioural tracking suffix.
        # channel_positions.npy is electrode geometry; calling it position
        # data would be wrong as well as unreadable.
        placement = next(
            p for p in derive(_manifest(self.PHY))
            if p["original_name"] == "channel_positions.npy"
        )
        self.assertEqual(Path(placement["target"]).name, "channel_positions.npy")

    def test_the_reason_says_why_it_was_left_alone(self):
        placement = derive(_manifest(self.PHY))[0]
        why = " ".join(placement["why"])
        self.assertIn("Phy", why)
        self.assertIn("reading it back", why)

    def test_nested_structure_inside_the_output_is_preserved(self):
        # Open Ephys keeps continuous/<processor>/continuous.dat, and the
        # reader walks that path.
        placements = derive(
            _manifest(
                [
                    "M123/2025_03_14/rec/structure.oebin",
                    "M123/2025_03_14/rec/continuous/Rhythm_FPGA-100.0/continuous.dat",
                ]
            )
        )
        targets = sorted(p["target"] for p in placements)
        self.assertEqual(
            targets,
            [
                "processed_data/M123/20250314/rec/continuous/Rhythm_FPGA-100.0/continuous.dat",
                "processed_data/M123/20250314/rec/structure.oebin",
            ],
        )

    def test_a_zarr_store_is_carried_whole(self):
        placements = derive(
            _manifest(
                [
                    "M123/2025_03_14/wf.zarr/.zgroup",
                    "M123/2025_03_14/wf.zarr/traces/0.0",
                ]
            )
        )
        for placement in placements:
            self.assertIn("wf.zarr/", placement["target"])

    def test_files_beside_a_tool_output_are_still_renamed(self):
        # Only what is inside the tool's directory is exempt.
        placements = derive(
            _manifest(self.PHY + ["M123/2025_03_14/0.avi"])
        )
        video = next(p for p in placements if p["original_name"] == "0.avi")
        self.assertEqual(Path(video["target"]).name, "M123_20250314_video.avi")

    def test_a_folder_missing_the_marker_files_is_not_treated_as_tool_output(self):
        # Two .npy files are not a sorting; the markers are what identify one.
        placements = derive(
            _manifest(
                [
                    "M123/2025_03_14/results/values.npy",
                    "M123/2025_03_14/results/other.npy",
                ]
            )
        )
        self.assertTrue(
            all(p["tool_output"] is None for p in placements)
            if all("tool_output" in p for p in placements)
            else True
        )
        names = {Path(p["target"]).name for p in placements}
        self.assertTrue(any(name.startswith("M123_20250314_") for name in names))


class SubjectVersusSessionTests(unittest.TestCase):
    """A session folder is not a subject.

    "ses-01" is letters followed by digits, which is also what a subject
    identifier looks like. Taking the deepest match read the session as the
    animal and demoted the animal to a cohort -- on any lab using the
    sub/ses layout, which is the common one.
    """

    def test_a_session_folder_is_not_read_as_the_subject(self):
        placement = derive(_manifest(["2025-03-14/M01/ses-01/raw/rec.dat"]))[0]

        self.assertEqual(placement["subject"], "M01")
        self.assertNotEqual(placement["subject"], "ses-01")

    def test_a_date_is_preferred_over_a_session_label(self):
        # The standard recommends YYYYMMDD, and here the path records one.
        placement = derive(_manifest(["2025-03-14/M01/ses-01/raw/rec.dat"]))[0]
        self.assertEqual(placement["session"], "20250314")

    def test_a_session_label_is_used_when_no_date_exists(self):
        placement = derive(_manifest(["sub-01/ses-03/rec.dat"]))[0]
        self.assertEqual(placement["session"], "ses-03")
        self.assertIn("no date is recorded", " ".join(placement["why"]))

    def test_run_folders_are_not_read_as_subjects_either(self):
        placement = derive(_manifest(["2025-03-14/M01/run-02/rec.dat"]))[0]
        self.assertEqual(placement["subject"], "M01")

    def test_organize_output_satisfies_the_standard_it_implements(self):
        import ndos_scan
        import ndos_validate
        from make_messy_lab import build

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = build(base / "lab", force=True)
            manifest = ndos_scan.scan(root, include_checksums=False, progress=False)
            project = base / "project"

            apply_plan(build_plan(manifest, project), progress=False)
            result = ndos_validate.validate(project)

            # A project this tool builds must pass the checker beside it.
            self.assertTrue(
                result["conforms"],
                [f["message"] for f in result["findings"]
                 if f["level"] == "requirement"],
            )
