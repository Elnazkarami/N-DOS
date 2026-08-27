# NDOS: Neuroscience Data Organization System

**A BIDS-inspired framework for wet-lab and animal neuroscience data.**

NDOS applies the organisational clarity of BIDS to the parts of animal
neuroscience that begin before a recording and continue long after it: animal
history, surgeries and injections, behavioural training, neural acquisition,
tissue and histology, and the analyses built on top of them.

This repository is **NDOS Core**, the open-source layer. It is being built
module by module. Each module works on its own, today, with no installation.

> **Status:** the N-DOS standard defined in the manuscript — its directory
> layout, session structure, naming conventions and data flags — is fully
> implemented here, along with the automation built on top of it. Everything
> below is working and tested against real lab storage. Interfaces are still
> at 0.x and may change.

---

## Install nothing

NDOS Core is **Python 3.9+ standard library only**. No `pip install`, no
environment, no dependencies. This is deliberate: the machine that most needs
to be inventoried is often an acquisition PC where you are not allowed to
install anything.

```bash
git clone https://github.com/Elnazkarami/N-DOS-.git ndos
cd ndos
python3 ndos.py --help
python3 ndos.py report /path/to/your/data
```

Every module is also a standalone script — `python3 ndos_report.py ...` works
identically, and a single file can be copied out and run on its own.

If you would rather type `ndos report` than `python3 ndos.py report`:

```bash
pip install ndos          # once published
pip install -e .          # or from a clone
```

