#!/usr/bin/env python3
"""Assemble the published site from the files that are already canonical.

The specification, the schemas and the worked examples live in the repository
and are checked by tests. A site that kept its own copies of them would be a
second place for the standard to live, and the second place is always the one
that goes stale.

So nothing here is written by hand except the landing page. Everything else is
copied from its canonical location, and `--check` fails if what is published
has drifted from what is true -- the same arrangement that keeps the shipped
interface and the committed example outputs honest.

    python3 scripts/build_docs.py            # write docs/
    python3 scripts/build_docs.py --check    # is docs/ current?

GitHub Pages builds the result with Jekyll, so this needs no dependencies and
no local toolchain.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

#: Pages served from Markdown that already exists. (source, destination, title)
PAGES: Tuple[Tuple[str, str, str], ...] = (
    ("SPECIFICATION.md", "specification.md", "The N-DOS standard"),
    ("WHY.md", "why.md", "Why N-DOS exists"),
    ("ROADMAP.md", "roadmap.md", "Roadmap"),
    ("QUICKSTART.md", "quickstart.md", "Quickstart"),
    ("RECIPES.md", "recipes.md", "When a guess is wrong"),
    ("CONTRIBUTING.md", "contributing.md", "Contributing"),
    ("examples/cohort-demo/README.md", "examples/cohort-demo.md",
     "Worked example: a cohort query"),
    ("examples/conflicting-records/README.md", "examples/conflicting-records.md",
     "Worked example: two records that disagree"),
)

#: The link preview card and the site icon, copied as they are. The SVGs are
#: the source and the PNGs are rendered from them; see assets/README.md.
ASSETS = ("social-card.svg", "social-card.png", "icon.svg", "icon.png")

#: A schema is served at exactly the path its own $id claims. That is the
#: whole point: an $id that does not resolve is a contract pointing nowhere.
SCHEMA_BASE = "https://elnazkarami.github.io/N-DOS/schemas/"

#: Open Graph needs an absolute URL, so the site's own address is stated once.
SITE = "https://elnazkarami.github.io/N-DOS"


def _schema_targets() -> Dict[Path, Path]:
    """Where each schema must be published, taken from its own $id."""
    targets = {}
    for source in sorted((ROOT / "schemas").glob("*.json")):
        identity = json.loads(source.read_text(encoding="utf-8"))["$id"]
        if not identity.startswith(SCHEMA_BASE):
            raise SystemExit(
                f"{source.name} has $id {identity!r}, which is not under "
                f"{SCHEMA_BASE}. The site can only serve what the schema "
                "claims to be."
            )
        targets[source] = DOCS / "schemas" / identity[len(SCHEMA_BASE):]
    return targets


#: The masthead's navigation, in order. The page you are on is marked, not
#: linked to itself. "Home" is absent on purpose: the wordmark is the way
#: back, the way it is on every site that has one.
NAV: Tuple[Tuple[str, str], ...] = (
    ("Why", "why.html"),
    ("The standard", "specification.html"),
    ("Quickstart", "quickstart.html"),
    ("When a guess is wrong", "recipes.html"),
    ("Roadmap", "roadmap.html"),
    ("Contributing", "contributing.html"),
)


def _nav_html() -> str:
    """The masthead links, written once here rather than twice in HTML."""
    lines = []
    for label, target in NAV:
        here = ("{% if page.url == '/" + target + "' %}"
                ' aria-current="page"{% endif %}')
        lines.append(
            f"          <a href=\"{{{{ '/{target}' | relative_url }}}}\""
            f"{here}>{label}</a>"
        )
    lines.append(
        '          <a class="out" href="https://github.com/Elnazkarami/N-DOS">'
        "GitHub&nbsp;&#8599;</a>"
    )
    return "\n".join(lines)


def _published_pages() -> Dict[str, str]:
    """Which repository Markdown file is served where on this site."""
    return {
        source: target.replace(".md", ".html")
        for source, target, _ in PAGES
    }


def _front_matter(title: str, body: str, depth: int = 0) -> str:
    """Jekyll needs a header; the Markdown below it keeps its own words.

    Links are the one thing that must change. A relative link that worked in
    the repository does not work on the site, where the files sit at different
    paths -- so a link to a page this site publishes becomes a link to that
    page, and everything else becomes an absolute link to GitHub.
    """
    served = _published_pages()
    up = "../" * depth

    def _retarget(match: "re.Match[str]") -> str:
        target = match.group(1)
        if target in served:
            return f"]({up}{served[target]})"
        return f"](https://github.com/Elnazkarami/N-DOS/blob/main/{target})"

    body = re.sub(r"\]\((?!https?://|#)([A-Za-z0-9_./-]+\.md)\)", _retarget, body)
    return f"---\ntitle: {json.dumps(title)}\n---\n\n{body}"


def build() -> List[str]:
    if DOCS.exists():
        shutil.rmtree(DOCS)
    written: List[str] = []

    for source_name, target_name, title in PAGES:
        source = ROOT / source_name
        if not source.is_file():
            raise SystemExit(f"missing source page: {source_name}")
        target = DOCS / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            _front_matter(
                title,
                source.read_text(encoding="utf-8"),
                depth=target_name.count("/"),
            ),
            encoding="utf-8",
        )
        written.append(target_name)

    for source, target in _schema_targets().items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        written.append(str(target.relative_to(DOCS)))

    for name in ASSETS:
        source = ROOT / "assets" / name
        if not source.is_file():
            raise SystemExit(f"missing asset: assets/{name}")
        target = DOCS / "assets" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        written.append(f"assets/{name}")

    for source, target in _site_files().items():
        if not source.is_file():
            raise SystemExit(f"missing site file: {source.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.name == "layout.html":
            marker = "<!--NAV-->"
            text = source.read_text(encoding="utf-8")
            if marker not in text:
                raise SystemExit(
                    "site/layout.html has no <!--NAV--> marker, so the "
                    "navigation in build_docs.py has nowhere to go."
                )
            target.write_text(text.replace(marker, _nav_html()),
                              encoding="utf-8")
        else:
            shutil.copy2(source, target)
        written.append(str(target.relative_to(DOCS)))

    (DOCS / "_config.yml").write_text(
        "# Built by scripts/build_docs.py. Do not edit docs/ by hand: it is\n"
        "# regenerated from the canonical files and a test checks it matches.\n"
        "title: N-DOS\n"
        "description: >-\n"
        "  A shared language for animal neuroscience data, and the tooling\n"
        "  that makes following it practical.\n"
        "# No theme: the layout, the stylesheet and the fonts are in site/\n"
        "# and are copied here. A themed site looks like the theme.\n"
        "plugins: [jekyll-seo-tag]\n"
        "exclude: [README.md]\n"
        "include: [schemas]\n"
        "\n"
        "# Jekyll's SEO tag builds the link preview from these. Without an\n"
        "# absolute url it cannot, and a posted link renders as a bare URL.\n"
        f"url: {SITE.rsplit('/', 1)[0]}\n"
        f"baseurl: /{SITE.rsplit('/', 1)[1]}\n"
        "twitter:\n"
        "  card: summary_large_image\n"
        "defaults:\n"
        "  - scope:\n"
        "      path: \"\"\n"
        "    values:\n"
        "      layout: default\n"
        "      image: /assets/social-card.png\n",
        encoding="utf-8",
    )
    written.append("_config.yml")

    (DOCS / "index.md").write_text(_landing(), encoding="utf-8")
    written.append("index.md")
    return sorted(written)


def _cohort_excerpt() -> str:
    """The committed query output, down to the part that makes the point.

    Read from the example rather than retyped, so the landing page cannot
    claim output the code does not produce.
    """
    source = ROOT / "examples" / "cohort-demo" / "query-output.txt"
    lines = source.read_text(encoding="utf-8").splitlines()
    try:
        stop = next(i for i, line in enumerate(lines)
                    if line.startswith("EXCLUDED"))
    except StopIteration:
        raise SystemExit(
            "examples/cohort-demo/query-output.txt no longer has an EXCLUDED "
            "section; the landing page excerpt needs rechecking."
        )
    # Drop the banner at the top and the divider above EXCLUDED.
    return "\n".join(lines[3:stop - 1]).rstrip()


def _site_files() -> Dict[Path, Path]:
    """The hand-written site: a layout, a stylesheet, a script, the fonts.

    The default GitHub Pages theme is recognisable at a glance, and a project
    asking laboratories to adopt its standard should not look like it was
    assembled from the first option offered. So the theme is gone and these
    four things replace it. The fonts are served from here rather than from a
    font CDN, which would hand every visitor's address to a third party on a
    site whose claim is that nothing leaves your machine.
    """
    site = ROOT / "site"
    files = {
        site / "layout.html": DOCS / "_layouts" / "default.html",
        site / "style.css": DOCS / "assets" / "css" / "site.css",
        site / "toc.js": DOCS / "assets" / "js" / "toc.js",
    }
    for font in sorted((site / "fonts").iterdir()):
        if font.is_file():
            files[font] = DOCS / "assets" / "fonts" / font.name
    return files


def _landing() -> str:
    schemas = "\n".join(
        f"- [`{identity[len(SCHEMA_BASE):]}`]({identity}) — "
        f"{json.loads(source.read_text(encoding='utf-8')).get('title', source.stem)}"
        for source, identity in sorted(
            (s, json.loads(s.read_text(encoding="utf-8"))["$id"])
            for s in (ROOT / "schemas").glob("*.json")
        )
    )
    return _front_matter(
        "N-DOS",
        f"""# N-DOS

