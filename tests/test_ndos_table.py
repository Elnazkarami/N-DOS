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
    _typed_fields,
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
        result = check_table([_row(ndos_id="ndos-0000000001", qc_status="maybe")])
        self.assertEqual(len(result["problems"]), 1)
        self.assertEqual(result["problems"][0]["column"], "qc_status")

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
            _row(ndos_id="ndos-0000000001", qc_status="unknown"),
            _row(ndos_id="ndos-0000000002"),
        ])
        self.assertEqual(result["problems"], [])
        self.assertEqual(result["completeness"]["qc_status"]["filled"], 1)
        self.assertEqual(result["completeness"]["qc_status"]["explicit_unknown"], 1)

    def test_a_row_is_complete_only_with_every_required_field(self):
        complete = _row(
            ndos_id="ndos-0000000001", subject_id="M01", session_date="2025-03-14",
        )
        partial = _row(ndos_id="ndos-0000000002", subject_id="M02")

        result = check_table([complete, partial])

        self.assertEqual(result["row_count"], 2)
        self.assertEqual(result["complete_rows"], 1)


class MergeTests(unittest.TestCase):
    def test_entered_values_survive_a_rescan(self):
        existing = [
            _row(ndos_id="ndos-0000000001", subject_id="M01", session_type="ephys")
        ]
        fresh = [
            {"ndos_id": "ndos-0000000001", "observed_file_count": 9},
            {"ndos_id": "ndos-0000000002", "observed_file_count": 3},
        ]

        merged, stats = merge_declared(fresh, existing)

        self.assertEqual(merged[0]["subject_id"], "M01")
        self.assertEqual(merged[0]["session_type"], "ephys")
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


class EvidenceTypingTests(unittest.TestCase):
    """How a value is known travels with the value itself."""

    def test_declared_is_distinguished_from_explicitly_unknown(self):
        fields = _typed_fields(
            _row(subject_id="M01", qc_status="unknown"),
            ndos_table.SESSION_DECLARED_COLUMNS,
        )
        self.assertEqual(fields["subject_id"]["status"], "declared")
        self.assertEqual(fields["qc_status"]["status"], "unknown")

    def test_blank_fields_are_absent_rather_than_empty(self):
        fields = _typed_fields(
            _row(subject_id="M01"), ndos_table.SESSION_DECLARED_COLUMNS
        )
        self.assertIn("subject_id", fields)
        # Nobody has filled these in; that is different from 'unknown'.
        self.assertNotIn("session_date", fields)
        self.assertNotIn("qc_status", fields)

    def test_the_original_text_is_kept_whenever_a_value_is_mapped(self):
        fields = _typed_fields(
            _row(session_type="ephys", task="T-maze"),
            ndos_table.SESSION_DECLARED_COLUMNS,
        )
        self.assertEqual(fields["session_type"]["value"], "electrophysiology")
        self.assertEqual(fields["session_type"]["as_entered"], "ephys")
        # Nothing was mapped, so there is nothing to audit.
        self.assertNotIn("as_entered", fields["task"])


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
    def test_linked_records_match_the_published_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed; NDOS core stays stdlib-only")

        schema_path = (
            Path(__file__).resolve().parent.parent
            / "schemas" / "session_metadata.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = build(base / "lab", force=True)
            manifest = ndos_scan.scan(root, include_checksums=False)
            metadata = base / "metadata"
            ndos_table.export_metadata(manifest, metadata)

            with (metadata / ndos_table.ANIMALS_FILE).open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=list(ndos_table.ANIMAL_COLUMNS))
                writer.writeheader()
                writer.writerow({"subject_id": "M01", "species": "mouse",
                                 "sex": "female", "date_of_birth": "2024-11-02"})
            with (metadata / ndos_table.PROCEDURES_FILE).open(
                "w", encoding="utf-8-sig", newline=""
            ) as stream:
                writer = csv.DictWriter(stream, fieldnames=list(ndos_table.PROCEDURE_COLUMNS))
                writer.writeheader()
                writer.writerow({"procedure_id": "P001", "subject_id": "M01",
                                 "procedure_date": "2025-02-14",
                                 "procedure_type": "viral injection",
                                 "target_region": "CA1"})
            rows = read_table(metadata / ndos_table.SESSIONS_FILE)
            for row in rows:
                if row["observed_path"] == "2025-03-14/M01/ses-01":
                    row["subject_id"] = "M01"
                    row["session_date"] = "2025-03-14"
                    row["session_type"] = "ephys"
            write_table(rows, metadata / ndos_table.SESSIONS_FILE)

            jsonschema.validate(ndos_table.link_records(metadata), schema)


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
            target.update(subject_id="M01", session_type="ephys", qc_status="pass")
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
            self.assertEqual(
                final["2025-03-14/M01/ses-01"]["session_type"], "ephys"
            )
            self.assertIn("2025-05-01/M09/ses-01", final)
            self.assertEqual(final["2025-05-01/M09/ses-01"]["subject_id"], "")
            self.assertEqual(stats["orphaned"], 0)


