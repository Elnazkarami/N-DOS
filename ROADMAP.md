# Roadmap

What exists, what is next, and what has been deliberately left undone. Dated
**November 2026**, against release 0.2.0.

The ordering principle is stated once and applies throughout: **nothing here is
built before there is evidence from a real archive that it is needed.** The
most common way a data standard fails is by specifying entities, vocabularies
and mappings that its authors imagined rather than met. Several items in §3
below are designed and could be implemented in a week; they are waiting on a
lab, not on effort.

---

## 1. Shipped

The original manuscript proposed N-DOS as a folder convention and listed
tooling as future work. All of the following now exists, is tested, and runs on
Linux, macOS and Windows with nothing installed beyond the Python standard
library.

| Planned as future work | Now | What it does |
| --- | --- | --- |
| Reference implementation | `ndos` | One command, zero runtime dependencies, Python 3.9+ |
| Compliant directory generation | `ndos init` | Starts a conformant project, and makes session folders |
| Metadata validation | `ndos validate` | Checks a project against the MUSTs of the specification |
| Automated conversion (`ndos-convert`) | `ndos convert` | BIDS and NWB handoff, refusing rather than guessing on collisions |
| Metadata ontology and automated discovery | `ndos query` | Cohort queries over incomplete records, citing the evidence for every answer |
| Ontology-driven search layer | `ndos search` | Full-text search across filenames, lab notes, protocols, `.docx` and `.xlsx`, reporting which animals a document names |
| Visualisation / lab dashboard | `ndos gui` | The same tools in a browser window, served by the package, bound to this machine only |
| Minimal metadata templates | `ndos table` | Three linked spreadsheets people fill in Excel, checked on the way back in |

And several things the manuscript did not anticipate, which came out of
building it:

- **`ndos report` / `ndos scan`** — read-only inventory and reconstruction of
  the experiment behind an inherited directory.
- **`ndos archive`** — reads inside `.zip`, `.tar` and friends without
  extracting them, so an archive can be inventoried before anyone commits disk
  to it.
- **`ndos organize`** — proposes the N-DOS layout from whatever structure
  exists, showing the rule and the evidence behind every individual guess, and
  reporting where two sources of the same fact disagreed.
- **`ndos tags`** — validated / temporary / safe-to-delete flags, and a
  sweep that will not delete anything without showing the plan first.
- **`ndos protect`** — raw data read-only after acquisition, which is a MUST in
  the specification and was previously only an instruction.
- **`ndos prov`** — records what produced a result, and traces a figure back
  through commands and parameters to the raw files behind it.
- **`ndos verify`** — checks a transferred dataset arrived intact, and returns
  *inconclusive* rather than a false pass when something could not be read.
- **Evidence typing throughout** — observed, declared, computed, or checked and
  genuinely unknown. A blank is not an unknown.
- **Three-valued answers throughout** — matched, excluded, and **cannot be
  ruled out**; verified, failed, and **inconclusive**.
- **Versioned JSON Schema contracts**, served at the identity each one
  declares, so an `$id` points at something real.

## 2. Next, and not waiting on anyone

These are ordinary work, scheduled.

- **A pilot write-up.** The first external archive N-DOS is pointed at, with
  what it got right, what it got wrong, and what the lab did about it. This is
  the highest-value item on this page.
- **More layout rules from real misreads.** Every "it read my folders wrongly"
  report becomes a test fixture. The rules that exist came from real archives;
  the ones that do not exist yet are the ones nobody has shown us.
- **Specification 0.2.** The current draft states current practice. 0.2 will
  state it again after labs have argued with it.
- **Controlled vocabulary expansion** for species, strain, brain region and
  drug, drawn from what people actually type into the metadata sheets rather
  than from an ontology chosen in advance.

## 3. Designed, waiting for evidence

Each of these has a sketch and a reason to exist. None will be implemented
until a real archive demonstrates the need, because each adds a commitment the
standard then has to keep.

- **A layout-mapping contract (`ndos-map.json`).** A file in which a lab
  declares how its own existing folder structure maps onto N-DOS entities, so
  the tools read it correctly without the lab moving anything and without us
  guessing. This is the honest answer to "we already have a convention and we
  are keeping it" — and it is the piece most likely to be built next.
- **An acquisition entity.** Below session, above file. Needed the moment a
  lab records two probes in one session and wants them addressed separately.
  Premature until someone does.
- **A feature registry.** Declaring which processed data suits which analysis,
  so a pipeline can select inputs without a person vouching for them.
- **An intent-translation layer.** Turning "find all sessions with CA1 theta
  after drug X" into a query over the metadata. The query engine underneath it
  exists; the translation is a convenience, and conveniences that guess are
  worse than none.
- **Non-Python wrappers.** Command-line wrappers for R and MATLAB workflows.
  The commands are already language-agnostic — this is for labs where nobody
  touches a terminal.

## 4. Deliberately not doing

Stated so nobody waits for it.

- **Reading PDFs.** Search covers `.docx`, `.xlsx`, Markdown and plain text.
  PDF text extraction is unreliable in exactly the cases that matter — a
  scanned surgery log — and a search that silently misses the document you
  remember is worse than one that tells you it cannot read it.
- **Becoming a file format.** Acquisition files stay exactly as the
  acquisition system wrote them.
- **Becoming a database.** No server, no daemon, no migrations.
- **Becoming an archive.** DANDI and OpenNeuro exist. N-DOS prepares data for
  them.
- **Human neuroimaging.** BIDS has it covered.
- **Anything that uploads your data anywhere.** Everything runs locally. The
  GUI binds to localhost.

## 5. Governance

Currently one author, which is a weakness and is stated as one. The intended
end state is the model BIDS and NWB use: a specification that changes by
public proposal, with a working group that is not the original author.

The route there runs through adoption, not through announcing a committee. The
practical first step is other people's archives breaking the tools in ways the
author could not have predicted — see
[contributing](CONTRIBUTING.md), including the bounded tasks worth volunteering
for.
