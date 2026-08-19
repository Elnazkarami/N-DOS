"""Tests for the spreadsheet metadata round-trip.

The property that matters most is that re-exporting never destroys work a
person typed in. A tool that loses an afternoon of manual metadata entry gets
uninstalled, so that behaviour is tested from several directions.
"""

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

import ndos_scan
import ndos_table
from make_messy_lab import build
from ndos_table import (
    COLUMNS,
    DECLARED_COLUMNS,
    check_table,
    group_sessions,
    merge_declared,
    normalise,
    read_table,
    to_records,
    write_table,
)


def _row(**overrides):
    row = {column: "" for column in COLUMNS}
    row.update(overrides)
    return row


class NormalisationTests(unittest.TestCase):
    def test_common_species_spellings_are_accepted(self):
        for text in ("mouse", "Mouse", "MICE", "mus musculus"):
            self.assertEqual(normalise("species", text), "mus musculus")
        self.assertEqual(normalise("species", "rat"), "rattus norvegicus")

    def test_common_sex_spellings_are_accepted(self):
        for text in ("female", "Female", "F", "fem"):
            self.assertEqual(normalise("sex", text), "F")
        for text in ("male", "M"):
            self.assertEqual(normalise("sex", text), "M")
        self.assertEqual(normalise("sex", "n/a"), "unknown")

    def test_lab_shorthand_for_modality_is_accepted(self):
        self.assertEqual(normalise("session_type", "ephys"), "electrophysiology")
        self.assertEqual(normalise("session_type", "2p"), "calcium imaging")
        self.assertEqual(normalise("session_type", "behavior"), "behaviour")

    def test_unrecognised_values_pass_through_for_validation_to_catch(self):
        self.assertEqual(normalise("sex", "xyz"), "xyz")
        self.assertEqual(normalise("strain", "C57BL/6J"), "C57BL/6J")


class ValidationTests(unittest.TestCase):
    def test_ambiguous_dates_are_rejected_with_an_explanation(self):
        result = check_table([_row(ndos_id="ndos-0000000001", session_date="21/03/2025")])
        self.assertEqual(len(result["problems"]), 1)
        self.assertIn("ambiguous", result["problems"][0]["message"])

    def test_iso_dates_are_accepted(self):
        result = check_table([_row(ndos_id="ndos-0000000001", session_date="2025-03-21")])
        self.assertEqual(result["problems"], [])

    def test_values_outside_a_vocabulary_are_rejected(self):
        result = check_table([_row(ndos_id="ndos-0000000001", sex="yes")])
        self.assertEqual(len(result["problems"]), 1)
        self.assertEqual(result["problems"][0]["column"], "sex")

    def test_duplicate_identifiers_are_reported(self):
        result = check_table([
            _row(ndos_id="ndos-0000000001"),
            _row(ndos_id="ndos-0000000001"),
        ])
        self.assertTrue(
            any("duplicate" in p["message"] for p in result["problems"])
        )

    def test_explicit_unknown_is_counted_separately_from_blank(self):
        result = check_table([
            _row(ndos_id="ndos-0000000001", sex="unknown"),
            _row(ndos_id="ndos-0000000002"),
        ])
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["completeness"]["sex"]["filled"], 1)
        self.assertEqual(result["completeness"]["sex"]["explicit_unknown"], 1)

    def test_a_row_is_complete_only_with_every_required_field(self):
        complete = _row(
            ndos_id="ndos-0000000001", subject_id="M01", species="mouse",
            sex="F", session_date="2025-03-14",
        )
        partial = _row(ndos_id="ndos-0000000002", subject_id="M02", species="mouse")

        result = check_table([complete, partial])

        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["complete_rows"], 1)


