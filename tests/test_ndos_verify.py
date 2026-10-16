"""Tests for ndos_verify.

The question is not whether two dictionaries can be compared. It is whether
the verdict is honest: a comparison that found no mismatch has not verified a
transfer if it had nothing to compare against.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ndos_scan  # noqa: E402
import ndos_verify  # noqa: E402
from ndos_verify import FAILED, INCONCLUSIVE, VERIFIED  # noqa: E402


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.source = self.tmp / "source"
        session = self.source / "raw_data" / "M123" / "20250314"
        session.mkdir(parents=True)
        (session / "M123_20250314_raw.dat").write_bytes(b"signal" * 500)
        (session / "M123_20250314_raw.meta").write_text("rate=30000\n", encoding="utf-8")
        (session / "tags.json").write_text('{"files": {}}', encoding="utf-8")

        sorting = session / "kilosort"
        sorting.mkdir()
        for name in ("params.py", "spike_times.npy", "spike_clusters.npy",
                     "amplitudes.npy"):
            (sorting / name).write_text(f"contents of {name}\n", encoding="utf-8")

    def manifest(self, checksums=True):
        return ndos_scan.scan(
            self.source, include_checksums=checksums, progress=False,
            follow_symlinks=False,
        )

    def copy(self, name="dest"):
        import shutil

        destination = self.tmp / name
        shutil.copytree(self.source, destination)
        return destination

    # -- the three verdicts ------------------------------------------------

    def test_an_identical_destination_verifies(self):
        result = ndos_verify.verify(self.manifest(), self.copy())
        self.assertEqual(result["result"], VERIFIED)
        self.assertEqual(result["counts"]["verified"], result["counts"]["source_files"])

    def test_a_missing_file_fails(self):
        destination = self.copy()
        (destination / "raw_data" / "M123" / "20250314" / "M123_20250314_raw.dat").unlink()
        result = ndos_verify.verify(self.manifest(), destination)
        self.assertEqual(result["result"], FAILED)
        self.assertEqual(result["counts"]["missing"], 1)

    def test_changed_bytes_at_the_same_size_fail(self):
        """The case a file count and a byte total both miss."""
        before = self.manifest()
        destination = self.copy()
        target = destination / "raw_data" / "M123" / "20250314" / "M123_20250314_raw.dat"
        data = bytearray(target.read_bytes())
        data[0] ^= 0xFF
        target.write_bytes(bytes(data))

        result = ndos_verify.verify(before, destination)
        self.assertEqual(result["result"], FAILED)
        self.assertEqual(result["counts"]["changed"], 1)
        self.assertIn("checksum", result["changed"][0]["reason"])

    def test_changed_bytes_at_a_different_size_fail(self):
        before = self.manifest()
        destination = self.copy()
        target = destination / "raw_data" / "M123" / "20250314" / "M123_20250314_raw.dat"
        target.write_bytes(b"truncated")
        self.assertEqual(ndos_verify.verify(before, destination)["result"], FAILED)

    def test_a_manifest_without_checksums_is_inconclusive_not_verified(self):
        """This is the whole point of the third verdict.

        Nothing is wrong, and nothing has been proven either. Reporting that
        as success would be the mistake this project argues against.
        """
        result = ndos_verify.verify(self.manifest(checksums=False), self.copy())
        self.assertEqual(result["result"], INCONCLUSIVE)
        self.assertEqual(result["counts"]["changed"], 0)
        self.assertEqual(result["counts"]["missing"], 0)
        self.assertTrue(result["counts"]["unverifiable"])

    def test_a_size_change_fails_even_without_checksums(self):
        """Absent a hash, a different size is still a definite change."""
        before = self.manifest(checksums=False)
        destination = self.copy()
        target = destination / "raw_data" / "M123" / "20250314" / "M123_20250314_raw.dat"
        target.write_bytes(b"short")
        result = ndos_verify.verify(before, destination)
        self.assertEqual(result["result"], FAILED)

    def test_a_per_file_missing_hash_is_not_covered_by_the_global_flag(self):
        """`checksums: true` does not guarantee every entry carries one."""
        before = self.manifest()
        self.assertTrue(before["checksums"])
        before["files"][0].pop("sha256")
        result = ndos_verify.verify(before, self.copy())
        self.assertEqual(result["result"], INCONCLUSIVE)

    # -- extras ------------------------------------------------------------

    def test_an_unexpected_file_is_reported_not_failed(self):
        destination = self.copy()
        (destination / "transfer.log").write_text("rsync said ok\n", encoding="utf-8")
        result = ndos_verify.verify(self.manifest(), destination)
        self.assertEqual(result["result"], VERIFIED)
        self.assertEqual(result["counts"]["unexpected"], 1)

    def test_an_unexpected_file_fails_under_strict_extra(self):
        destination = self.copy()
        (destination / "transfer.log").write_text("rsync said ok\n", encoding="utf-8")
        result = ndos_verify.verify(
            self.manifest(), destination, strict_extra=True
        )
        self.assertEqual(result["result"], FAILED)

    # -- the parts specific to this data ----------------------------------

    def test_an_incomplete_sorting_is_grouped_and_named(self):
        destination = self.copy()
        sorting = destination / "raw_data" / "M123" / "20250314" / "kilosort"
        (sorting / "spike_times.npy").unlink()

        result = ndos_verify.verify(self.manifest(), destination)
        self.assertEqual(result["result"], FAILED)
        self.assertEqual(len(result["incomplete"]), 1)
        group = result["incomplete"][0]
        self.assertIn("Kilosort", group["tool"])
        self.assertEqual(group["source_file_count"], 4)
        self.assertEqual(group["verified"], 3)
        self.assertEqual([Path(p).name for p in group["missing"]], ["spike_times.npy"])

    def test_a_wholly_absent_sorting_is_not_reported_as_incomplete(self):
        """Gone is a different problem from half-arrived."""
        import shutil

        destination = self.copy()
        shutil.rmtree(destination / "raw_data" / "M123" / "20250314" / "kilosort")
        result = ndos_verify.verify(self.manifest(), destination)
        self.assertEqual(result["result"], FAILED)
        self.assertEqual(result["incomplete"], [])
        self.assertEqual(result["counts"]["missing"], 4)

    def test_a_record_left_behind_is_called_out(self):
        destination = self.copy()
        (destination / "raw_data" / "M123" / "20250314" / "tags.json").unlink()
        result = ndos_verify.verify(self.manifest(), destination)
        self.assertEqual(
            [Path(p).name for p in result["records_left_behind"]], ["tags.json"]
        )

    def test_a_changed_modification_time_alone_does_not_fail(self):
        """Copy tools legitimately change mtimes while preserving bytes."""
        import os

        before = self.manifest()
        destination = self.copy()
        target = destination / "raw_data" / "M123" / "20250314" / "M123_20250314_raw.dat"
        os.utime(target, (0, 0))
        result = ndos_verify.verify(before, destination)
        self.assertEqual(result["result"], VERIFIED)
        self.assertEqual(result["counts"]["modification_times_changed"], 1)

    def test_an_excluded_path_does_not_make_a_clean_transfer_inconclusive(self):
        """Otherwise one .DS_Store makes every verdict useless."""
        before = self.manifest()
        before.setdefault("skipped", []).append(
            {"path": ".DS_Store", "reason": "excluded",
             "detail": "matched an exclude pattern"}
        )
        self.assertEqual(ndos_verify.verify(before, self.copy())["result"], VERIFIED)

    def test_an_unreadable_path_does_make_it_inconclusive(self):
        before = self.manifest()
        before.setdefault("skipped", []).append(
            {"path": "locked.dat", "reason": "unreadable-file", "detail": "permission"}
        )
        self.assertEqual(
            ndos_verify.verify(before, self.copy())["result"], INCONCLUSIVE
        )

    # -- contracts ---------------------------------------------------------

    def test_verifying_changes_nothing_at_either_end(self):
        import hashlib

        def snapshot(root):
            return {
                p.relative_to(root).as_posix(): (
                    p.stat().st_size, p.stat().st_mtime_ns,
                    hashlib.sha256(p.read_bytes()).hexdigest(),
                )
                for p in sorted(root.rglob("*")) if p.is_file()
            }

        destination = self.copy()
        before_source, before_dest = snapshot(self.source), snapshot(destination)
        ndos_verify.verify(self.manifest(), destination)
        self.assertEqual(before_source, snapshot(self.source))
        self.assertEqual(before_dest, snapshot(destination))

    def test_the_exit_codes_match_the_verdicts(self):
        self.assertEqual(ndos_verify.EXIT[VERIFIED], 0)
        self.assertEqual(ndos_verify.EXIT[FAILED], 1)
        self.assertEqual(ndos_verify.EXIT[INCONCLUSIVE], 3)
        # 2 stays an error, as in every other module.
        self.assertNotIn(2, ndos_verify.EXIT.values())

    def test_the_command_line_reports_each_verdict(self):
        manifest = self.tmp / "before.json"
        manifest.write_text(json.dumps(self.manifest()), encoding="utf-8")
        destination = self.copy()

        def run(*extra):
            return subprocess.run(
                [sys.executable, str(ROOT / "ndos_verify.py"), str(manifest),
                 str(destination), *extra],
                capture_output=True, text=True,
            )

        clean = run()
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertIn("VERIFIED", clean.stdout)

        (destination / "raw_data" / "M123" / "20250314" / "tags.json").unlink()
        broken = run()
        self.assertEqual(broken.returncode, 1)
        self.assertIn("FAILED", broken.stdout)

    def test_a_missing_manifest_is_an_error_not_a_verdict(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "ndos_verify.py"),
             str(self.tmp / "absent.json"), str(self.source)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("no manifest", result.stderr)

    def test_the_result_matches_its_published_schema(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is not installed")

        schema = json.loads(
            (ROOT / "schemas" / "verification.schema.json").read_text(encoding="utf-8")
        )
        destination = self.copy()
        (destination / "raw_data" / "M123" / "20250314" / "kilosort"
         / "spike_times.npy").unlink()
        for document in (
            ndos_verify.verify(self.manifest(), self.copy("clean")),
            ndos_verify.verify(self.manifest(), destination),
            ndos_verify.verify(self.manifest(checksums=False), self.copy("third")),
        ):
            jsonschema.validate(document, schema)

    def test_the_dispatcher_knows_about_it(self):
        import ndos

        self.assertIn("verify", [name for name, _, _ in ndos.COMMANDS])


class IntegrityOfTheVerifierTests(unittest.TestCase):
    """The verifier is an integrity tool, so its own inputs have to be sound.

    Every case here produced a confident-looking answer from a record that
    could not support one.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.destination = self.tmp / "dest"
        self.destination.mkdir()

    def test_a_manifest_of_nothing_cannot_verify_a_transfer(self):
        """It reported VERIFIED, which is the contradiction this is built on.

        Reachable by scanning an empty mount, or by excluding everything.
        """
        result = ndos_verify.verify(
            {"source_root": "/mnt/empty", "checksums": True, "files": []},
            self.destination,
        )
        self.assertEqual(result["result"], INCONCLUSIVE)
        self.assertIn("nothing to verify", result["unverifiable"][0]["reason"])

    def test_a_path_appearing_twice_is_refused(self):
        """One entry silently won, and the result did not say which."""
        with self.assertRaises(ndos_verify.ManifestError) as caught:
            ndos_verify.verify(
                {"files": [
                    {"path": "a.dat", "sha256": "a" * 64},
                    {"path": "a.dat", "sha256": "b" * 64},
                ]},
                self.destination,
            )
        self.assertIn("twice", str(caught.exception))

    def test_an_entry_without_a_path_is_refused_in_words(self):
        """It raised a bare KeyError from inside the comparison."""
        with self.assertRaises(ndos_verify.ManifestError):
            ndos_verify.verify({"files": [{"size_bytes": 1}]}, self.destination)

    def test_something_that_is_not_a_digest_is_refused(self):
        with self.assertRaises(ndos_verify.ManifestError) as caught:
            ndos_verify.verify(
                {"files": [{"path": "a.dat", "sha256": "probably"}]},
                self.destination,
            )
        self.assertIn("sha256", str(caught.exception))

    def test_a_malformed_shape_is_refused(self):
        for document in (
            {"files": "not a list"},
            {"files": [["not", "an", "object"]]},
            {"files": [{"path": "a", "size_bytes": -1}]},
            {"files": [{"path": "   "}]},
        ):
            with self.subTest(document=str(document)[:40]):
                with self.assertRaises(ndos_verify.ManifestError):
                    ndos_verify.verify(document, self.destination)

    def test_a_manifest_version_it_cannot_read_is_refused(self):
        with self.assertRaises(ndos_verify.ManifestError):
            ndos_verify.verify(
                {"manifest_version": "9.9", "files": []}, self.destination
            )

    def test_the_version_the_scanner_writes_is_accepted(self):
        import ndos_scan

        self.assertIn(
            ndos_scan.MANIFEST_VERSION, ndos_verify.SUPPORTED_MANIFEST_VERSIONS
        )

    def test_a_refusal_exits_as_an_error_not_as_a_verdict(self):
        manifest = self.tmp / "bad.json"
        manifest.write_text(
            json.dumps({"files": [{"path": "a"}, {"path": "a"}]}), encoding="utf-8"
        )
        result = subprocess.run(
            [sys.executable, str(ROOT / "ndos_verify.py"), str(manifest),
             str(self.destination)],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertNotIn("VERIFIED", result.stdout)


class HonestReportingTests(unittest.TestCase):
    """What the report claims has to match what was established."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        self.source = self.tmp / "source"
        self.sorting = self.source / "raw_data" / "M1" / "20250101" / "kilosort"
        self.sorting.mkdir(parents=True)
        for name in ("params.py", "spike_times.npy", "spike_clusters.npy",
                     "amplitudes.npy"):
            (self.sorting / name).write_text(f"contents {name}\n", encoding="utf-8")

        metadata = self.source / "metadata"
        metadata.mkdir()
        for name in ("animals.csv", "procedures.csv", "sessions.csv"):
            (metadata / name).write_text("subject_id\nM1\n", encoding="utf-8")

    def manifest(self):
        return ndos_scan.scan(
            self.source, include_checksums=True, progress=False, follow_symlinks=False
        )

    def copy(self):
        import shutil

        destination = self.tmp / "dest"
        shutil.copytree(self.source, destination)
        return destination

    def test_a_corrupted_file_is_not_counted_as_verified(self):
        """It said "3 of 4 verified" with one missing and one corrupted."""
        before = self.manifest()
        destination = self.copy()
        sorting = destination / "raw_data" / "M1" / "20250101" / "kilosort"
        (sorting / "spike_times.npy").unlink()
        (sorting / "amplitudes.npy").write_text("CORRUPTED\n", encoding="utf-8")

        result = ndos_verify.verify(before, destination)
        group = next(g for g in result["incomplete"] if "kilosort" in g["directory"])
        self.assertEqual(group["source_file_count"], 4)
        self.assertEqual(len(group["missing"]), 1)
        self.assertEqual(len(group["changed"]), 1)
        self.assertEqual(group["verified"], 2, "a corrupted file counted as verified")

        text = ndos_verify.render(result)
        self.assertIn("2 of 4 source files verified", text)
        self.assertIn("changed:", text)

    def test_losing_a_metadata_table_is_reported_as_a_record_left_behind(self):
        """Those three files are where the human decisions live."""
        before = self.manifest()
        destination = self.copy()
        (destination / "metadata" / "animals.csv").unlink()

        result = ndos_verify.verify(before, destination)
        self.assertIn(
            "animals.csv",
            [Path(p).name for p in result["records_left_behind"]],
        )

    def test_all_three_tables_count_as_records(self):
        for name in ("animals.csv", "procedures.csv", "sessions.csv"):
            self.assertTrue(ndos_verify._is_sidecar(name), name)

    def test_an_excluded_scope_is_stated_rather_than_implied(self):
        """`--exclude '*.bin'` must not read as a clean bill of health."""
        before = self.manifest()
        before.setdefault("skipped", []).extend(
            {"path": f"raw_data/M1/20250101/run{n}.bin", "reason": "excluded",
             "detail": "matched an exclude pattern"}
            for n in range(412)
        )
        result = ndos_verify.verify(before, self.copy())

        self.assertEqual(result["result"], VERIFIED)
        self.assertEqual(result["counts"]["excluded_from_scope"], 412)
        text = ndos_verify.render(result)
        self.assertIn("within the scope this manifest declares", text)
        self.assertIn("412", text)

    def test_the_closing_line_does_not_read_as_the_files_being_fine(self):
        """"Nothing was changed at either end" sat under a CHANGED heading."""
        before = self.manifest()
        destination = self.copy()
        target = destination / "raw_data" / "M1" / "20250101" / "kilosort" / "params.py"
        target.write_text("CORRUPTED\n", encoding="utf-8")

        text = ndos_verify.render(ndos_verify.verify(before, destination))
        self.assertNotIn("Nothing was changed", text)
        self.assertIn("NDOS did not modify either location", text)
        self.assertIn("Re-copy", text)

    def test_inconclusive_is_not_told_to_re_copy(self):
        """Re-copying does not supply checksums the manifest never had."""
        before = ndos_scan.scan(
            self.source, include_checksums=False, progress=False, follow_symlinks=False
        )
        text = ndos_verify.render(ndos_verify.verify(before, self.copy()))
        self.assertIn("Re-copying will not resolve this", text)
        self.assertIn("ndos scan", text)




if __name__ == "__main__":
    unittest.main()
