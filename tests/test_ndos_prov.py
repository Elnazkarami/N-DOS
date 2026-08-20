"""Tests for run provenance.

Two properties carry the weight here: a run that failed must still be
recorded and visibly marked, and credentials in the environment must never be
swept into a record that is meant to be shared.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ndos_prov import (
    load_records,
    record_run,
    render_trace,
    trace,
    write_record,
)

WRITER = (
    "import pathlib, sys;"
    "d = pathlib.Path(sys.argv[1]); d.mkdir(parents=True, exist_ok=True);"
    "[ (d / (p.stem + '_out.txt')).write_text(p.read_text().upper())"
    "  for p in sorted(pathlib.Path(sys.argv[2]).glob('*.txt')) ]"
)


class RecordTests(unittest.TestCase):
    def _lab(self, base: Path):
        raw = base / "raw"
        raw.mkdir(parents=True)
        (raw / "a.txt").write_text("alpha", encoding="utf-8")
        (raw / "b.txt").write_text("beta", encoding="utf-8")
        return raw, base / "out"

    def test_inputs_and_outputs_are_captured_with_checksums(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = self._lab(base)

            record = record_run(
                [sys.executable, "-c", WRITER, str(out), str(raw)],
                inputs=[raw], outputs=[out], name="convert", echo=False,
            )

            self.assertEqual(record["status"], "succeeded")
            self.assertEqual(len(record["used"]), 2)
            self.assertEqual(len(record["generated"]), 2)
            for artifact in record["used"] + record["generated"]:
                self.assertEqual(len(artifact["sha256"]), 64)
            self.assertTrue(
                all(a["change"] == "created" for a in record["generated"])
            )

    def test_a_rerun_that_changes_a_file_records_it_as_modified(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = self._lab(base)
            command = [sys.executable, "-c", WRITER, str(out), str(raw)]

            record_run(command, inputs=[raw], outputs=[out], echo=False)
            (raw / "a.txt").write_text("changed", encoding="utf-8")
            second = record_run(command, inputs=[raw], outputs=[out], echo=False)

            # Path.name rather than splitting on "/", which is not the
            # separator on Windows.
            changes = {Path(a["path"]).name: a["change"] for a in second["generated"]}
            self.assertEqual(changes.get("a_out.txt"), "modified")
            # b was rewritten identically, so it is not reported as changed.
            self.assertNotIn("b_out.txt", changes)

    def test_a_failing_run_is_still_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "out"

            record = record_run(
                [
                    sys.executable, "-c",
                    "import pathlib,sys;"
                    "d=pathlib.Path(sys.argv[1]);d.mkdir(parents=True,exist_ok=True);"
                    "(d/'partial.txt').write_text('half');sys.exit(3)",
                    str(out),
                ],
                outputs=[out], name="flaky", echo=False,
            )

            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["exit_code"], 3)
            # The partial output is recorded, which is the whole point.
            self.assertEqual(len(record["generated"]), 1)

    def test_a_command_that_cannot_start_is_recorded_as_failed(self):
        record = record_run(["definitely-not-a-real-command-xyz"], echo=False)
        self.assertEqual(record["status"], "failed")
        self.assertIn("error", record)

    def test_stdout_and_stderr_are_captured(self):
        record = record_run(
            [sys.executable, "-c", "import sys;print('out');print('err',file=sys.stderr)"],
            echo=False,
        )
        self.assertIn("out", record["stdout"]["text"])
        self.assertIn("err", record["stderr"]["text"])

    def test_very_large_output_is_truncated_rather_than_stored_whole(self):
        record = record_run(
            [sys.executable, "-c", "print('x' * 100000)"], echo=False
        )
        self.assertTrue(record["stdout"]["truncated"])
        self.assertLess(len(record["stdout"]["text"]), 100000)
        self.assertGreater(record["stdout"]["total_bytes"], 100000 - 1)

    def test_an_empty_command_is_rejected(self):
        with self.assertRaises(ValueError):
            record_run([])


class EnvironmentSafetyTests(unittest.TestCase):
    """Provenance is meant to be shared, so it must not collect credentials."""

    def test_environment_variables_are_not_captured_by_default(self):
        import os

        os.environ["NDOS_TEST_SECRET"] = "sk-do-not-record"
        try:
            record = record_run([sys.executable, "-c", "pass"], echo=False)
            self.assertNotIn("variables", record["environment"])
            self.assertNotIn("sk-do-not-record", json.dumps(record))
        finally:
            del os.environ["NDOS_TEST_SECRET"]

    def test_only_explicitly_named_variables_are_captured(self):
        import os

        os.environ["NDOS_TEST_SECRET"] = "sk-do-not-record"
        os.environ["NDOS_TEST_WANTED"] = "v2"
        try:
            record = record_run(
                [sys.executable, "-c", "pass"],
                record_env=["NDOS_TEST_WANTED"], echo=False,
            )
            variables = record["environment"]["variables"]
            self.assertEqual(variables, {"NDOS_TEST_WANTED": "v2"})
            self.assertNotIn("sk-do-not-record", json.dumps(record))
        finally:
            del os.environ["NDOS_TEST_SECRET"]
            del os.environ["NDOS_TEST_WANTED"]

    def test_anonymous_mode_omits_the_machine_and_the_person(self):
        record = record_run([sys.executable, "-c", "pass"], echo=False, anonymous=True)
        self.assertNotIn("hostname", record["environment"])
        self.assertNotIn("user", record["environment"])
        # Still enough to reproduce the run.
        self.assertIn("python_version", record["environment"])


class TraceTests(unittest.TestCase):
    def _pipeline(self, base: Path) -> Path:
        raw, mid, out = base / "raw", base / "mid", base / "out"
        raw.mkdir(parents=True)
        (raw / "a.txt").write_text("alpha", encoding="utf-8")
        provenance = base / "provenance"

        first = record_run(
            [sys.executable, "-c", WRITER, str(mid), str(raw)],
            inputs=[raw], outputs=[mid], name="stage-one", echo=False,
        )
        write_record(first, provenance)
        second = record_run(
            [sys.executable, "-c", WRITER, str(out), str(mid)],
            inputs=[mid], outputs=[out], name="stage-two", echo=False,
        )
        write_record(second, provenance)
        return provenance

    def test_a_result_traces_back_through_every_stage_to_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            provenance = self._pipeline(base)
            target = base / "out" / "a_out_out.txt"

            result = trace(target, provenance)

            self.assertEqual(result["record_count"], 2)
            stage_two = result["tree"]["produced_by"][0]
            self.assertEqual(stage_two["name"], "stage-two")
            stage_one = stage_two["used"][0]["produced_by"][0]
            self.assertEqual(stage_one["name"], "stage-one")
            # The end of the chain is data nothing recorded produced.
            self.assertIn("origin", stage_one["used"][0])

    def test_an_untracked_file_is_reported_as_raw_not_as_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            provenance = self._pipeline(base)
            stray = base / "stray.txt"
            stray.write_text("nothing made me", encoding="utf-8")

            result = trace(stray, provenance)

            self.assertIn("origin", result["tree"])

    def test_a_run_is_expanded_once_however_many_files_it_produced(self):
        # Otherwise a stage producing a hundred files renders a hundred times.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = base / "raw", base / "out"
            raw.mkdir(parents=True)
            for name in ("a", "b", "c"):
                (raw / f"{name}.txt").write_text(name, encoding="utf-8")
            provenance = base / "provenance"
            write_record(
                record_run(
                    [sys.executable, "-c", WRITER, str(out), str(raw)],
                    inputs=[raw], outputs=[out], name="fan-out", echo=False,
                ),
                provenance,
            )
            combined = base / "combined"
            write_record(
                record_run(
                    [sys.executable, "-c", WRITER, str(combined), str(out)],
                    inputs=[out], outputs=[combined], name="combine", echo=False,
                ),
                provenance,
            )

            text = render_trace(trace(combined / "a_out_out.txt", provenance))

            self.assertEqual(text.count("$ "), 2 + text.count("inputs shown above"))
            self.assertIn("inputs shown above", text)

    def test_tracing_with_no_records_says_so_rather_than_failing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            result = trace(base / "nothing.txt", base / "provenance")
            self.assertEqual(result["record_count"], 0)
            self.assertIn("origin", result["tree"])

    def test_a_failed_run_is_marked_in_the_rendered_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            out = base / "out"
            provenance = base / "provenance"
            write_record(
                record_run(
                    [
                        sys.executable, "-c",
                        "import pathlib,sys;"
                        "d=pathlib.Path(sys.argv[1]);d.mkdir(parents=True,exist_ok=True);"
                        "(d/'partial.txt').write_text('half');sys.exit(1)",
                        str(out),
                    ],
                    outputs=[out], name="broken", echo=False,
                ),
                provenance,
            )

            text = render_trace(trace(out / "partial.txt", provenance))

            self.assertIn("FAILED", text)
            self.assertIn("✗", text)


class StorageTests(unittest.TestCase):
    def test_records_round_trip_through_the_provenance_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            provenance = Path(directory) / "provenance"
            record = record_run([sys.executable, "-c", "pass"], name="one", echo=False)
            path = write_record(record, provenance)

            self.assertTrue(path.is_file())
            loaded = load_records(provenance)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["run_id"], record["run_id"])

    def test_a_missing_directory_yields_no_records_rather_than_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_records(Path(directory) / "absent"), [])

    def test_records_validate_against_the_published_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed; NDOS core stays stdlib-only")

        schema_path = (
            Path(__file__).resolve().parent.parent / "schemas" / "provenance.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            raw, out = base / "raw", base / "out"
            raw.mkdir(parents=True)
            (raw / "a.txt").write_text("alpha", encoding="utf-8")

            for anonymous in (False, True):
                jsonschema.validate(
                    record_run(
                        [sys.executable, "-c", WRITER, str(out), str(raw)],
                        inputs=[raw], outputs=[out], name="convert",
                        echo=False, anonymous=anonymous,
                    ),
                    schema,
                )
            jsonschema.validate(
                record_run([sys.executable, "-c", "import sys;sys.exit(2)"], echo=False),
                schema,
            )


if __name__ == "__main__":
    unittest.main()
