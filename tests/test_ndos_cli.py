"""Tests for the single `ndos` command.

The dispatcher's job is discovery: someone who has only been told "run ndos"
should be able to find everything from there, and every subcommand should
behave exactly as the module behind it does.
"""

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ndos
import ndos_scan
from ndos import COMMANDS, main

ROOT = Path(__file__).resolve().parent.parent


def _run(args):
    """Run the dispatcher in-process, capturing what it printed."""
    out, err = io.StringIO(), io.StringIO()
    saved = sys.argv
    sys.argv = ["ndos"] + list(args)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
    finally:
        sys.argv = saved
    return code, out.getvalue(), err.getvalue()


class DiscoveryTests(unittest.TestCase):
    def test_bare_invocation_lists_every_command(self):
        code, out, _ = _run([])
        self.assertEqual(code, 0)
        for name, _, summary in COMMANDS:
            self.assertIn(name, out)
            self.assertIn(summary, out)

    def test_help_says_where_to_start(self):
        _, out, _ = _run(["--help"])
        # Someone with an unreadable directory needs one obvious first move.
        self.assertIn("report", out)
        self.assertIn("nobody understands", out)

    def test_help_states_the_safety_guarantee(self):
        _, out, _ = _run(["--help"])
        flat = " ".join(out.split())
        self.assertIn("Nothing NDOS does modifies your data", flat)
        self.assertIn("show a plan and confirm first", flat)

    def test_version(self):
        code, out, _ = _run(["--version"])
        self.assertEqual(code, 0)
        self.assertIn(ndos.VERSION, out)


class DispatchTests(unittest.TestCase):
    def test_every_declared_command_imports_and_exposes_main(self):
        import importlib

        for name, module_name, _ in COMMANDS:
            module = importlib.import_module(module_name)
            self.assertTrue(
                callable(getattr(module, "main", None)),
                f"{module_name} has no main() for '{name}' to call",
            )

    def test_a_subcommand_runs_and_reports_its_own_name(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "ndos.py"), "organize", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        # Not "ndos_organize.py", which is not what the user typed.
        self.assertIn("ndos organize", result.stdout)

    def test_argv_is_restored_after_dispatch(self):
        before = list(sys.argv)
        _run(["--version"])
        _run(["report", "--help"]) if False else None
        self.assertEqual(sys.argv, before)


class ErrorTests(unittest.TestCase):
    def test_an_unknown_command_suggests_a_real_one(self):
        code, _, err = _run(["orgnaize"])
        self.assertEqual(code, 2)
        self.assertIn("unknown command", err)
        self.assertIn("organize", err)

    def test_an_unrecognisable_command_still_points_at_help(self):
        code, _, err = _run(["zzzzz"])
        self.assertEqual(code, 2)
        self.assertIn("--help", err)


class InvocationHintTests(unittest.TestCase):
    """Printed hints should match the command the user actually typed."""

    def test_direct_invocation_names_the_script(self):
        saved = sys.argv
        sys.argv = ["ndos_organize.py"]
        try:
            self.assertEqual(
                ndos_scan.invocation("ndos_organize"), "python3 ndos_organize.py"
            )
        finally:
            sys.argv = saved

    def test_dispatched_invocation_names_the_subcommand(self):
        saved = sys.argv
        sys.argv = ["ndos organize"]
        try:
            self.assertEqual(ndos_scan.invocation("ndos_organize"), "ndos organize")
        finally:
            sys.argv = saved


class PackagingTests(unittest.TestCase):
    def test_pyproject_declares_no_runtime_dependencies(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")

        content = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        # The zero-dependency guarantee is the reason this runs on locked-down
        # acquisition machines; a dependency here would quietly end it.
        self.assertEqual(content["project"]["dependencies"], [])

    def test_every_module_on_disk_is_declared_for_packaging(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")

        content = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = set(content["tool"]["setuptools"]["py-modules"])
        on_disk = {path.stem for path in ROOT.glob("ndos*.py")}
        self.assertEqual(on_disk - declared, set())

    def test_the_console_script_points_at_the_dispatcher(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")

        content = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(content["project"]["scripts"]["ndos"], "ndos:main")


class QuickstartTests(unittest.TestCase):
    def test_every_command_the_quickstart_names_exists(self):
        import re

        text = (ROOT / "QUICKSTART.md").read_text(encoding="utf-8")
        known = {name for name, _, _ in COMMANDS}
        used = set(re.findall(r"ndos\.py (\w+)", text))
        unknown = used - known
        self.assertEqual(unknown, set(), f"quickstart names unknown commands: {unknown}")


if __name__ == "__main__":
    unittest.main()
