# The N-DOS standard

**Version 0.1 — draft.** Derived from *N-DOS: A Practical Framework for Neural
Data Organization* (Alikarami, in preparation), which is the source of this
specification and the reasoning behind it. This document states the standard
in the form an implementation can be checked against; the manuscript explains
why it takes this shape.

This is the base the rest of the repository rests on. The tools exist to make
a project conform to what is written here, and `ndos validate` reports whether
one does.

## How to read the requirement levels

**MUST** — a project that does otherwise does not conform.
**SHOULD** — recommended; a project may depart from it with reason.
**MAY** — optional.

A project **conforms** to N-DOS 0.1 when it satisfies every MUST below.

---

## 1. Project structure

A project MUST have these directories at its root:

| Directory | Contents |
| --- | --- |
| `raw_data/` | Unmodified data as it came from acquisition |
| `processed_data/` | Cleaned, sorted and pre-processed data |
| `analysis/` | Exploratory analyses and intermediate results |
| `derivatives/` | Validated, finalised analyses approved for sharing |
| `flagged_data/` | Corrupted, incomplete or uncertain data |
| `figures/` | Visualisations built from processed or derived data |
| `scripts/` | Code used for acquisition, preprocessing and analysis |
| `metadata/` | Experiment, acquisition, protocol and session descriptions |

A project MUST have a `README.md` at its root.

A directory MAY be empty. Empty is a statement — that this project has no
figures yet — and is more useful than the directory's absence, which says
nothing.

A project MAY contain other directories. Their contents are outside this
specification.

## 2. Session structure

Data MUST be organised by subject and then session:

```
raw_data/<SubjectID>/<SessionID>/
```

Acquisition files MUST sit directly under `<SessionID>/`. They MUST NOT be
placed in a further subdirectory of the implementation's choosing.

`processed_data/` SHOULD mirror the same shape:

```
processed_data/<SubjectID>/<SessionID>/
├── temp/                    scratch from sorting, safe to remove once validated
├── <processed files>
└── derived_metadata.json    how these files came to be
```

Scratch written by a sorter SHOULD be placed in `temp/` and flagged temporary
(§6), so it can be found and removed later without anyone having to remember
which files were intermediates.

## 3. Identifiers

**SubjectID** MUST identify one experimental subject, and MUST be stable for
the life of that subject. It SHOULD be short and human-readable: `M123` for
mouse 123.

**SessionID** MUST be unique within a subject, and MUST NOT contain a date in
a form where day and month can be confused: `03/04/2025` names two different
days depending on the reader's country.

It SHOULD be the acquisition date as `YYYYMMDD`, and `YYYYMMDD_NN` where a
subject was recorded more than once that day, numbered from `01` in
acquisition order.

Some data records a session without recording its date — a folder named only
`ses-01`. Such a project still conforms; `ses-01` is a worse identifier than a
date, but inventing a date it does not have would be worse still.

## 4. File naming

Files SHOULD be named:

```
<SubjectID>_<SessionID>_<type>.<ext>
```

with `<type>` from this list where one applies:

| Type | Contents | Example |
| --- | --- | --- |
| `raw` | Raw electrophysiology | `M123_20250314_raw.dat`, `.nwb` |
| `lfp` | Local field potential | `M123_20250314_lfp.npy` |
| `spikes` | Sorted spikes | `M123_20250314_spikes.csv` |
| `behavior` | Behavioural measurements | `M123_20250314_behavior.tsv` |
| `task` | Task events: maze, reward, trial structure | `M123_20250314_task.tsv` |
| `position` | Position tracking | `M123_20250314_position.tsv` |
| `experimenter` | Experimenter input, keypresses, annotations | `M123_20250314_experimenter.tsv` |
| `video` | Video | `M123_20250314_video.mp4` |

Where no listed type applies, the file SHOULD keep a descriptive word of its
own in the same position. A file MUST NOT be given a type from this list that
misdescribes it: a wrong label is worse than an unfamiliar one, because the
filename is what everyone reads first.

Video SHOULD be H.264-encoded MP4 where the acquisition system allows it. This
is a decision for whoever configures the rig; re-encoding afterwards costs
either quality or a second copy, and raw data is meant to stay as acquired.

### Versions

A reprocessing SHOULD be marked with a suffix: `_v1`, `_v2`. A new version MUST
NOT overwrite the one before it.

## 5. Analysis-tool output

Directories written by an analysis tool — a Phy or Kilosort sorting, a
SpikeInterface folder, suite2p output, an Open Ephys recording, a Zarr store,
a DeepLabCut project — MUST be kept exactly as the tool wrote them. Their
filenames and internal structure are how the tool finds its own data.

Such a directory SHOULD be placed under the session it belongs to, and MUST
NOT have its contents renamed to §4. The naming convention applies to files a
lab writes, not to a format another program reads back.

## 6. Flags

A dataset MAY carry flags recording what is known about it:

```json
{"validated": true, "temp": false, "deletable": false}
```

| Flag | Meaning |
| --- | --- |
| `validated` | Someone checked this and considers it good |
| `temp` | Scratch, existing only until validation |
| `deletable` | Confirmed safe to remove |

A file marked `validated` MUST NOT be removed by an automated cleanup,
whatever else it is flagged. Deletion MUST NOT happen without a person
confirming the specific files.

A project MAY carry a table of its validated files as a reference index for
analyses, so a pipeline reads what has been checked rather than whatever a
directory happens to contain.

## 7. Metadata

Metadata SHOULD record, for each subject: species, strain, sex, date of birth
and genotype. For each session: date, type, task and quality. For each
procedure — surgery, injection, implant, drug, training — the subject, date,
type, target and agent.

A value that has never been supplied MUST be distinguishable from one that was
checked and could not be determined. An absent value and an unknown value are
different facts, and treating them alike biases anything built on top.

Metadata MAY be stored as CSV, JSON or YAML. It SHOULD live in `metadata/`, or
alongside the session it describes.

## 8. Storage

Raw data MUST NOT be modified after acquisition. It SHOULD be made read-only
once a session is complete, and SHOULD be held in more than one place.

Processed data SHOULD record which code and parameters produced it.

Data whose integrity is uncertain SHOULD be placed in `flagged_data/` with a
note saying why, rather than deleted or left where it might be mistaken for
sound data.

## 9. Interoperability

An N-DOS project SHOULD be convertible to BIDS and NWB without re-organisation,
since subject, session and acquisition are already explicit. Conversion is
outside this specification, and N-DOS does not replace either.

---

## Conformance

A project conforms to N-DOS 0.1 when:

1. The eight directories of §1 and a `README.md` are present.
2. Every file under `raw_data/` sits at `<SubjectID>/<SessionID>/` (§2).
3. Every `SessionID` is unique within its subject and free of ambiguous dates
   (§3). A session not named as a date is reported as a recommendation, not a
   failure.

These are the requirements a tool can check by looking at a project. The other
MUSTs in this document — that raw data is not modified after acquisition, that
tool output is not renamed, that validated files are not deleted — constrain
what may be *done* to a project rather than what it looks like afterwards. A
checker cannot see that a file was renamed last year, only that it has the
name it has now. They are stated as requirements because they are, not because
they can be enforced.

Check the first three with:

```bash
ndos validate /path/to/project
```

Everything else in this document is SHOULD or MAY: recommended practice that a
project may depart from, deliberately, and still conform.

## Versioning of this document

This specification is versioned separately from the software. `0.1` is a
draft: it states current practice and may change in response to labs using it.
A change that would make a conforming project non-conforming requires a new
version number.
