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

    def test_the_masthead_reaches_every_page(self):
        """Navigation lives in the layout, so it cannot drift page to page."""
        layout = (DOCS / "_layouts" / "default.html").read_text(encoding="utf-8")
        for target in ("why.html", "specification.html", "quickstart.html",
                       "recipes.html", "roadmap.html", "contributing.html"):
            with self.subTest(target=target):
                self.assertIn(f"'/{target}'", layout, f"{target} is not linked")
                self.assertIn(
                    f"page.url == '/{target}'", layout,
                    f"{target} is never marked as the current page",
                )
        self.assertIn("https://github.com/Elnazkarami/N-DOS", layout)

    def test_no_page_carries_its_own_navigation(self):
        """It used to be pasted into every page, and looked like it."""
        for page in sorted(DOCS.rglob("*.md")):
            body = page.read_text(encoding="utf-8")
            with self.subTest(page=page.name):
                self.assertNotIn(
                    "[GitHub](https://github.com/Elnazkarami/N-DOS) ", body,
                    f"{page.name} still has a pasted navigation bar",
                )

    def test_the_reasoning_and_the_roadmap_are_published(self):
        """The site is not only the specification; these are its other halves."""
        for name, heading in (("why.md", "# Why N-DOS exists"),
                              ("roadmap.md", "# Roadmap")):
            served = DOCS / name
            self.assertTrue(served.is_file(), f"{name} is not published")
            self.assertIn(heading, served.read_text(encoding="utf-8"), name)

    def test_internal_links_stay_on_the_site(self):
        """A link to a page this site serves must not leave for GitHub.

        Sending a reader to raw Markdown on github.com when the rendered page
        exists two directories away is a worse site, not a safer one.
        """
        import re

        published = {
            target.replace(".md", ".html")
            for target in ("specification.md", "why.md", "roadmap.md",
                           "quickstart.md", "recipes.md", "contributing.md")
        }
        for page in sorted(DOCS.rglob("*.md")):
            body = page.read_text(encoding="utf-8")
            escaping = [
                link for link in re.findall(
                    r"https://github\.com/Elnazkarami/N-DOS/blob/main/([A-Za-z0-9_./-]+\.md)",
                    body,
                )
                if link.lower().replace(".md", ".html") in published
            ]
            self.assertEqual(
                escaping, [], f"{page.name} leaves the site for {escaping}"
            )

    def test_the_landing_page_quotes_output_it_does_not_invent(self):
        """The excerpt is read from the committed example, not retyped."""
        index = (DOCS / "index.md").read_text(encoding="utf-8")
        committed = (
            ROOT / "examples" / "cohort-demo" / "query-output.txt"
        ).read_text(encoding="utf-8")
        for line in ("Considered 4 sessions: 1 matched, 2 unresolved, 1 excluded.",
                     "CANNOT BE RULED OUT (2)"):
            self.assertIn(line, committed, line)
            self.assertIn(line, index, f"the landing page dropped: {line}")

    def test_the_link_preview_card_is_published(self):
        """A link posted anywhere shows this or it shows nothing."""
        for name in ("social-card.svg", "social-card.png",
                     "icon.svg", "icon.png"):
            served = DOCS / "assets" / name
            with self.subTest(asset=name):
                self.assertTrue(served.is_file(), f"{name} is not published")
                self.assertEqual(
                    served.read_bytes(),
                    (ROOT / "assets" / name).read_bytes(),
                    f"the published {name} differs from assets/{name}",
                )

    def test_the_card_png_matches_the_svg_it_was_rendered_from(self):
        """Catches an edited SVG whose PNG was never re-rendered.

        The two cannot be compared pixel for pixel without a renderer, but a
        size that no longer agrees is the mistake that actually happens.
        """
        import re
        import struct

        for stem, expected_scale in (("social-card", 1), ("icon", 3)):
            svg = (ROOT / "assets" / f"{stem}.svg").read_text(encoding="utf-8")
            declared = {
                key: int(re.search(rf'\b{key}="(\d+)"', svg).group(1))
                for key in ("width", "height")
            }
            png = (ROOT / "assets" / f"{stem}.png").read_bytes()
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n", stem)
            width, height = struct.unpack(">II", png[16:24])
            with self.subTest(asset=stem):
                self.assertEqual(
                    (width, height),
                    (declared["width"] * expected_scale,
                     declared["height"] * expected_scale),
                    f"assets/{stem}.png is {width}x{height}, but "
                    f"assets/{stem}.svg declares "
                    f"{declared['width']}x{declared['height']} — re-render it, "
                    "see assets/README.md",
                )

    def test_the_site_tells_jekyll_where_the_card_is(self):
        """The SEO tag cannot build a preview from a relative image."""
        config = (DOCS / "_config.yml").read_text(encoding="utf-8")
        self.assertIn("url: https://elnazkarami.github.io", config)
        self.assertIn("baseurl: /N-DOS", config)
        self.assertIn("image: /assets/social-card.png", config)
        self.assertIn("card: summary_large_image", config)

    def test_the_layout_carries_the_head_the_site_needs(self):
        """There is no theme, so the layout is the only place these exist."""
        layout = (DOCS / "_layouts" / "default.html").read_text(encoding="utf-8")
        for required in ("{% seo %}", "/assets/css/site.css",
                         "/assets/icon.svg", "/assets/icon.png",
                         "/assets/js/toc.js", 'name="viewport"'):
            with self.subTest(required=required):
                self.assertIn(required, layout)
        self.assertNotIn(
            "og:image", layout,
            "the SEO tag already emits this; two sets would compete",
        )

    def test_the_site_is_not_themed(self):
        """A themed site looks like the theme, which was the whole problem."""
        config = (DOCS / "_config.yml").read_text(encoding="utf-8")
        settings = [
            line for line in config.splitlines()
            if line.startswith(("theme:", "remote_theme:"))
        ]
        self.assertEqual(settings, [], "the site is still themed")
        self.assertIn("layout: default", config)

    def test_the_fonts_are_served_from_this_site(self):
        """Not from a font CDN, on a site whose claim is that data stays put.

        The stylesheet must also ask for every weight that is published, and
        publish every weight it asks for -- a missing file silently falls back
        to a system font, which is the thing this design is avoiding.
        """
        import re

        published = {
            path.name for path in (DOCS / "assets" / "fonts").iterdir()
            if path.suffix == ".woff2"
        }
        self.assertTrue(published, "no fonts are published")
        css = (DOCS / "assets" / "css" / "site.css").read_text(encoding="utf-8")
        asked = set(re.findall(r"\.\./fonts/([A-Za-z0-9.-]+\.woff2)", css))
        self.assertEqual(
            asked, published,
            "the stylesheet and the published fonts disagree",
        )
        for url in re.findall(r"url\(\"([^\"]+)\"\)", css):
            self.assertFalse(
                url.startswith("http"), f"{url} is fetched from elsewhere",
            )
        self.assertTrue(
            (DOCS / "assets" / "fonts" / "OFL.txt").is_file(),
            "IBM Plex is OFL-licensed and the licence must travel with it",
        )

    def test_nothing_points_at_the_domain_that_does_not_exist(self):
        for path in list(ROOT.glob("*.md")) + list(SCHEMAS.glob("*.json")):
            self.assertNotIn(
                "ndos.dev", path.read_text(encoding="utf-8"), path.name
            )


if __name__ == "__main__":
    unittest.main()
