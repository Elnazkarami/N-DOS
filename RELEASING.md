# Releasing NDOS

Publishing is automated, but it needs a one-time setup on PyPI that only the
project owner can do. Nothing here stores an API token: PyPI verifies with
GitHub directly that a release came from this repository's workflow.

## One-time setup

Do this once, on PyPI and again on TestPyPI if you want to rehearse.

1. Sign in at <https://pypi.org> (and <https://test.pypi.org>).
2. Go to **Your projects → Publishing**, or, since `ndos` does not exist on
   PyPI yet, **Account settings → Publishing → Add a pending publisher**.
3. Fill in exactly:

   | Field | Value |
   | --- | --- |
   | PyPI project name | `ndos` |
   | Owner | `Elnazkarami` |
   | Repository name | `N-DOS` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` (or `testpypi` on TestPyPI) |

4. In this repository, under **Settings → Environments**, create an
   environment named `pypi`, and `testpypi` if you are rehearsing. Adding
   yourself as a required reviewer on `pypi` means a publish waits for you to
   approve it, which is worth doing: a version number on PyPI is permanent.

That is the whole setup. No secret is created, and nothing needs rotating.

## Rehearsing on TestPyPI

Worth doing once, so the first real publish is not the first attempt.

**Actions → publish → Run workflow**, choose `testpypi`. Then check it
installs from there:

```bash
python3 -m venv /tmp/rehearse
/tmp/rehearse/bin/pip install --index-url https://test.pypi.org/simple/ ndos
/tmp/rehearse/bin/ndos --version
```

## Publishing a release

1. Decide the version and set it in `pyproject.toml`. NDOS is pre-1.0, so
   interfaces may change between minor versions; say so in the notes when they
   do.
2. Update `ndos.py`'s `VERSION` to match.
3. Commit, merge to `main`.
4. Draft a release on GitHub tagged `vX.Y.Z`, matching the version exactly.
   Publishing it runs the workflow.

The workflow refuses to publish if the tag and `pyproject.toml` disagree. That
guard exists because a version number on PyPI cannot be reused, edited, or
taken back — only yanked, which leaves it visible.

Before uploading anything it runs the full test suite, builds both
distributions, checks they render, installs the wheel in a clean environment,
and fails if the install pulled in any third-party package. That last check is
the zero-dependency promise, and a release is exactly where it would quietly
break.

## What ships

The wheel carries the modules and nothing else. The source distribution also
carries the schemas — the published contracts of the standard — along with
`QUICKSTART.md`, `RECIPES.md`, the licence and the test suite. `legacy/` is
excluded: those scripts are superseded and should not travel with a release.

## After publishing

- Confirm `pip install ndos` works from a clean environment.
- If the release is meant to be citable, archive the tag on Zenodo and add the
  DOI to `CITATION.cff` and the README.

## About the DOI

A Zenodo DOI does not require a published paper, and does not wait for one.
Software is cited in its own right: you link this repository to Zenodo once,
and every GitHub release from then on is archived and assigned a DOI
automatically.

Doing it early is worth more than doing it neatly. Pilot users can cite the
exact version they tested, a bug report can name a version that will still
exist in five years, and when the paper is written it cites the software DOI
rather than the other way round.

Zenodo issues two: one for the project as a whole and one per release. Put the
project DOI in the README, and the release DOI in `CITATION.cff`.