if __name__ == "__main__":
    unittest.main()


class EntityModelTests(unittest.TestCase):
    """The three linked tables, and what they make possible.

    The point of splitting animals and procedures out of the session sheet is
    that a fact recorded once should govern every session it applies to.
    """

    def _build(self, base: Path):
        root = build(base / "lab", force=True)
        manifest = ndos_scan.scan(root, include_checksums=False)
        directory = base / "metadata"
        ndos_table.export_metadata(manifest, directory)
        return directory

    def _write(self, path: Path, rows, columns):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(columns))
            writer.writeheader()
            writer.writerows(rows)

    def test_export_creates_three_linked_tables(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))

            self.assertTrue((metadata / ndos_table.ANIMALS_FILE).is_file())
            self.assertTrue((metadata / ndos_table.PROCEDURES_FILE).is_file())
            self.assertTrue((metadata / ndos_table.SESSIONS_FILE).is_file())

    def test_animals_are_seeded_from_observed_subject_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))
            names = {
                row["subject_id"]
                for row in read_table(metadata / ndos_table.ANIMALS_FILE)
            }

            self.assertIn("M01", names)
            self.assertIn("M03", names)
            # A scratch folder is not an animal.
            self.assertNotIn("scratch", names)
            self.assertNotIn("backup", names)

    def test_procedures_are_never_overwritten_by_a_rescan(self):
        # NDOS cannot observe a surgery, so it must never touch that file.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            metadata = self._build(base)
            procedures = metadata / ndos_table.PROCEDURES_FILE
            self._write(
                procedures,
                [{"procedure_id": "P001", "subject_id": "M01",
                  "procedure_date": "2025-02-14", "procedure_type": "injection"}],
                ndos_table.PROCEDURE_COLUMNS,
            )

            manifest = ndos_scan.scan(base / "lab", include_checksums=False)
            ndos_table.export_metadata(manifest, metadata)

            rows = read_table(procedures)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["procedure_id"], "P001")

    def test_animal_facts_are_recorded_once_and_reach_every_session(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))
            self._write(
                metadata / ndos_table.ANIMALS_FILE,
                [{"subject_id": "M01", "species": "mouse", "sex": "female"}],
                ndos_table.ANIMAL_COLUMNS,
            )
            sessions = read_table(metadata / ndos_table.SESSIONS_FILE)
            for row in sessions:
                if row["observed_path"].startswith("2025-03-14/M01"):
                    row["subject_id"] = "M01"
                    row["session_date"] = "2025-03-14"
            self._write(metadata / ndos_table.SESSIONS_FILE, sessions, ndos_table.COLUMNS)

            linked = ndos_table.link_records(metadata)
            record = linked["sessions"][0]

            # Typed once in animals.csv, present on the session.
            self.assertEqual(record["animal"]["declared"]["species"]["value"], "mus musculus")
            self.assertEqual(record["animal"]["declared"]["sex"]["value"], "F")

    def test_intervals_since_a_procedure_are_computed_not_typed(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))
            self._write(
                metadata / ndos_table.ANIMALS_FILE,
                [{"subject_id": "M01", "species": "mouse", "sex": "F",
                  "date_of_birth": "2024-11-02"}],
                ndos_table.ANIMAL_COLUMNS,
            )
            self._write(
                metadata / ndos_table.PROCEDURES_FILE,
                [{"procedure_id": "P001", "subject_id": "M01",
                  "procedure_date": "2025-02-14",
                  "procedure_type": "viral injection", "target_region": "CA1"}],
                ndos_table.PROCEDURE_COLUMNS,
            )
            sessions = read_table(metadata / ndos_table.SESSIONS_FILE)
            for row in sessions:
                if row["observed_path"] == "2025-03-14/M01/ses-01":
                    row["subject_id"] = "M01"
                    row["session_date"] = "2025-03-14"
            self._write(metadata / ndos_table.SESSIONS_FILE, sessions, ndos_table.COLUMNS)

            record = ndos_table.link_records(metadata)["sessions"][0]
            derived = record["derived"]

            # 14 Feb to 14 Mar is 28 days; nobody typed that number.
            self.assertEqual(derived["days_since_injection"]["value"], "28")
            self.assertEqual(derived["days_since_injection"]["status"], "computed")
            self.assertEqual(derived["age_days"]["value"], "132")
            # "viral injection" was mapped onto the controlled term.
            self.assertEqual(
                record["procedures"][0]["declared"]["procedure_type"]["value"],
                "injection",
            )
            self.assertEqual(record["procedures"][0]["days_before_session"], 28)

    def test_a_procedure_after_the_session_is_labelled_not_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))
            self._write(
                metadata / ndos_table.ANIMALS_FILE,
                [{"subject_id": "M01", "species": "mouse"}],
                ndos_table.ANIMAL_COLUMNS,
            )
            self._write(
                metadata / ndos_table.PROCEDURES_FILE,
                [{"procedure_id": "P009", "subject_id": "M01",
                  "procedure_date": "2025-06-01", "procedure_type": "perfusion"}],
                ndos_table.PROCEDURE_COLUMNS,
            )
            sessions = read_table(metadata / ndos_table.SESSIONS_FILE)
            for row in sessions:
                if row["observed_path"] == "2025-03-14/M01/ses-01":
                    row["subject_id"] = "M01"
                    row["session_date"] = "2025-03-14"
            self._write(metadata / ndos_table.SESSIONS_FILE, sessions, ndos_table.COLUMNS)

            record = ndos_table.link_records(metadata)["sessions"][0]

            self.assertEqual(record["procedures"][0]["relation"], "after")
            # A perfusion that happened later cannot be an elapsed interval.
            self.assertNotIn("days_since_perfusion", record.get("derived", {}))

    def test_a_session_naming_an_unknown_animal_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))
            self._write(
                metadata / ndos_table.ANIMALS_FILE,
                [{"subject_id": "M01"}],
                ndos_table.ANIMAL_COLUMNS,
            )
            sessions = read_table(metadata / ndos_table.SESSIONS_FILE)
            sessions[0]["subject_id"] = "GHOST"
            self._write(metadata / ndos_table.SESSIONS_FILE, sessions, ndos_table.COLUMNS)

            result = ndos_table.check_metadata(metadata)

            self.assertTrue(
                any("GHOST" in problem["message"] for problem in result["references"])
            )

    def test_a_procedure_for_an_unknown_animal_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))
            self._write(
                metadata / ndos_table.ANIMALS_FILE,
                [{"subject_id": "M01"}],
                ndos_table.ANIMAL_COLUMNS,
            )
            self._write(
                metadata / ndos_table.PROCEDURES_FILE,
                [{"procedure_id": "P001", "subject_id": "NOBODY",
                  "procedure_date": "2025-01-01", "procedure_type": "surgery"}],
                ndos_table.PROCEDURE_COLUMNS,
            )

            result = ndos_table.check_metadata(metadata)

            self.assertTrue(
                any("NOBODY" in problem["message"] for problem in result["references"])
            )

    def test_duplicate_animal_rows_are_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))
            self._write(
                metadata / ndos_table.ANIMALS_FILE,
                [{"subject_id": "M01"}, {"subject_id": "M01"}],
                ndos_table.ANIMAL_COLUMNS,
            )

            result = ndos_table.check_metadata(metadata)

            self.assertTrue(
                any("duplicate" in p["message"] for p in result["animals"]["problems"])
            )

    def test_procedure_dates_are_validated_like_any_other_date(self):
        with tempfile.TemporaryDirectory() as directory:
            metadata = self._build(Path(directory))
            self._write(
                metadata / ndos_table.ANIMALS_FILE,
                [{"subject_id": "M01"}],
                ndos_table.ANIMAL_COLUMNS,
            )
            self._write(
                metadata / ndos_table.PROCEDURES_FILE,
                [{"procedure_id": "P001", "subject_id": "M01",
                  "procedure_date": "14/02/2025", "procedure_type": "surgery"}],
                ndos_table.PROCEDURE_COLUMNS,
            )

            result = ndos_table.check_metadata(metadata)

            self.assertTrue(
                any("ambiguous" in p["message"] for p in result["procedures"]["problems"])
            )


