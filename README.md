# NDOS

**A BIDS-inspired framework for wet-lab and animal neuroscience data.**

NDOS applies the organisational clarity of BIDS to the parts of animal
neuroscience that begin before a recording and continue long after it: animal
history, surgeries and injections, behavioural training, neural acquisition,
tissue and histology, and the analyses built on top of them.

This repository is **NDOS Core**, the open-source layer. It is being built
module by module. Each module works on its own, today, with no installation.

> **Status:** early. The modules below are working and tested. The wider
> framework described in the project plan is not built yet.

---

## Install nothing

NDOS Core is **Python 3.9+ standard library only**. No `pip install`, no
environment, no dependencies. This is deliberate: the machine that most needs
to be inventoried is often an acquisition PC where you are not allowed to
install anything.

```bash
git clone https://github.com/<your-org>/ndos.git
cd ndos
python3 ndos_report.py /path/to/your/data
```

A single module can also be copied on its own and run anywhere.

---

## Safety guarantee

`ndos_scan.py` and `ndos_report.py` **never modify, move, rename, extract, or
delete anything** below the directory you point them at. They open files only
to read bytes for checksums. This is verified by tests that snapshot every
size and modification time before and after a scan.

Nothing in NDOS Core writes to your data without an explicit, reviewable plan
that you approve first.

---

## Modules

### `ndos_report.py` — understand a directory you have inherited

Point it at a folder and get a readable account of what is in there, what is
duplicated, how it appears to be organised, and what needs attention. Requires
no metadata and no prior setup.

```bash
python3 ndos_report.py /path/to/data                        # readable summary
python3 ndos_report.py /path/to/data -f markdown -o report.md
python3 ndos_report.py manifest.json -f json                 # machine-readable
```

It reports:

| Section | What it answers |
| --- | --- |
| What is in here | Composition by category and size — ephys, imaging, behaviour, analysis, archives |
| Inferred folder structure | Which directory level looks like a subject, a session, a date — and which names contradict that |
| Duplicate files | Byte-identical copies and how much space they waste |
| Largest directories | Where the volume actually lives |
| Needs attention | Unextracted archives, zero-byte files, unreadable paths, names that break on other systems |

Compound formats are recognised where a bare extension is not enough:
`M01_g0_t0.imec0.ap.bin` is reported as electrophysiology, not as an anonymous
`.bin`. Genuinely ambiguous extensions are labelled *ambiguous* rather than
guessed at — a confident wrong label is worse than an honest unknown.

Inferred structure is always labelled as inference. NDOS distinguishes what it
**observed**, what it **computed**, and what it **guessed**, and never presents
one as another.

### `ndos_table.py` — get lab metadata in, via the tool you already use

Scanning reveals what is on disk. It cannot reveal which animal a recording
came from, what was injected, or when. That knowledge lives in a notebook or
an Excel sheet, so NDOS meets it there.

```bash
python3 ndos_table.py export manifest.json -d metadata/   # build the sheets
# ... open them in Excel and fill in the blanks ...
python3 ndos_table.py check metadata/ --emit linked.json
```

Metadata lives in **three linked tables**, because a fact recorded once should
govern every session it applies to:

| File | One row per | Filled by |
| --- | --- | --- |
| `animals.csv` | animal — species, strain, sex, date of birth, genotype | you, once per animal |
| `procedures.csv` | surgery, injection, implant, drug, training | you; NDOS cannot observe a surgery, so it never touches this file |
| `sessions.csv` | recording session — date, task, QC | NDOS pre-fills what it observed; you add the rest |

`animals.csv` is seeded with the subject names NDOS found in your folder tree,
so you start with rows rather than a blank sheet. Sessions are regenerated on
every export with observed columns refreshed and typed-in values carried
across; a row that disappears is reported rather than silently taking its
metadata with it.

**Intervals are computed, never typed.** Because a procedure has a date and a
session has a date, NDOS derives `days_since_injection`, `days_since_implant`,
`age_days`, and so on. These carry the status `computed`, so they are never
mistaken for something a person asserted — and they make "recorded three to
five weeks after the injection" a query you can actually run.

Entry is forgiving, validation is strict. `mouse`, `Mouse`, and `mice` all
resolve to `mus musculus`; `ephys` to `electrophysiology`; `viral injection`
to `injection`; `female` to `F`. What you typed is preserved beside the mapped
value so the mapping can be audited. But `21/03/2025` is refused, because
`03/04/2025` means 3 April in the UK and 4 March in the US and guessing would
silently corrupt a date.