Either adds the command and nothing else — there are no dependencies to
install, and CI fails the build if that ever stops being true. **New here? Start with [QUICKSTART.md](https://github.com/Elnazkarami/N-DOS/blob/main/QUICKSTART.md).** When NDOS reads your
data wrongly — and on some layout it will — [RECIPES.md](https://github.com/Elnazkarami/N-DOS/blob/main/RECIPES.md) is what
to do about it.

---

## Safety guarantee

`ndos_scan.py` and `ndos_report.py` **never modify, move, rename, extract, or
delete anything** below the directory you point them at. They open files only
to read bytes for checksums. This is verified by tests that snapshot every
size and modification time before and after a scan.

Nothing in NDOS Core writes to your data without an explicit, reviewable plan
that you approve first.

---

## The whole thing, end to end

Starting from a directory nobody understands:

```bash
python3 ndos.py report   /path/to/chaos                     # what is in here?
python3 ndos.py archive  inspect /path/to/chaos -c arch.json    # what is in the zips?
python3 ndos.py organize apply /path/to/chaos -d ./project  # build the N-DOS layout
python3 ndos.py table    export ./project -d ./metadata     # fill in what only you know
python3 ndos.py table    check  ./metadata --emit linked.json
python3 ndos.py query    linked.json -w species=mouse -w target_region=CA1
python3 ndos.py convert  bids ./project -d ./bids-export --write
```

Nothing in that sequence moves or modifies your data. The layout is built
from symbolic links; the only commands that ever write to your files are
`ndos_organize --mode move`, `ndos_archive extract`, and `ndos_tags sweep
--apply`, each of which shows a plan and asks first.

## Modules

The order below is the order you meet them: understand what you have,
then structure it, then describe it, then use it.

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
[`schemas/manifest.schema.json`](https://github.com/Elnazkarami/N-DOS/blob/main/schemas/manifest.schema.json).

An inventory that quietly omits data is worse than no inventory, so
unreadable directories, permission failures, and symlinks are recorded in a
`skipped` list rather than silently dropped.

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

### `ndos_organize.py` — rebuild the N-DOS layout from what already exists

An inventory *describes* a directory. It does not make an inherited archive
understandable to a PI whose data collector left years ago. This builds the
missing half: the N-DOS project, derived from the original structure rather
than imposed on it.

```bash
python3 ndos_organize.py plan  /path/to/chaos -d ./project   # see it first
python3 ndos_organize.py apply /path/to/chaos -d ./project   # then confirm
python3 ndos_organize.py undo  ./project/.ndos-layout-log.json
```

The layout is the one defined in the N-DOS manuscript:

```
project/
├── raw_data/<SubjectID>/<SessionID>/     # acquisition files
├── processed_data/  analysis/  derivatives/
├── flagged_data/    figures/   scripts/   metadata/
└── README.md
```

SessionID follows the manuscript's `YYYYMMDD` convention, becoming
`YYYYMMDD_01`, `_02` when a subject was recorded more than once that day.

**Nothing is copied or moved by default.** The tree is built from symbolic
links, so a 45 GB collection is organised in seconds, occupies about 40 KB,
and is undone by deleting it. `--mode copy` and `--mode move` exist, are
planned and confirmed the same way, and `move` says plainly that it relocates
your data. Every apply writes `.ndos-layout-log.json`, and `undo` reverses it —
including moving files back.

**Filenames follow the manuscript's conventions**, `SubjectID_SessionID_type`:

```
A0634_20201122_video-0.avi        A0634_20201122_raw-info.rhd
A0634_20201122_position-Take-2020-11-22-06.32.30-PM.csv
A0634_20201122_experimenter-notes.csv
```

The data type comes from the file itself — its extension, then its name — and
never from the directories above it, which decide the *role* instead. Where no
standard type applies, the original descriptor is kept (`_analogin.dat`)
rather than forcing a file into a category it may not belong to: a confident
wrong label is worse than an unfamiliar one, because the filename is what
everyone reads first. Pass `--keep-original-names` to skip renaming entirely.

Because the default mode is links, renaming costs nothing and risks nothing:
the link carries the standard name while the file it points at keeps its own.

**Sessions are clustered, not split.** A miniscope starting at 18:32:25 and an
Intan at 18:32:20 are one recording, not two. Acquisition times within ten
minutes are treated as one session; genuinely separate recordings on a day
become `YYYYMMDD_01` and `_02`.

**Every placement explains itself:**

```
raw_data/A0634/20201122/0.avi
    from  0.avi
    why   folder 'A0634' matches a subject identifier;
          'A0600' above it read as a cohort or range
    why   date '2020_11_22' with acquisition time '18_32_25'
    why   imaging and video is treated as raw_data
```

Structure is read from directory names, from filenames when the folders are
silent (`2020_11_20.zip` carries its date nowhere else), and from compound
names like `A0634_201122_183220`.

**Nothing is dropped.** Files whose subject or session cannot be determined go
to `flagged_data/` with their original structure intact and a
`flagged_notes.json` saying why — which is what the N-DOS layout reserves that
directory for.

**Redundant copies are recognised, not duplicated.** A lab that restructured
its data once has the same recording in two places; on a real drive this was
3.0 GB. Each file is linked once and the copies are listed, rather than
appearing under invented names as though they were distinct.

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
against [`schemas/session_metadata.schema.json`](https://github.com/Elnazkarami/N-DOS/blob/main/schemas/session_metadata.schema.json).

### `ndos_tags.py` — validated, temporary, safe to delete

The layout reserves `flagged_data/` and `temp/`, and the standard defines the
flags that make them mean something:
`{"validated": true, "temp": false, "deletable": false}`.

```bash
python3 ndos_tags.py set spikes.npy --validated --note "curated in Phy"
python3 ndos_tags.py list ./project --flag temp
python3 ndos_tags.py sweep ./project              # plan a cleanup
python3 ndos_tags.py sweep ./project --apply      # after reading it
```

Tags live in a `tags.json` beside the data they describe, one per session, so
a session directory stays self-describing if it is moved or copied.

**A validated file is never swept**, whatever its other flags say, and marking
something both validated and deletable is recorded as a conflict rather than
resolved silently. `sweep` plans by default and deletes only on `--apply` with
a confirmation: the manuscript imagines a maintenance script removing
temporaries automatically, and deletion driven by a hand-edited flag is how a
lab loses data it meant to keep.

Files that *look* like scratch but were never flagged are listed separately
and only with `--include-untagged`, because nobody has vouched for them.
Scratch is judged relative to the project root, so a project living under
`/tmp` does not have all of its files called temporary.

`ndos_organize` tags automatically: spike-sorting scratch is routed to
`processed_data/<sub>/<ses>/temp/`, flagged `temp`, and recorded in that
session's `derived_metadata.json` — so a sweep finds it later without anyone
remembering which files were intermediates.

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
[`schemas/cohort.schema.json`](https://github.com/Elnazkarami/N-DOS/blob/main/schemas/cohort.schema.json), including counts of
what was excluded and what could not be decided, so a selection can be re-run,
audited, or disputed later.

### Declaring which data suits which analysis

```bash
python3 ndos_query.py linked.json --config analyses.json
```

```json
{"analyses": [
  {"name": "theta-power-CA1",
   "requires": ["target_region=CA1", "days_since_injection>=21", "qc_status=pass"]}
]}
```

Each analysis is a saved query, so the answer carries the same evidence rules:
sessions that qualify, sessions that cannot be ruled out, and why nothing
matched when nothing does.

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
[`schemas/provenance.schema.json`](https://github.com/Elnazkarami/N-DOS/blob/main/schemas/provenance.schema.json) and follow
the W3C PROV shape of an activity that *used* and *generated* artifacts.

### `ndos_convert.py` — hand off to BIDS and NWB

NDOS does not reimplement either standard. NWB conversion is solved by
maintained tools, and rewriting it here would produce a worse converter nobody
maintains. This prepares the handoff instead:

```bash
python3 ndos_convert.py bids ./project -d ./bids-export --write
python3 ndos_convert.py nwb  ./project --metadata linked.json --save nwb-plan.json
```

`bids` builds a BIDS-shaped tree of links with `dataset_description.json`,
`participants.tsv` and per-file sidecars, mapping N-DOS entities onto BIDS
ones — `A0634` → `sub-A0634`, `20201122` → `ses-20201122`, and the
discriminator onto `acq-`. Scratch in `temp/` is never published.

**It is BIDS-shaped, not validated BIDS**, and says so in its own output.
Animal electrophysiology is covered by BEP032, which is not finalised, so no
export can honestly claim conformance today.

`nwb` emits a conversion plan with metadata already mapped onto NWB's fields,
ready for NeuroConv or a lab script — and reports what is still missing
(`species`, `sex`, `date_of_birth`) rather than inventing it.

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
| `ndos.py` | One command dispatching to all of the below |
| `QUICKSTART.md` | Fifteen minutes, for a lab member |
| `RECIPES.md` | What to do when a guess is wrong |
| `ndos_report.py` | Inventory report |
| `ndos_scan.py` | Read-only inventory |
| `ndos_archive.py` | Archive inspection and planned extraction |
| `ndos_organize.py` | Rebuild the N-DOS layout from existing structure |
| `ndos_table.py` | Linked metadata tables |
| `ndos_tags.py` | Validation, temporary and deletion flags |
| `ndos_query.py` | Cohort queries with evidence citation |
| `ndos_prov.py` | Run provenance and lineage tracing |
| `ndos_convert.py` | BIDS and NWB handoff |
| `ndos_init.py` | Project initialisation |
| `schemas/` | Versioned JSON Schema contracts |
| `tests/` | Test suite and synthetic fixtures |
| `LEGACY.md` | Where the superseded prototypes went, and why |

Scripts that predate NDOS Core are no longer in this branch: they move data
with no rollback and one of them contradicts the standard. They remain
reachable, with their history — see [LEGACY.md](https://github.com/Elnazkarami/N-DOS/blob/main/LEGACY.md).

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