**A shared language for animal neuroscience data, and the tooling that makes
following it practical.**

Every neuroscience lab invents its own way of organising data. Often every lab
member invents their own. None of them can read each other's — and two years
on, a lab frequently can't read its own. Meanwhile the standards that do exist
— BIDS, NWB, DANDI — all begin at publication, which is years after the point
where the data was made and where it was lost.

N-DOS is a specification for the part in between, plus the tools that make
complying with it practical, plus the means to bring data that predates it up
to it. It hands off to BIDS and NWB rather than replacing them.

```bash
pip install ndos
```

Zero runtime dependencies — Python 3.9+ and the standard library. Nothing
changes on your disk unless you name one of the three commands that can, and
each shows a plan and waits.

→ **[Why N-DOS exists](why.html)**, the reasoning and the evidence behind it.

## Three answers, not two

The clearest way to show what N-DOS is for. Four sessions, four animals, one
question. This output is committed in the repository and regenerated by a
test, so it is what the code actually prints:

```
{_cohort_excerpt()}
```

A session whose species nobody wrote down is **not** a session known not to be
a mouse. A tool that conflates those hands you a biased cohort without saying
so. Every value N-DOS stores records how it is known — observed, declared,
computed, or checked and genuinely unknown — and a blank is none of them.

## The standard

