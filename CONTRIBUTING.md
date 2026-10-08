# Contributing to NDOS

The most useful thing you can send is **a folder layout NDOS reads wrongly**.
That is worth more than a feature, because the inference rules have met too
few real lab conventions to be trusted yet, and every lab names things
differently.

You do not need to write code to do it.

## Running the tests

Standard library only. No environment, no install.

```bash
git clone https://github.com/Elnazkarami/N-DOS.git ndos && cd ndos
python3 -m unittest discover -s tests
```

One test suite checks manifests against the published JSON Schemas and skips
itself if `jsonschema` is absent. `pip install jsonschema` to run those too.
CI runs the whole suite on Python 3.9 and 3.13 across Linux, macOS and
Windows, plus a job that imports and runs every module against a **bare**
interpreter — that job is what keeps the zero-dependency promise honest, so a
change that adds an import will fail it.

## Which module owns what

| Module | Owns |
| --- | --- |
| `ndos_scan.py` | Walking a tree, checksums, manifests, resumable caches |
| `ndos_report.py` | Categorising files, inferring structure, the inventory report |
| `ndos_archive.py` | Reading inside ZIP and TAR without extracting |
| `ndos_organize.py` | **What a subject and a session look like**, and rebuilding the layout |
| `ndos_table.py` | The metadata tables, vocabularies, synonyms, linking |
| `ndos_search.py` | The full-text index and search |
| `ndos_query.py` | Constraints, and the matched / excluded / unresolved decision |
| `ndos_tags.py` | Flags, and planning a sweep |
| `ndos_prov.py` | Recording a run, and tracing an output back |
| `ndos_convert.py` | BIDS and NWB handoff |
| `ndos_validate.py` | Conformance against `SPECIFICATION.md` |
| `ndos_init.py` | Creating a project, and the directory list the checker reads |
| `ndos_gui.py` | The local server. **No scientific decisions live here** |

Two of those are load-bearing and easy to break:

- **`ndos_organize.py` decides what a subject folder is.** `ndos_table` and
  `ndos_search` call into it rather than deciding for themselves, because they
  once disagreed and produced two different answers to one question. If you
  are teaching NDOS a new naming convention, it goes here.
- **`ndos_init.DIRECTORIES` is what `ndos_validate` checks against**, on
  purpose, so the thing that creates a project and the thing that validates
  one cannot disagree about the standard.

## Reporting a layout NDOS read wrongly

The [layout-misread form](https://github.com/Elnazkarami/N-DOS/issues/new?template=1-layout-misread.yml)
asks about the *shape* of your directories, never their contents. No data is
shared.

If you can, include a **synthetic reproduction** — the same folder names with
empty files:

```bash
mkdir -p repro/2025-03-14/Mouse_7/run1
touch repro/2025-03-14/Mouse_7/run1/amplifier.dat
python3 ndos.py organize plan repro -d /tmp/out      # shows what it inferred
```

Paste the plan. The "why" line on each placement is the rule that fired, which
is usually enough to find the bug.

## Bounded tasks, if you want to write code

These are real, self-contained, and have obvious done conditions.

1. **Add a naming convention to `ndos_organize.SUBJECT_PATTERNS` or
   `DATE_PATTERNS`.** Bring a fixture: a directory of empty files under
   `tests/fixtures/`, plus a test asserting the subject and session NDOS
   infers. Patterns already cover `M123`, `sub-01`, `mouse_7`, `2025-03-14`
   and `20250314`; there are many more in the wild.

2. **Add a file format to `ndos_report.CATEGORIES`.** If your rig writes
   something NDOS reports as "Other", add the extension to the right category
   and a case to `tests/test_ndos_report.py`. Cheap, and it improves the first
   thing every user sees.

3. **Add a text format to `ndos_search.TEXT_EXTENSIONS`**, or a reader to
   `ndos_search.extract_text`. `.docx` and `.xlsx` are read by treating them
   as ZIPs of XML; `.odt` and `.rtf` could be too. **`.pdf` cannot** without a
   dependency, which NDOS does not take — if you want PDFs, the interesting
   question is how to do it as an optional extra rather than in core.

4. **Add a synonym to `ndos_table`'s maps.** If your lab writes `C57` for
   `C57BL/6J`, or `2P` for calcium imaging, the normalisation belongs in
   `SPECIES_SYNONYMS`, `SESSION_TYPE_SYNONYMS` or
   `PROCEDURE_TYPE_SYNONYMS`. One line plus a test.

## House rules

- **No runtime dependencies in core.** This is not a style preference: NDOS
  has to run on acquisition machines where nothing can be installed. Optional
  extras are fine as separate packages.
- **Read-only unless asked.** A command that writes shows a plan and waits.
  A command that changes what is already on disk does both and says so.
- **One answer per question.** If two modules would both decide what a session
  is, one of them calls the other. This has been the source of more bugs here
  than anything else.
- **Label inference as inference.** A guess presented as a fact is the failure
  mode this project exists to prevent.
- **Tests explain why.** A test name saying what broke, and a docstring saying
  why it matters, is worth more than coverage.
- If you change a vocabulary, a file type or a required directory,
  `SPECIFICATION.md` has to change with it — there are tests that fail if it
  does not.

## Questions

Open a [discussion](https://github.com/Elnazkarami/N-DOS/discussions). Saying
"I gave up at step three" is a genuinely useful contribution, and so is
disagreeing with the specification for a scientifically sound reason.
