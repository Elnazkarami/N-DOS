"""The committed example must be the output the code actually produces.

A README showing a result the tool no longer gives is worse than no README:
it is the first thing a visitor reads and the last thing anyone re-runs.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ndos_query  # noqa: E402
import ndos_table  # noqa: E402

DEMO = ROOT / "examples" / "cohort-demo"
CONSTRAINTS = ["species=mouse", "sex=F", "target_region~CA1"]


class CohortDemoTests(unittest.TestCase):
    def setUp(self):
        self.linked = ndos_table.link_records(DEMO / "metadata", include_empty=True)
        self.result = ndos_query.run_query(
            self.linked, [ndos_query.parse_constraint(c) for c in CONSTRAINTS]
        )

    def test_the_committed_output_is_what_the_code_produces(self):
        committed = (DEMO / "query-output.txt").read_text(encoding="utf-8")
        produced = ndos_query.render(self.result)
        self.assertEqual(
            produced.strip(), committed.strip(),
            "examples/cohort-demo/query-output.txt is stale. Regenerate it:\n"
            "  python3 ndos_table.py check examples/cohort-demo/metadata "
            "--emit /tmp/l.json --include-empty\n"
            "  python3 ndos_query.py /tmp/l.json -w species=mouse -w sex=F "
            "-w 'target_region~CA1' > examples/cohort-demo/query-output.txt",
        )

    def test_the_demo_shows_all_three_outcomes(self):
        """A demo that only matched would not demonstrate the argument."""
        counts = self.result["counts"]
        self.assertEqual(counts["considered"], 4)
        self.assertEqual(counts["matched"], 1)
        self.assertEqual(counts["excluded"], 1)
        self.assertEqual(counts["unresolved"], 2)

    def test_it_distinguishes_checked_unknown_from_never_entered(self):
        """The distinction §7 requires, shown rather than asserted."""
        reasons = {
            row["ndos_id"]: " ".join(m.get("reason", "") for m in row["missing"])
            for row in self.result["unresolved"]
        }
        m103 = reasons["ndos-0000000003"]
        m104 = reasons["ndos-0000000004"]
        self.assertIn("could not be determined", m103)
        self.assertIn("never entered", m104)
        self.assertNotEqual(m103, m104)

    def test_the_rat_is_excluded_by_evidence_not_by_absence(self):
        excluded = self.result["excluded"]
        self.assertEqual(len(excluded), 1)
        self.assertIn("species=mouse", excluded[0]["failed"])

    def test_the_readme_table_matches_the_outcome(self):
        """The example's own prose has to agree with the example."""
        prose = (DEMO / "README.md").read_text(encoding="utf-8")
        for animal, outcome in (
            ("M101", "matched"), ("M102", "excluded"),
            ("M103", "cannot be ruled out"), ("M104", "cannot be ruled out"),
        ):
            line = next(l for l in prose.splitlines() if l.startswith(f"| `{animal}`"))
            self.assertIn(outcome, line, animal)

    def test_the_documented_commands_run(self):
        with tempfile.TemporaryDirectory() as directory:
            linked = Path(directory) / "linked.json"
            check = subprocess.run(
                [sys.executable, str(ROOT / "ndos_table.py"), "check",
                 str(DEMO / "metadata"), "--emit", str(linked), "--include-empty"],
                capture_output=True, text=True,
            )
            self.assertTrue(linked.is_file(), check.stderr)
            query = subprocess.run(
                [sys.executable, str(ROOT / "ndos_query.py"), str(linked),
                 "-w", "species=mouse", "-w", "sex=F", "-w", "target_region~CA1"],
                capture_output=True, text=True,
            )
            self.assertIn("CANNOT BE RULED OUT", query.stdout)


if __name__ == "__main__":
    unittest.main()
