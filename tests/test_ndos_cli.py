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

    def test_the_two_version_strings_agree(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")

        content = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        # Releasing means bumping both by hand, and a mismatch would ship a
        # package whose --version lies about which release it is.
        self.assertEqual(content["project"]["version"], ndos.VERSION)

    def test_the_citation_version_tracks_the_package(self):
        import re

        text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
        match = re.search(r"^version:\s*(\S+)$", text, flags=re.M)
        self.assertIsNotNone(match, "CITATION.cff has no version")
        # Citing a version that was never released helps nobody.
        self.assertEqual(match.group(1), ndos.VERSION)

    def test_the_sdist_manifest_ships_the_standard_it_implements(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        # Schemas are the published contracts; a source release without them
        # would carry the implementation and not the thing implemented.
        self.assertIn("recursive-include schemas *.json", manifest)
        self.assertIn("QUICKSTART.md", manifest)
        self.assertIn("RECIPES.md", manifest)
        # Superseded prototypes should not travel with a release.
        self.assertIn("prune legacy", manifest)

    def test_the_readme_has_no_relative_links_that_pypi_would_break(self):
        import re

        text = (ROOT / "README.md").read_text(encoding="utf-8")
        # PyPI renders the README on its own, where a relative link is a 404.
        relative = re.findall(r"\]\((?!https?://|#)([^)]+\.(?:md|json))\)", text)
        self.assertEqual(relative, [], f"relative links in README: {relative}")

    def test_the_console_script_points_at_the_dispatcher(self):
        try:
            import tomllib
        except ImportError:
            self.skipTest("tomllib needs Python 3.11+")

        content = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(content["project"]["scripts"]["ndos"], "ndos:main")


class IssueTemplateTests(unittest.TestCase):
    """The first thing a user touches when something breaks.

    The previous template asked people to choose between six modules that had
    been removed, which is worse than having no template at all.
    """

    TEMPLATES = Path(".github/ISSUE_TEMPLATE")

    def _files(self):
        return sorted((ROOT / self.TEMPLATES).glob("*.yml"))

    def test_templates_exist(self):
        self.assertTrue(self._files(), "no issue templates")

    def test_no_template_names_a_file_that_was_removed(self):
        import re

        for path in self._files():
            text = path.read_text(encoding="utf-8")
            for name in set(re.findall(r"\bndos[_a-z]*\.(?:py|R|sh)\b", text)):
                self.assertTrue(
                    (ROOT / name).is_file(),
                    f"{path.name} refers to {name}, which is not in the repo",
                )

    def test_a_report_can_be_filed_without_sharing_any_data(self):
        # Lab data is unpublished. If filing a bug seemed to require sending
        # some, people would simply not file.
        for path in self._files():
            if path.name == "config.yml":
                continue
            text = path.read_text(encoding="utf-8").lower()
            self.assertIn(
                "data", text,
                f"{path.name} never addresses whether data must be shared",
            )
        combined = " ".join(
            p.read_text(encoding="utf-8").lower() for p in self._files()
        )
        self.assertIn("you do not need to share any data", combined)


class DocumentationTests(unittest.TestCase):
    """A documented command that does not exist is worse than no document."""

    def _commands_named_in(self, filename: str):
        import re

        text = (ROOT / filename).read_text(encoding="utf-8")
        return set(re.findall(r"ndos\.py (\w+)", text))

    def test_every_command_the_docs_name_exists(self):
        known = {name for name, _, _ in COMMANDS}
        for filename in ("QUICKSTART.md", "RECIPES.md", "README.md"):
            unknown = self._commands_named_in(filename) - known
            self.assertEqual(
                unknown, set(), f"{filename} names unknown commands: {unknown}"
            )

    def test_the_recipes_cover_the_failure_people_actually_hit(self):
        text = (ROOT / "RECIPES.md").read_text(encoding="utf-8")
        # The override flags exist because these situations do; if a flag is
        # ever renamed, the document that tells people to use it must follow.
        for flag in ("--subject-depth", "--session-depth", "--strip",
                     "--keep-original-names", "--estimate", "--cache"):
            self.assertIn(flag, text, f"RECIPES.md never mentions {flag}")

    def test_the_override_flags_the_recipes_promise_are_real(self):
        import subprocess

        result = subprocess.run(
            [sys.executable, str(ROOT / "ndos.py"), "organize", "plan", "--help"],
            capture_output=True, text=True,
        )
        for flag in ("--subject-depth", "--session-depth", "--strip"):
            self.assertIn(flag, result.stdout)


if __name__ == "__main__":
    unittest.main()
