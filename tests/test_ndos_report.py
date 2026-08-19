"""Tests for the inventory report.

The report's value depends on it being honest: a duplicate it claims must be
byte-identical, an inferred structure must be labelled as inferred, and a
problem it does not detect must not be implied to be absent.
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
from ndos_report import (
    build_report,
    categorise,
    duplicate_groups,
    render_markdown,
    render_text,
    structure,
)


class CategorisationTests(unittest.TestCase):
    def test_compound_suffixes_are_recognised(self):
        # Path.suffix sees only `.bin`; the filename identifies SpikeGLX.
        self.assertEqual(
            categorise(".bin", "M01_g0_t0.imec0.ap.bin"), "Electrophysiology"
        )
        self.assertEqual(
            categorise(".meta", "M01_g0_t0.imec0.lf.meta"), "Electrophysiology"
        )
        self.assertEqual(categorise(".dat", "continuous.dat"), "Electrophysiology")
        self.assertEqual(categorise(".gz", "archive.tar.gz"), "Archives")

    def test_genuinely_ambiguous_extensions_are_not_guessed(self):
        self.assertEqual(
            categorise(".bin", "recording.bin"), "Ambiguous (could be raw data)"
        )
        self.assertEqual(categorise(".dat", "output.dat"), "Ambiguous (could be raw data)")

    def test_known_and_unknown_extensions(self):
        self.assertEqual(categorise(".nwb", "session.nwb"), "Standard neurodata containers")
        self.assertEqual(categorise(".csv", "behaviour.csv"), "Tabular and behavioural")
        self.assertEqual(categorise("", "README"), "No extension")
        self.assertEqual(categorise(".qqq", "thing.qqq"), "Unclassified")


class DuplicateTests(unittest.TestCase):
    def test_identical_files_are_grouped_and_waste_is_counted(self):
        files = [
            {"path": "a.bin", "size_bytes": 100, "sha256": "a" * 64},
            {"path": "backup/a.bin", "size_bytes": 100, "sha256": "a" * 64},
            {"path": "copy/a.bin", "size_bytes": 100, "sha256": "a" * 64},
            {"path": "b.bin", "size_bytes": 50, "sha256": "b" * 64},
        ]

        groups = duplicate_groups(files)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["copies"], 3)
        # Three copies of a 100-byte file waste 200 bytes, not 300.
        self.assertEqual(groups[0]["wasted_bytes"], 200)
        self.assertEqual(
            groups[0]["paths"], ["a.bin", "backup/a.bin", "copy/a.bin"]
        )

    def test_zero_byte_files_are_not_reported_as_duplicates(self):
        files = [
            {"path": "x", "size_bytes": 0, "sha256": "e" * 64},
            {"path": "y", "size_bytes": 0, "sha256": "e" * 64},
        ]
        self.assertEqual(duplicate_groups(files), [])

    def test_missing_checksums_yield_no_duplicate_claims(self):
        files = [
            {"path": "a.bin", "size_bytes": 100},
            {"path": "b.bin", "size_bytes": 100},
        ]
        self.assertEqual(duplicate_groups(files), [])


class StructureTests(unittest.TestCase):
    def test_session_names_are_not_mistaken_for_subject_ids(self):
        # `ses-01` is letters-then-digits, so a generic ID pattern would match
        # it. The specific session pattern must win.
        files = [
            {"path": f"sub-0{n}/ses-0{m}/raw/file.bin", "size_bytes": 1}
            for n in range(1, 5)
            for m in range(1, 4)
        ]

        levels = {level["depth"]: level for level in structure(files)}

        self.assertEqual(levels[0]["inferred"], "animal or subject ID")
        self.assertEqual(levels[1]["inferred"], "session")

    def test_dates_are_recognised_in_several_shapes(self):
        files = [
            {"path": f"{name}/f.bin", "size_bytes": 1}
            for name in ("2025-03-14", "2025_03_21", "20250402", "2025-04-10")
        ]
        levels = structure(files)
        self.assertEqual(levels[0]["inferred"], "date")

    def test_a_level_with_no_pattern_is_reported_as_unclear(self):
        files = [
            {"path": f"{name}/f.bin", "size_bytes": 1}
            for name in ("elephant", "correspondence", "misc_stuff", "qq")
        ]
        levels = structure(files)
        self.assertIsNone(levels[0]["inferred"])
        self.assertEqual(levels[0]["confidence"], 0.0)

    def test_names_contradicting_the_pattern_are_surfaced(self):
        files = [
            {"path": f"{name}/f.bin", "size_bytes": 1}
            for name in ("sub-01", "sub-02", "sub-03", "sub-04", "leftovers")
        ]
        levels = structure(files)
        self.assertEqual(levels[0]["inferred"], "animal or subject ID")
        self.assertIn("leftovers", levels[0]["exceptions"])


class EndToEndTests(unittest.TestCase):
    """Run the whole pipeline over the synthetic messy lab fixture."""

    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        root = build(Path(cls._directory.name) / "messy-lab", force=True)
        cls.manifest = ndos_scan.scan(root)
        cls.report = build_report(cls.manifest)

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    def test_junk_is_excluded_from_the_inventory(self):
        names = {entry["name"] for entry in self.manifest["files"]}
        self.assertNotIn(".DS_Store", names)
        self.assertNotIn("Thumbs.db", names)

    def test_the_duplicated_backup_is_detected(self):
        paths = {
            path
            for group in self.report["duplicates"]["largest"]
            for path in group["paths"]
        }
        self.assertIn(
            "2025-03-14/M01/ses-01/raw/M01_ses01_g0_t0.imec0.ap.bin", paths
        )
        self.assertIn(
            "backup/2025-03-14/M01/ses-01/raw/M01_ses01_g0_t0.imec0.ap.bin", paths
        )
        self.assertGreater(self.report["duplicates"]["wasted_bytes"], 0)

    def test_failed_acquisitions_are_flagged(self):
        titles = " ".join(flag["title"] for flag in self.report["attention"])
        self.assertIn("zero-byte", titles)

    def test_unextracted_archives_are_flagged(self):
        titles = " ".join(flag["title"] for flag in self.report["attention"])
        self.assertIn("archive", titles)

    def test_spikeglx_files_are_classified_as_ephys(self):
        categories = {row["category"] for row in self.report["composition"]}
        self.assertIn("Electrophysiology", categories)

    def test_summary_totals_are_internally_consistent(self):
        summary = self.report["summary"]
        self.assertEqual(summary["file_count"], len(self.manifest["files"]))
        self.assertEqual(
            summary["total_bytes"],
            sum(entry["size_bytes"] for entry in self.manifest["files"]),
        )

    def test_every_output_format_renders(self):
        text = render_text(self.report)
        markdown = render_markdown(self.report)
        as_json = json.loads(json.dumps(self.report))

        self.assertIn("NDOS INVENTORY REPORT", text)
        self.assertIn("Nothing was modified", text)
        self.assertIn("# NDOS inventory report", markdown)
        self.assertEqual(as_json["source_root"], self.report["source_root"])

    def test_inference_is_labelled_as_observation_not_fact(self):
        text = render_text(self.report)
        self.assertIn("Observed patterns only", text)


if __name__ == "__main__":
    unittest.main()