class MergeTests(unittest.TestCase):
    def test_entered_values_survive_a_rescan(self):
        existing = [
            _row(ndos_id="ndos-0000000001", subject_id="M01", species="mouse", sex="F")
        ]
        fresh = [
            {"ndos_id": "ndos-0000000001", "observed_file_count": 9},
            {"ndos_id": "ndos-0000000002", "observed_file_count": 3},
        ]

        merged, stats = merge_declared(fresh, existing)

        self.assertEqual(merged[0]["subject_id"], "M01")
        self.assertEqual(merged[0]["species"], "mouse")
        # Observed values are refreshed, not carried over from the old table.
        self.assertEqual(merged[0]["observed_file_count"], 9)
        self.assertEqual(stats["matched"], 1)
        self.assertEqual(stats["orphaned"], 0)

    def test_rows_that_vanish_are_reported_rather_than_silently_dropped(self):
        existing = [_row(ndos_id="ndos-deadbeef00", subject_id="M99")]
        fresh = [{"ndos_id": "ndos-0000000001"}]

        _, stats = merge_declared(fresh, existing)

        self.assertEqual(stats["orphaned"], 1)
        self.assertEqual(stats["matched"], 0)

    def test_a_blank_old_value_never_overwrites_a_new_one(self):
        existing = [_row(ndos_id="ndos-0000000001", subject_id="")]
        fresh = [{"ndos_id": "ndos-0000000001", "subject_id": "M07"}]

        merged, _ = merge_declared(fresh, existing)

        self.assertEqual(merged[0]["subject_id"], "M07")