class ProjectExportTests(unittest.TestCase):
    """Exporting metadata from a project built in the default link mode.

    A pilot run found steps 3 and 4 of the quickstart did not compose: the
    layout is symlinks, the scanner skipped symlinks, and export saw almost
    nothing.
    """

    def _project(self, base: Path) -> Path:
        import ndos_organize

        source = base / "lab" / "M01" / "2025_03_14"
        source.mkdir(parents=True)
        (source / "rec.dat").write_bytes(b"signal")
        (source / "0.avi").write_bytes(b"video")
        manifest = ndos_scan.scan(base / "lab", include_checksums=False, progress=False)
        project = base / "project"
        ndos_organize.apply_plan(
            ndos_organize.build_plan(manifest, project), progress=False
        )
        return project

    def test_a_link_built_project_is_recognised_as_one(self):
        with tempfile.TemporaryDirectory() as directory:
            project = self._project(Path(directory))
            self.assertTrue(ndos_table.looks_like_project(project))
            self.assertFalse(ndos_table.looks_like_project(Path(directory) / "lab"))

    def test_exporting_from_a_project_sees_the_linked_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = self._project(base)
            metadata = base / "metadata"

            manifest = ndos_table._load_manifest(project, quiet=True)

            # Without following links this found nothing to describe.
            self.assertGreaterEqual(manifest["file_count"], 2)

    def test_the_project_layout_is_used_rather_than_guessed_at(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = self._project(base)
            manifest = ndos_table._load_manifest(project, quiet=True)

            # <role>/<subject>/<session>/ is known, so it is not re-derived;
            # guessing read "raw_data" itself as the session.
            rows = ndos_table.group_sessions(manifest, group_depth=2, subject_depth=1)
            subjects = {row["observed_folder_subject"] for row in rows}
            self.assertIn("M01", subjects)

    def test_exporting_a_directory_does_not_checksum_it(self):
        # table export never reads a checksum. Computing them anyway cost
        # hours on a real drive and the result was discarded.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = base / "lab" / "M01" / "2025_03_14"
            source.mkdir(parents=True)
            (source / "rec.dat").write_bytes(b"signal")

            manifest = ndos_table._load_manifest(base / "lab", quiet=True)

            self.assertFalse(manifest["checksums"])
            for entry in manifest["files"]:
                self.assertNotIn("sha256", entry)


class SharedIdentificationTests(unittest.TestCase):
    """organize and table must agree about which animal a file belongs to.

    A pilot run reported six animals found only after passing depth flags; the
    defaults found one. Subject identification was implemented twice, and only
    one copy had been taught to read an animal out of a filename.
    """

    ARCHIVES = [
        "Gilberto/A3200/A3302-190809.zip",
        "Gilberto/A3200/A3213-210413.zip",
        "Gilberto/A3300/A3303/A3303-191021.zip",
    ]

    def _manifest(self):
        return {
            "source_root": "/drive",
            "files": [
                {
                    "path": path,
                    "name": path.split("/")[-1],
                    "extension": ".zip",
                    "size_bytes": 1000,
                    "modified": "2020-01-01T00:00:00Z",
                }
                for path in self.ARCHIVES
            ],
        }

    def test_the_defaults_find_every_animal(self):
        rows = ndos_table.group_sessions(self._manifest())
        subjects = {row["observed_folder_subject"] for row in rows}
        self.assertEqual(subjects, {"A3302", "A3213", "A3303"})

    def test_two_archives_in_one_folder_are_two_sessions(self):
        # Grouping by directory merged them and lost all but the first.
        rows = ndos_table.group_sessions(self._manifest())
        self.assertEqual(len(rows), 3)

    def test_table_and_organize_agree_on_the_subject(self):
        import ndos_organize

        manifest = self._manifest()
        from_table = {
            row["observed_folder_subject"]
            for row in ndos_table.group_sessions(manifest)
        }
        from_organize = {
            placement["subject"] for placement in ndos_organize.derive(manifest)
        }
        self.assertEqual(from_table, from_organize)

    def test_a_filename_stating_both_is_not_reported_as_a_guess(self):
        rows = ndos_table.group_sessions(self._manifest())
        for row in rows:
            self.assertEqual(row["observed_match"], "subject and session")

    def test_the_cohort_folder_is_not_mistaken_for_the_animal(self):
        rows = ndos_table.group_sessions(self._manifest())
        subjects = {row["observed_folder_subject"] for row in rows}
        self.assertNotIn("A3200", subjects)
        self.assertNotIn("A3300", subjects)

    def test_ordinary_folder_layouts_are_unaffected(self):
        manifest = {
            "source_root": "/lab",
            "files": [
                {
                    "path": f"M01/2025_03_14/{name}",
                    "name": name,
                    "extension": ".dat",
                    "size_bytes": 1,
                    "modified": "2025-03-14T00:00:00Z",
                }
                for name in ("a.dat", "b.dat")
            ],
        }
        rows = ndos_table.group_sessions(manifest)
        # Both files belong to one session, as before.
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["observed_file_count"], 2)
