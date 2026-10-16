"""The read-only promise, enforced rather than asserted.

RECIPES.md divides the commands into three groups and says the first writes
nothing at all. That is the central trust claim of the project -- a lab is
being asked to point this at irreplaceable data -- so it should be a test and
not a paragraph.
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ndos_init  # noqa: E402
import ndos_scan  # noqa: E402
import ndos_search  # noqa: E402
import ndos_table  # noqa: E402


def snapshot(root: Path):
    """Every byte and timestamp under a directory."""
    state = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            state[path.relative_to(root).as_posix() + "/"] = ("dir",)
            continue
        stat = path.stat()
        state[path.relative_to(root).as_posix()] = (
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_mode,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
    return state


class ReadOnlyCommandTests(unittest.TestCase):
    """Run the first group, then prove the project is untouched."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

        # The project under test, and a separate place for every output, so a
        # command writing where it was told does not count as a change.
        self.project = self.tmp / "study"
        self.out = self.tmp / "out"
        self.out.mkdir()

        ndos_init.initialize(self.project)
        raw, _ = ndos_init.add_session(self.project, "M123", "2025-03-14")
        (raw / "M123_20250314_raw.dat").write_bytes(b"signal" * 100)
        (raw / "notes.txt").write_text("CA1, rig 2\n", encoding="utf-8")

        manifest = ndos_scan.scan(
            self.project, include_checksums=True, progress=False,
            follow_symlinks=True,
        )
        self.manifest = self.out / "manifest.json"
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        ndos_table.export_metadata(manifest, self.out / "metadata")
        self.linked = self.out / "linked.json"
        self.linked.write_text(
            json.dumps(
                ndos_table.link_records(self.out / "metadata", include_empty=True)
            ),
            encoding="utf-8",
        )
        self.index = self.out / "search.db"
        ndos_search.build(self.project, self.index, quiet=True)

    def run_command(self, *args):
        result = subprocess.run(
            [sys.executable, str(ROOT / "ndos.py"), *args],
            capture_output=True, text=True, cwd=self.tmp,
        )
        # A command may legitimately exit non-zero -- validate on a
        # non-conforming project, search finding nothing -- so the exit code is
        # not the assertion. Crashing is.
        self.assertNotIn("Traceback", result.stderr, f"{args}\n{result.stderr}")
        return result

    def test_the_read_only_commands_change_nothing(self):
        before = snapshot(self.project)

        project = str(self.project)
        commands = [
            ("report", project),
            ("report", project, "--no-checksum"),
            ("scan", project),                      # no -o: writes nothing
            ("archive", "inspect", project, "-c", str(self.out / "arch.json")),
            ("organize", "plan", str(self.manifest), "-d", str(self.out / "plan")),
            ("tags", "list", project),
            ("tags", "get", str(self.project / "raw_data" / "M123" / "20250314"
                                / "M123_20250314_raw.dat")),
            ("query", str(self.linked), "-w", "file_count>=1"),
            ("prov", "list", "-d", str(self.out / "prov")),
            ("validate", project),
            ("convert", "bids", project, "-d", str(self.out / "bids")),
            ("convert", "nwb", project),
            ("search", "find", "CA1", "-i", str(self.index)),
            ("table", "check", str(self.out / "metadata")),
            ("protect", project, "--check"),
        ]
        for command in commands:
            with self.subTest(command=" ".join(command[:2])):
                self.run_command(*command)
                after = snapshot(self.project)
                self.assertEqual(
                    before, after,
                    f"`ndos {' '.join(command)}` changed the project",
                )

    def test_a_dry_run_of_a_writing_command_changes_nothing(self):
        """`sweep` without --apply and `protect` without --apply are plans."""
        before = snapshot(self.project)
        for command in (
            ("tags", "sweep", str(self.project)),
            ("tags", "sweep", str(self.project), "--include-untagged"),
            ("protect", str(self.project)),
        ):
            with self.subTest(command=" ".join(command[:2])):
                self.run_command(*command)
                self.assertEqual(
                    before, snapshot(self.project),
                    f"`ndos {' '.join(command)}` changed the project without --apply",
                )

    def test_indexing_for_search_writes_outside_the_project(self):
        before = snapshot(self.project)
        ndos_search.build(self.project, self.out / "again.db", quiet=True)
        self.assertEqual(before, snapshot(self.project))

    def test_the_recipes_groups_name_only_real_commands(self):
        """Every command in the three groups has to exist."""
        import ndos

        known = {name for name, _, _ in ndos.COMMANDS}
        recipes = (ROOT / "RECIPES.md").read_text(encoding="utf-8")
        section = recipes.split('## "Did it change my data?"')[1].split("##")[0]
        named = {
            word.strip("`,.")
            for word in section.replace("`", " ` ").split()
            if word.strip("`,.") in known
        }
        self.assertTrue(named)
        self.assertTrue(
            named <= known, f"RECIPES names commands that do not exist: {named - known}"
        )
        # The three that can change data must all be named in the third group.
        for command in ("organize", "tags", "protect"):
            self.assertIn(command, named, command)


if __name__ == "__main__":
    unittest.main()