class CsvSafetyTests(unittest.TestCase):
    def test_formula_injection_from_folder_names_is_neutralised(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.csv"
            write_table([_row(ndos_id="ndos-0000000001", observed_path="=cmd|calc")], path)

            raw = path.read_text(encoding="utf-8-sig")
            self.assertIn("'=cmd|calc", raw)
            # Round-trips back to a value, not a formula.
            self.assertEqual(read_table(path)[0]["observed_path"], "'=cmd|calc")

    def test_the_file_is_written_with_a_bom_so_excel_opens_it_correctly(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.csv"
            write_table([_row(ndos_id="ndos-0000000001")], path)
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_unicode_survives_the_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "t.csv"
            write_table([_row(ndos_id="ndos-0000000001", notes="süß — µV, 30°C")], path)
            self.assertEqual(read_table(path)[0]["notes"], "süß — µV, 30°C")


class RecordTests(unittest.TestCase):
    def test_evidence_status_distinguishes_declared_from_unknown(self):
        rows = [_row(ndos_id="ndos-0000000001", subject_id="M01", sex="unknown")]
        records = to_records(rows)

        declared = records["sessions"][0]["declared"]
        self.assertEqual(declared["subject_id"]["status"], "declared")
        self.assertEqual(declared["sex"]["status"], "unknown")

    def test_blank_fields_are_absent_rather_than_empty(self):
        rows = [_row(ndos_id="ndos-0000000001", subject_id="M01")]
        declared = to_records(rows)["sessions"][0]["declared"]

        self.assertIn("subject_id", declared)
        # Nobody has filled these in; that is different from 'unknown'.
        self.assertNotIn("species", declared)
        self.assertNotIn("sex", declared)

    def test_the_original_text_is_kept_whenever_a_value_is_mapped(self):
        rows = [_row(ndos_id="ndos-0000000001", species="mouse", strain="C57BL/6J")]
        declared = to_records(rows)["sessions"][0]["declared"]

        self.assertEqual(declared["species"]["value"], "mus musculus")
        self.assertEqual(declared["species"]["as_entered"], "mouse")
        # Nothing was mapped, so there is nothing to audit.
        self.assertNotIn("as_entered", declared["strain"])

    def test_rows_with_no_entered_metadata_are_omitted_by_default(self):
        rows = [
            _row(ndos_id="ndos-0000000001", subject_id="M01"),
            _row(ndos_id="ndos-0000000002"),
        ]
        self.assertEqual(to_records(rows)["session_count"], 1)
        self.assertEqual(to_records(rows, include_empty=True)["session_count"], 2)


class GroupingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._directory = tempfile.TemporaryDirectory()
        root = build(Path(cls._directory.name) / "lab", force=True)
        cls.manifest = ndos_scan.scan(root, include_checksums=False)
        cls.rows = group_sessions(cls.manifest)

    @classmethod
    def tearDownClass(cls):
        cls._directory.cleanup()

    def test_real_sessions_are_distinguished_from_noise(self):
        by_path = {row["observed_path"]: row for row in self.rows}

        self.assertEqual(
            by_path["2025-03-14/M01/ses-01"]["observed_match"], "subject and session"
        )
        self.assertEqual(
            by_path["2025-03-21/m02/session2"]["observed_match"], "subject and session"
        )
        # A scratch folder is not a session and must not be presented as one.
        self.assertEqual(by_path["scratch"]["observed_match"], "no pattern match")

    def test_a_duplicated_backup_is_not_merged_into_the_original(self):
        paths = {row["observed_path"] for row in self.rows}
        self.assertIn("2025-03-14/M01/ses-01", paths)
        self.assertTrue(any(path.startswith("backup/") for path in paths))

    def test_identifiers_are_stable_across_repeated_exports(self):
        again = group_sessions(self.manifest)
        self.assertEqual(
            [row["ndos_id"] for row in self.rows],
            [row["ndos_id"] for row in again],
        )

    def test_every_file_is_accounted_for_in_exactly_one_group(self):
        self.assertEqual(
            sum(row["observed_file_count"] for row in self.rows),
            self.manifest["file_count"],
        )

    def test_modalities_are_reported_per_session(self):
        by_path = {row["observed_path"]: row for row in self.rows}
        self.assertIn(
            "Electrophysiology", by_path["2025-03-14/M01/ses-01"]["observed_modalities"]
        )


class SchemaTests(unittest.TestCase):
    def test_emitted_records_match_the_published_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed; NDOS core stays stdlib-only")

        schema_path = (
            Path(__file__).resolve().parent.parent
            / "schemas"
            / "session_metadata.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            root = build(Path(directory) / "lab", force=True)
            manifest = ndos_scan.scan(root, include_checksums=False)
            rows = group_sessions(manifest)
            for row in rows:
                row.update(
                    subject_id="M01", species="mouse", sex="female",
                    session_date="2025-03-14", session_type="ephys",
                )
            jsonschema.validate(to_records(rows), schema)


class EndToEndTests(unittest.TestCase):
    def test_export_fill_rescan_preserves_entered_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = build(base / "lab", force=True)
            table = base / "sessions.csv"

            # 1. Export a fresh table.
            manifest = ndos_scan.scan(root, include_checksums=False)
            write_table(group_sessions(manifest), table)

            # 2. A researcher fills in one session.
            rows = read_table(table)
            target = next(
                row for row in rows
                if row["observed_path"] == "2025-03-14/M01/ses-01"
            )
            target.update(subject_id="M01", species="mouse", sex="female")
            write_table(rows, table)

            # 3. New data arrives and everything is rescanned.
            new_session = root / "2025-05-01" / "M09" / "ses-01" / "raw"
            new_session.mkdir(parents=True)
            (new_session / "rec.ap.bin").write_bytes(b"x" * 1000)

            manifest = ndos_scan.scan(root, include_checksums=False)
            merged, stats = merge_declared(
                group_sessions(manifest), read_table(table)
            )
            write_table(merged, table)

            # 4. The typed metadata survived, and the new session is present.
            final = {row["observed_path"]: row for row in read_table(table)}
            self.assertEqual(final["2025-03-14/M01/ses-01"]["subject_id"], "M01")
            self.assertEqual(final["2025-03-14/M01/ses-01"]["species"], "mouse")
            self.assertIn("2025-05-01/M09/ses-01", final)
            self.assertEqual(final["2025-05-01/M09/ses-01"]["subject_id"], "")
            self.assertEqual(stats["orphaned"], 0)


if __name__ == "__main__":
    unittest.main()
