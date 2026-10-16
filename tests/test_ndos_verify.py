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


if __name__ == "__main__":
    unittest.main()
