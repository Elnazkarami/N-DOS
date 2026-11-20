"""The published site must be what the repository says.

A site that kept its own copy of the specification would be a second place
for the standard to live, and the second place is the one that goes stale.
Everything under docs/ is generated; these tests are what stop it drifting.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SCHEMAS = ROOT / "schemas"
SITE = "https://elnazkarami.github.io/N-DOS/"


class PublishedSiteTests(unittest.TestCase):
    def test_the_site_is_current(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_docs.py"), "--check"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_schema_is_served_at_the_identity_it_claims(self):
        """An $id that does not resolve is a contract pointing nowhere.

        Before this, all five declared https://ndos.dev/..., a domain with no
        DNS record at all.
        """
        for source in sorted(SCHEMAS.glob("*.json")):
            identity = json.loads(source.read_text(encoding="utf-8"))["$id"]
            with self.subTest(schema=source.name):
                self.assertTrue(
                    identity.startswith(SITE),
                    f"{source.name} claims {identity}, which this site cannot serve",
                )
                served = DOCS / identity[len(SITE):]
                self.assertTrue(
                    served.is_file(),
                    f"{source.name} claims {identity} and nothing is published there",
                )
                self.assertEqual(
                    json.loads(served.read_text(encoding="utf-8")),
                    json.loads(source.read_text(encoding="utf-8")),
                    f"{served.name} differs from the schema it publishes",
                )

    def test_a_schema_resolves_as_json(self):
        """Served with a .json suffix so it arrives as JSON, not as a blob."""
        for source in sorted(SCHEMAS.glob("*.json")):
            identity = json.loads(source.read_text(encoding="utf-8"))["$id"]
            self.assertTrue(identity.endswith(".json"), identity)

    def test_the_specification_is_published_whole(self):
        published = (DOCS / "specification.md").read_text(encoding="utf-8")
        canonical = (ROOT / "SPECIFICATION.md").read_text(encoding="utf-8")
        # Front matter is added; the body must be untouched apart from links.
        self.assertIn("The N-DOS standard", published)
        for heading in ("## 1. Project structure", "## 7. Metadata",
                        "## Conformance"):
            self.assertIn(heading, published, heading)
        self.assertEqual(
            canonical.count("## "), published.count("## "),
            "the published specification has a different number of sections",
        )

    def test_no_relative_markdown_links_survive(self):
        """They resolve in the repository and 404 on the site."""
        import re

        for page in sorted(DOCS.rglob("*.md")):
            body = page.read_text(encoding="utf-8")
            relative = re.findall(r"\]\((?!https?://|#)([^)]+\.md)\)", body)
            self.assertEqual(
                relative, [], f"{page.name} links to {relative} relatively"
            )

    def test_nothing_points_at_the_domain_that_does_not_exist(self):
        for path in list(ROOT.glob("*.md")) + list(SCHEMAS.glob("*.json")):
            self.assertNotIn(
                "ndos.dev", path.read_text(encoding="utf-8"), path.name
            )


if __name__ == "__main__":
    unittest.main()