Validation spans the tables, not just each file: a session naming an animal
with no row, or a procedure for a subject nobody described, is reported as a
broken link.

A blank cell and the word `unknown` mean different things, and NDOS keeps them
apart: blank means nobody has filled it in yet, `unknown` means somebody
checked and could not determine it. `--emit` writes evidence-typed records
against [`schemas/session_metadata.schema.json`](schemas/session_metadata.schema.json).

### `ndos_query.py` — build a cohort, and see why each session qualified

```bash
python3 ndos_query.py metadata.json -w species=mouse -w sex=F \
    -w 'target_region=CA1' -w 'session_date>=2025-03-01' \
    -w 'modalities~electrophysiology' \
    --save-cohort cohort.json --name ca1-ephys-spring-2025
```

Operators are `=` `!=` `>` `<` `>=` `<=` and `~` (contains). `field=*` requires
any value; `field=?` finds values recorded as unknown. Queries are normalised
the same way the data was, so `species=mouse` finds sessions recorded as
`mus musculus`, and the report shows you that substitution.

**Results come in three groups, not two.** A session whose sex was never
recorded is not a non-match — it is an open question, and quietly dropping it
biases the cohort in a way nobody sees. So NDOS reports:

| Group | Meaning |
| --- | --- |
| Matched | Every criterion satisfied, each citing the field, value, and evidence status it rests on |
| **Cannot be ruled out** | Met everything checkable, but a deciding value was never recorded |
| Excluded | Ruled out by evidence that *is* recorded |

Unresolved sessions stay out of a saved cohort unless you pass
`--include-unresolved`, and are labelled if you do.

**An empty result explains itself** rather than returning nothing. It names the
constraint that eliminated the most sessions, and distinguishes "your query was
too narrow" from "this column was never filled in" — which need opposite fixes.

Cohorts are frozen with the full query plan against
[`schemas/cohort.schema.json`](schemas/cohort.schema.json), including counts of
what was excluded and what could not be decided, so a selection can be re-run,
audited, or disputed later.

### `ndos_archive.py` — see inside archives without extracting them

Labs zip their archives because the data is enormous. On a real lab drive,
**88% to 100% of everything was inside `.zip` files**, which meant no
inventory could describe any of it.

This reads an archive's index rather than its contents, so a 300 GB collection
can be catalogued without unpacking a byte:

```bash
python3 ndos_archive.py inspect /Volumes/archive -c archives.json
python3 ndos_archive.py search archives.json '*.avi'
```

Listings are cached and keyed on size and modification time. That matters: on
a slow external drive the first read of a 2 GB archive took nearly a minute,
and nobody should pay that twice.

**Extraction is planned, then confirmed, then done.** Ask for what you want,
see exactly what it would write and what it would cost, and only then say yes:

```bash
python3 ndos_archive.py plan archives.json --dest ./work --name '*.avi'
python3 ndos_archive.py extract archives.json --dest ./work --name '*.avi'
```

The plan reports how many files, how many bytes, which already exist, and
whether there is enough free space — refusing to start if there is not.
Nothing is written until you confirm.

**Members that would escape the destination are refused.** An archive can
contain `../../etc/something`, and unpacking one you did not create is a real
way to get files written where you did not intend. Those members are listed
under REFUSED and never extracted.

`.tar` and `.tar.gz` need `--include-tar`, because unlike a zip they must be
streamed end to end to be listed, which on slow storage is expensive enough to
be a deliberate choice.

### `ndos_prov.py` — record what produced a result

Provenance normally goes uncaptured because capturing it means instrumenting
analysis code, and nobody rewrites a working script to satisfy a data policy.
So NDOS wraps the command instead:

```bash
python3 ndos_prov.py run --input raw/ --output processed/ \
    -- python3 preprocess.py raw processed
```

Nothing about `preprocess.py` changes. NDOS checksums the inputs, watches the
output directories before and after, records the git commit and environment,
and writes a run record. The wrapped command's exit code passes through, so
this composes inside existing shell scripts.

Then walk backwards from any result to the data behind it:

```bash
python3 ndos_prov.py trace figures/figure1.svg
```

