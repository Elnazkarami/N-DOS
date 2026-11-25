---
title: "Why N-DOS exists"
---

[Home](index.html) · **Why** · [The standard](specification.html) · [Quickstart](quickstart.html) · [When a guess is wrong](recipes.html) · [Examples](index.html#worked-examples) · [Roadmap](roadmap.html) · [Contributing](contributing.html) · [GitHub](https://github.com/Elnazkarami/N-DOS)

---

# Why N-DOS exists

**Neuroscience has good standards for publishing data. It has almost nothing
for the eighteen months before that — which is where the data is made, and
where it is lost.**

This page is the reasoning behind [the specification](specification.html). The
specification states the rules; this states why they take the shape they do.

---

## 1. The gap is at the bench, not the repository

Three widely adopted standards cover the end of the data lifecycle. The Brain
Imaging Data Structure (BIDS) harmonises datasets for publication. Neurodata
Without Borders (NWB) standardises the file format neurophysiology is stored
in. The DANDI Archive publishes and serves the result. Each works well at what
it is for, and N-DOS is built to hand off to all three.

None of them governs the eighteen months before that. Data is collected,
sorted, re-sorted, flagged, copied to a server, copied back, inherited by a new
student and analysed, all inside a lab, in whatever arrangement of folders the
person who started it preferred. BIDS has an electrophysiology extension
(BEP032), but like the rest of BIDS it describes a dataset prepared for
submission, not the working directory it was prepared from.

This is not a gap anyone overlooked — it is a different problem. A repository
format can require conformance as a condition of acceptance. A lab cannot: the
data arrives in whatever state the acquisition system wrote it, and nobody can
refuse it.

When the neuroscience community has been asked directly, this is what it
reports. The German National Research Data Infrastructure initiative
(NFDI-Neuro) surveyed the community and published the results (Klingner et
al., 2023). The barriers members named were, in their own ordering: a lack of
data and metadata standards; a lack of community-adopted provenance tracking
methods; a lack of secure infrastructure for sensitive data; a lack of research
data management literacy; and a lack of resources — time, personnel, money —
for doing it properly. Meanwhile 91% said they were willing to share their
data. The survey's own conclusion is that converting that willingness into
practice "requires the systematic development of standards, tools, and
infrastructure" — the three together.

That is worth reading carefully, because it is not a complaint about missing
documents. Standards exist, and the people surveyed know they exist. What is
missing is a standard that applies where their data actually is, provenance
tracking the community has adopted, and a version of all of it cheap enough in
time to use while an experiment is running. Published alongside it, Eke et al.
(2022) make the same argument at the level of international governance, and
Spires-Jones (2024) makes it at the smallest possible scale: an editorial by a
journal editor describing reorganising her own lab's data storage so it could
be shared and archived.

N-DOS is an attempt at exactly the combination the survey asks for: a
specification, the tools that make complying with it practical, and provenance
recorded as part of ordinary work rather than as a separate chore.

## 2. What that costs, concretely

Two costs, and the second is the one usually left out.

**Forward cost.** Every lab invents its own layout. Often every lab member
invents their own. `raw`, `processed`, `final`, `final2`,
`definitely_final3`. None of them can read each other's, collaboration needs a
person in the room to interpret the folders, and onboarding a new member means
transferring an oral tradition.

**Retrospective cost.** The data already collected. A drive arrives; the
person who filled it has graduated. Somewhere in it are three years of
recordings, and nobody left can say which animal is which, what was injected
when, or which of the four folders called `final` produced the figures in the
paper. That data was paid for, and animals were used for it, and it is now
indistinguishable from data that was never collected.

Standards address the forward cost. The retrospective cost is what most labs
actually have, and is why N-DOS treats *reading data that follows no
convention* as a first-class requirement rather than a migration chore.

## 3. The principles that follow

Four principles come from the diagnosis above, and four from the experience of
implementing them.

**Immediate usability.** A lab can adopt the layout with the filesystem it
already has. Nothing in the standard requires software to satisfy.

**Human readability.** `M123/20230915/` tells a person what it is. Directory
and file names are meant to be read by the student who inherits them, before
they are parsed by anything.

**Simplicity.** Eight directories, a subject level, a session level. Learnable
in one sitting by someone with no interest in data management.

**Traceability by identifier.** A session identifier carrying its date places
a recording in time without opening anything, sorts chronologically on its own,
and can be matched against a surgery log or an order record years later.
`ses-01` can do none of that — which is the one place N-DOS deliberately
departs from BIDS-style entity naming, and [§3 of the
specification](specification.html) gives the reasoning in full.

And from building it:

**Read-only by default.** A tool that reorganises an archive you do not
understand yet is a tool that destroys evidence. Everything N-DOS does is
read-only unless you name one of three commands that is not, and each shows a
plan and waits.

**Evidence typing.** Every value records how it is known: *observed* in the
data, *declared* by a person, *computed* from other values, or checked and
genuinely *unknown*. A blank cell and a confirmed unknown are different facts
and must not be stored the same way.

**Three answers, not two.** A cohort query returns matched, excluded, and
**cannot be ruled out**. A session whose species nobody wrote down is not a
session known not to be a mouse. A tool that conflates those returns a biased
cohort without saying so.

**One source of truth.** Where the same question had two implementations, they
eventually disagreed. The specification, the schemas and the worked examples
each live in exactly one place, and tests fail when a copy drifts — including
the copies on this site.

## 4. A standard nobody can comply with is just a PDF

This is the part that separates N-DOS from a document.

Publishing a layout convention and asking labs to follow it puts the entire
cost of adoption on the person with the least time. They must read the spec,
decide how their existing folders map onto it, move terabytes by hand, and
discover their mistakes months later. Most reasonably decline.

So the standard ships with the tools that make following it practical, and
with the means to bring data that predates it up to it: an inventory of what
is actually on the disk, a proposed layout with the rule and the evidence
behind every single guess so you can correct it rather than trust it, metadata
capture through spreadsheets people already use, search across lab notes and
surgery logs, cohort queries that cite their evidence, a conformance checker,
and a handoff to BIDS and NWB.

The tools are not the standard. They are the reason anyone can adopt it.

## 5. Where N-DOS sits

| | What it governs | When it applies |
| --- | --- | --- |
| **BIDS** | Dataset layout for publication and reuse | Preparing to share |
| **NWB** | File format for neurophysiology data | Writing or converting files |
| **DANDI** | Public archive and serving | After publication |
| **NeuroBlueprint** | Folder structure for new systems-neuroscience projects (`rawdata`/`derivatives`, `sub-`/`ses-` key-value entities, required datatype folders) | Creating a project now |
| **datashuttle** | Creating, validating and transferring NeuroBlueprint project folders | Creating a project now |
| **Spyglass** | Database-backed analysis and experiment tracking | Running analyses |
| **IBL / ONE** | Shared data access across a consortium | Multi-site collaboration |
| **N-DOS** | Lab-level layout, metadata, evidence and provenance — **including for data already on the disk that follows no convention** | From acquisition onward, and retrospectively |

The distinctive claim is the last column. NeuroBlueprint and datashuttle solve
the forward problem well, and a lab starting a project today has a real choice
to make between conventions. N-DOS additionally starts from an archive that
predates every convention, reconstructs the experiment behind it, and reports
what it could *not* determine — and it will read and query that archive without
asking you to change a single folder first.

That is why the specification defines [three things a project can
be](specification.html): **readable** (NDOS can inventory, search and query it in
whatever organisation it already has — this requires nothing),
**conformant** (it satisfies the MUSTs), and **traceable** (it also records how
its facts are known). Nothing withholds features at the lower levels. A lab
with an inherited archive starts at readable and may reasonably stay there.

## 6. What N-DOS is not

- **Not a file format.** Your `.dat`, `.nwb` and proprietary acquisition files
  stay exactly as the acquisition system wrote them.
- **Not a database.** No server, no schema migration, no daemon. Eight
  directories and some JSON.
- **Not an archive.** It does not host or publish anything. It prepares data
  for the places that do.
- **Not a replacement for BIDS or NWB.** It hands off to both, and claims no
  conformance it cannot demonstrate.
- **Not for human neuroimaging.** Scope is non-human animal neuroscience:
  colony and cohort context, surgeries, implants and drugs, behavioural
  training, extracellular electrophysiology, calcium imaging, histology, and
  the analyses built on them.

## 7. Status, honestly

Version 0.2.0. The software works and is tested on Linux, macOS and Windows
with no dependencies beyond the Python standard library. The specification is a
draft at 0.1 and will change in response to labs using it.

**No external lab has completed a pilot yet.** That is the single most useful
thing anyone reading this can change, and it takes about fifteen minutes and
will not move or change your data. Start at the
[quickstart](quickstart.html); the forms linked from
[contributing](contributing.html) ask about the *shape* of your directories,
never their contents.

---

## References

Every reference below was checked against Crossref; the metadata is what the
publisher records, not what a secondary source reported.

Eke, D. O., Bernard, A., Bjaalie, J. G., Chavarriaga, R., et al. (2022). International data
governance for neuroscience. *Neuron*, 110(4), 600–612.
[doi:10.1016/j.neuron.2021.11.017](https://doi.org/10.1016/j.neuron.2021.11.017)

Gorgolewski, K. J., Auer, T., Calhoun, V. D., Craddock, R. C., et al. (2016). The brain imaging
data structure, a format for organizing and describing outputs of neuroimaging
experiments. *Scientific Data*, 3, 160044.
[doi:10.1038/sdata.2016.44](https://doi.org/10.1038/sdata.2016.44)

Klingner, C. M., Denker, M., Grün, S., Hanke, M., et al. (2023). Research data management
and data sharing for reproducible research — results of a community survey of
the German National Research Data Infrastructure initiative neuroscience.
*eNeuro*, 10(2), ENEURO.0215-22.2023.
[doi:10.1523/ENEURO.0215-22.2023](https://doi.org/10.1523/ENEURO.0215-22.2023)

Pierré, A., Pham, T., Pearl, J., et al. (2024). A perspective on
neuroscience data standardization with Neurodata Without Borders. *The Journal
of Neuroscience*, 44(38), e0381242024.
[doi:10.1523/JNEUROSCI.0381-24.2024](https://doi.org/10.1523/JNEUROSCI.0381-24.2024)

Rübel, O., Tritt, A., Ly, R., Dichter, B. K., et al. (2022). The Neurodata Without Borders
ecosystem for neurophysiological data science. *eLife*, 11, e78362.
[doi:10.7554/eLife.78362](https://doi.org/10.7554/eLife.78362)

Spires-Jones, T. L. (2024). Data management (and sharing) in neuroscience:
balancing possible, practical and perfect solutions. *Brain Communications*,
7(1), fcae450.
[doi:10.1093/braincomms/fcae450](https://doi.org/10.1093/braincomms/fcae450)

Teeters, J. L., Godfrey, K., Young, R., Dang, C., et al. (2015). Neurodata Without
Borders: creating a common data format for neurophysiology. *Neuron*, 88(4),
629–634.
[doi:10.1016/j.neuron.2015.10.025](https://doi.org/10.1016/j.neuron.2015.10.025)

Ziminski, J. J., Sirmpilatze, N., Peri, B. D., et al. (2026). datashuttle: automated data management for
experimental neuroscience. *Journal of Open Source Software*, 11(122), 9642.
[doi:10.21105/joss.09642](https://doi.org/10.21105/joss.09642)

The reasoning above is drawn from *N-DOS: A Practical Framework for Neural Data
Organization* (Alikarami, in preparation), which is also the source of the
specification.