**[The N-DOS specification](specification.html)** — directory structure, how
subjects and sessions are identified, how files are named, what metadata an
experiment carries, and how each value is known.

A standard nobody can comply with is just a PDF. So the specification defines
three things a project can be, and the tools withhold nothing at the lower
levels:

| | What it means | What it costs you |
| --- | --- | --- |
| **N-DOS-readable** | N-DOS can inventory, search and query it in whatever organisation it already has | Nothing. No layout, no metadata, no permission to change anything |
| **N-DOS-conformant** | It satisfies every MUST: the directories, the subject-then-session shape, the identifier rules | A reorganisation you choose to do, with a plan shown first |
| **N-DOS-traceable** | It also records how its facts are known — evidence, flags, provenance | Metadata somebody has to fill in |

A lab with an inherited archive starts at **readable** and may reasonably stay
there. Most of what N-DOS does is available at that level.

## What the tools do

- **Recovery.** Inventories heterogeneous storage, reads inside archives
  without extracting them, and proposes a structure — showing the rule and the
  evidence behind every guess, so you can correct it rather than trust it.
- **Search.** Finds the word you remember — `CA1`, `GCaMP`, a construct name —
  across filenames, lab notes, protocol files and spreadsheets, including
  `.docx` and `.xlsx`. A hit in a surgery log reports which animals it names,
  which is what turns a document into a route to the recordings.
- **Discovery.** Builds cohorts from incomplete records and returns matched,
  excluded, and *cannot be ruled out*.
- **Traceability.** Records what produced a result, and traces a figure back
  through the commands and parameters to the raw files it came from.