```
figure1.svg
└── → figure  [run-157f69ae502a]  2026-08-20T02:39:50Z
      $ python3 scripts/make_figure.py processed figures
    ├── M01_ses01_filtered.dat
    │   └── → preprocess  [run-418c7c94596d]  2026-08-20T02:39:49Z
    │         $ python3 scripts/preprocess.py raw processed
    │       ├── M01_ses01.dat
    │       │   [raw] not produced by any recorded run
```

**Failed runs are recorded too**, and marked. "This figure came from a script
that exited 1" is exactly what someone needs warning about, so a partial
output is captured rather than discarded.

**Provenance never collects credentials.** Environment variables are recorded
only when named explicitly with `--record-env`; capturing the whole
environment would routinely bury API keys inside files meant to be shared.
`--anonymous` additionally omits hostname and username, for provenance you
intend to publish.

Records validate against
[`schemas/provenance.schema.json`](schemas/provenance.schema.json) and follow
the W3C PROV shape of an activity that *used* and *generated* artifacts.

### `ndos_scan.py` — read-only inventory

Produces a versioned JSON manifest: every file with its path, size,
modification time, and SHA-256 digest, plus an explicit list of everything
skipped and why.

```bash
python3 ndos_scan.py /path/to/data --output manifest.json
python3 ndos_scan.py /path/to/data --no-checksum        # faster, no dedup
python3 ndos_scan.py /path/to/data --exclude '*.tmp'
```

The manifest is the input to every other NDOS module, so a slow checksummed
scan only has to happen once. The output contract is versioned in
[`schemas/manifest.schema.json`](schemas/manifest.schema.json).

An inventory that quietly omits data is worse than no inventory, so
unreadable directories, permission failures, and symlinks are recorded in a
`skipped` list rather than silently dropped.

### `ndos_init.py` — start an NDOS project

Creates a project profile and the directories NDOS owns. It does **not**
migrate, move, or restructure your data; raw data stays exactly where it is.

```bash
python3 ndos_init.py ~/projects/my-study
```

---

## Try it without any data

A synthetic messy lab project is included, containing problems chosen because
they recur in real labs: a duplicated backup, an unextracted archive, a failed
acquisition left as a zero-byte file, inconsistent subject naming, and
histology stored away from the recordings it validates.

```bash
python3 tests/fixtures/make_messy_lab.py /tmp/messy-lab
python3 ndos_report.py /tmp/messy-lab
python3 ndos_table.py export /tmp/messy-lab -d /tmp/metadata
# fill in a few rows across the three sheets, then:
python3 ndos_table.py check /tmp/metadata --emit /tmp/linked.json
python3 ndos_query.py /tmp/linked.json -w species=mouse -w sex=F
```

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The suite runs on the standard library alone. If `jsonschema` is installed, it
additionally validates generated manifests against the published schema.

---

## Repository layout

| Path | Contents |
| --- | --- |
| `ndos_scan.py` | Read-only inventory |
| `ndos_report.py` | Inventory report |
| `ndos_table.py` | Spreadsheet metadata round-trip |
| `ndos_query.py` | Cohort queries with evidence citation |
| `ndos_prov.py` | Run provenance and lineage tracing |
| `ndos_archive.py` | Archive inspection and planned extraction |
| `ndos_init.py` | Project initialisation |
| `schemas/` | Versioned JSON Schema contracts |
| `tests/` | Test suite and synthetic fixtures |
| `legacy/` | Superseded prototypes — **unsupported, they move files** |

The `legacy/` code predates NDOS Core and restructures data in place. It is kept
for reference only; see [`legacy/README.md`](legacy/README.md).

---

## Scope

**In scope:** non-human animal neuroscience — colony and cohort context,
surgeries, injections, implants and drugs, behavioural training, extracellular
electrophysiology and calcium imaging, tissue collection and histology, and the
analyses derived from them.

**Not in scope:** replacing BIDS for human MRI/MEG/EEG, replacing NWB as a
container, or becoming a public archive. NDOS reads and hands off to those
ecosystems rather than competing with them.

---

## Licence

[Apache-2.0](LICENSE). Chosen over MIT for its explicit patent grant, which
institutional legal review generally looks for before adoption.

Earlier revisions of this repository declared MIT in the README. That grant
still stands for those revisions; anyone who took the code under MIT keeps it.
NDOS Core is Apache-2.0 going forward.
