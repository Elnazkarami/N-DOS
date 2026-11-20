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
    ("QUICKSTART.md", "quickstart.md", "Quickstart"),
    ("RECIPES.md", "recipes.md", "When a guess is wrong"),
    ("CONTRIBUTING.md", "contributing.md", "Contributing"),
    ("examples/cohort-demo/README.md", "examples/cohort-demo.md",
     "Worked example: a cohort query"),
    ("examples/conflicting-records/README.md", "examples/conflicting-records.md",
     "Worked example: two records that disagree"),
)

#: A schema is served at exactly the path its own $id claims. That is the
#: whole point: an $id that does not resolve is a contract pointing nowhere.
SCHEMA_BASE = "https://elnazkarami.github.io/N-DOS/schemas/"


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


def _front_matter(title: str, body: str) -> str:
    """Jekyll needs a header; the Markdown below it is untouched."""
    # A relative link that worked in the repository does not work on the site,
    # where the files sit at different paths. Absolute links to GitHub do.
    body = re.sub(
        r"\]\((?!https?://|#)([A-Za-z0-9_./-]+\.md)\)",
        r"](https://github.com/Elnazkarami/N-DOS/blob/main/\1)",
        body,
    )
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
            _front_matter(title, source.read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        written.append(target_name)

    for source, target in _schema_targets().items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        written.append(str(target.relative_to(DOCS)))

    (DOCS / "_config.yml").write_text(
        "# Built by scripts/build_docs.py. Do not edit docs/ by hand: it is\n"
        "# regenerated from the canonical files and a test checks it matches.\n"
        "title: N-DOS\n"
        "description: >-\n"
        "  A shared language for animal neuroscience data, and the tooling\n"
        "  that makes following it practical.\n"
        "theme: jekyll-theme-primer\n"
        "exclude: [README.md]\n"
        "include: [schemas]\n",
        encoding="utf-8",
    )
    written.append("_config.yml")

    (DOCS / "index.md").write_text(_landing(), encoding="utf-8")
    written.append("index.md")
    return sorted(written)


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
on, a lab frequently can't read its own.

```bash
pip install ndos
```

## The standard

**[The N-DOS specification](specification.html)** — directory structure, how
subjects and sessions are identified, how files are named, what metadata an
experiment carries, and how each value is known: observed, declared, computed,
or checked and genuinely unknown.

A standard nobody can comply with is just a PDF, so it ships with the tools
that make complying with it practical, and with the means to bring data that
predates it to the standard.

## Start here

- **[Quickstart](quickstart.html)** — about fifteen minutes, and it will not
  move or change your data.
- **[When a guess is wrong](recipes.html)** — what to do when NDOS reads your
  layout incorrectly, which on some layout it will.
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

## Elsewhere

- [Repository](https://github.com/Elnazkarami/N-DOS)
- [Package](https://pypi.org/project/ndos/)
- [DOI](https://doi.org/10.5281/zenodo.23167365)
- [Questions and discussion](https://neurostars.org/t/36467)

NDOS hands off to BIDS and NWB rather than replacing them, and does not claim
conformance it cannot demonstrate.
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