- **Verification.** Checks a transferred dataset arrived intact, and says
  *inconclusive* rather than passing something it could not read.

All of it also runs in a window: `ndos gui`, served by the package itself,
bound to this machine only. Nothing is uploaded anywhere.

## Start here

- **[Quickstart](quickstart.html)** — about fifteen minutes, and it will not
  move or change your data.
- **[When a guess is wrong](recipes.html)** — what to do when N-DOS reads your
  layout incorrectly, which on some layout it will.
- **[Roadmap](roadmap.html)** — what exists, what is next, and what has been
  deliberately left undone.
- **[Contributing](contributing.html)** — including the bounded tasks worth
  volunteering for.

## Worked examples

Both carry committed output, regenerated by a test, so what you read is what
the code prints.

- **[A cohort query](examples/cohort-demo.html)** — four animals, one
  question, and three answers: matched, excluded, and *cannot be ruled out*.
- **[Two records that disagree](examples/conflicting-records.html)** — where
  every link is valid and the identity is still wrong.

## Schema contracts

Versioned JSON Schema, served at the identity each one declares:

{schemas}

## Looking for pilot testers

**No external lab has completed a pilot yet.** That is the single most useful
thing a reader of this page can change.

If you have a directory of lab data nobody fully understands any more, that is
exactly what this needs to meet. It takes about fifteen minutes and **will not
move or change your data**. No data needs sharing — every form asks about the
*shape* of your directories, never their contents.

| | |
| --- | --- |
| **[Tell us how it went →](https://github.com/Elnazkarami/N-DOS/issues/new?template=3-pilot-feedback.yml)** | Even "I gave up at step three" is a result |
| **[It read my folders wrongly →](https://github.com/Elnazkarami/N-DOS/issues/new?template=1-layout-misread.yml)** | The most useful report there is |
| **[Something is broken →](https://github.com/Elnazkarami/N-DOS/issues/new?template=2-bug.yml)** | A crash or a wrong answer |

## Elsewhere

- [Repository](https://github.com/Elnazkarami/N-DOS) — and the
  [README](https://github.com/Elnazkarami/N-DOS#readme), which documents every
  command
- [Package on PyPI](https://pypi.org/project/ndos/)
- [DOI](https://doi.org/10.5281/zenodo.23167365) — cite the version you ran
- [Questions and discussion](https://neurostars.org/t/36467) on Neurostars

**Status: 0.2.0.** The software works and is tested on Linux, macOS and
Windows. The specification is a draft at 0.1 and will change in response to
labs using it. N-DOS claims no conformance to BIDS or NWB that it cannot
demonstrate.

Apache-2.0. By [Elnaz Alikarami](https://github.com/Elnazkarami).
""",
    )


def check() -> int:
    if not DOCS.is_dir():
        print("docs/ has not been built. Run: python3 scripts/build_docs.py",
              file=sys.stderr)
        return 1

    existing = {
        p.relative_to(DOCS).as_posix()
        for p in DOCS.rglob("*") if p.is_file()
    }
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "docs"
        shutil.copytree(DOCS, staged)
        build()
        fresh = {
            p.relative_to(DOCS).as_posix()
            for p in DOCS.rglob("*") if p.is_file()
        }
        differing = sorted(
            name for name in fresh & existing
            if not filecmp.cmp(DOCS / name, staged / name, shallow=False)
        )
        missing = sorted(fresh - existing)
        extra = sorted(existing - fresh)

    if differing or missing or extra:
        print("docs/ is not what the canonical files produce:", file=sys.stderr)
        for name in differing:
            print(f"  changed: {name}", file=sys.stderr)
        for name in missing:
            print(f"  missing: {name}", file=sys.stderr)
        for name in extra:
            print(f"  stale:   {name}", file=sys.stderr)
        print("Rebuild it: python3 scripts/build_docs.py", file=sys.stderr)
        return 1

    print(f"docs/ matches its sources ({len(fresh)} files)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true",
        help="report whether docs/ is current, writing nothing permanent",
    )
    args = parser.parse_args(argv)
    if args.check:
        return check()
    written = build()
    print(f"wrote {len(written)} files to docs/")
    for name in written:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
