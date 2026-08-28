# NDOS quickstart

The standard covers two situations, and so does this guide.

**Starting to collect, or collecting now?** Jump to [Starting from
scratch](#starting-from-scratch) — one command, then you are acquiring into the
right place from the first session.

**Handed a directory nobody understands any more?** Start here. About fifteen
minutes, most of it waiting for a scan.

You need Python 3.9 or newer. Nothing else — no `pip install`, no environment.

```bash
git clone https://github.com/Elnazkarami/N-DOS-.git ndos
cd ndos
python3 ndos.py --help
```

Every command below is `python3 ndos.py <something>`. If you would rather type
`ndos <something>`, run `pip install -e .` once; it changes nothing else.

---

## Before you start

**NDOS does not move or change your data.** Scanning reads files and writes
nothing. The layout it builds is made of shortcuts pointing at your originals.
Three commands *can* write — `organize --mode move`, `archive extract`, and
`tags sweep --apply` — and each shows you a plan and asks before doing anything.

If you are nervous, point it at a copy first. But you should not have to.

---

## 1. What is actually in there?

```bash
python3 ndos.py report /path/to/your/data
```

You get a readable summary: what kinds of files, how much of each, which
folders hold the volume, duplicated files, and a list of things worth your
attention — empty files from failed acquisitions, archives nobody unpacked,
filenames that will break on another computer.

It also guesses what your folder levels mean ("level 1 looks like a subject
ID") and tells you which names *don't* fit that guess.

On a slow external drive, add `--no-checksum` to get an answer in seconds.
Checksums are what make duplicate detection possible, so run it without that
flag when you can leave it going.

Not sure how long that would take? Ask:

```bash
python3 ndos.py scan /path/to/your/data --estimate
```

If the answer is hours, add `--cache` to the scan. It saves checksums as it
goes, so if you stop it — or your laptop sleeps — the next run carries on from
where it left off instead of starting again.

## 2. What is inside the zip files?

Most lab archives are mostly zips, and an inventory cannot see into them.

```bash
python3 ndos.py archive inspect /path/to/your/data -c archives.json
python3 ndos.py archive search archives.json '*.avi'
```

This reads each archive's index — nothing is unpacked, nothing is written into
your directory. The results are cached in `archives.json`, so the slow first
read happens once.

When you find something you actually want:

```bash
python3 ndos.py archive plan archives.json --dest ./work --name '*.avi'
python3 ndos.py archive extract archives.json --dest ./work --name '*.avi'
```

`plan` shows how many files, how much disk it needs, and whether you have
room. `extract` asks before starting.

## 3. Build a structure you can read

```bash
python3 ndos.py organize plan  /path/to/your/data -d ./project
python3 ndos.py organize apply /path/to/your/data -d ./project
```

This creates an N-DOS project:

```
project/
├── raw_data/<SubjectID>/<SessionID>/
├── processed_data/  analysis/  derivatives/
├── flagged_data/    figures/   scripts/   metadata/
└── README.md
```

Subjects, sessions and dates are read from your existing folder and file names,
and **every placement tells you why it was made**. Read the plan before you
apply it — if a guess is wrong, that is where you will see it.

When it does guess wrong, you can say where things actually are. Levels count
from the top of the directory you scanned, starting at 0:

```bash
python3 ndos.py organize plan /path/to/your/data -d ./project \
    --subject-depth 2 --session-depth 3
```

[RECIPES.md](RECIPES.md) works through the cases where this is needed.

Files it cannot identify go to `flagged_data/` with their original structure
and a note. Nothing is discarded.

By default this builds shortcuts, so it takes seconds and almost no disk space
whatever the size of your data. Made a mess? `python3 ndos.py organize undo
./project/.ndos-layout-log.json` removes it entirely.

## 4. Add what only you know

NDOS can see file sizes and dates. It cannot see which animal a recording came
from, or what was injected.

```bash
python3 ndos.py table export ./project -d ./metadata
```

Pointed at a project, this recognises the layout and reads through the links
it is built from, so it knows which folder is the animal without guessing. It
does not checksum anything — the tables need names and dates, not hashes.

That writes three spreadsheets:

| File | One row per | Notes |
| --- | --- | --- |
| `animals.csv` | animal | Pre-filled with the subject names found in your folders |
| `procedures.csv` | surgery, injection, drug | Empty — NDOS cannot observe these |
| `sessions.csv` | recording | Pre-filled with what was observed |

Open them in Excel. Fill in what you know; leave the rest blank. Write
`unknown` only where you checked and could not find out — a blank cell and the
word `unknown` mean different things here, and both are useful.

```bash
python3 ndos.py table check ./metadata --emit linked.json
```

This tells you what is still missing and catches mistakes. It is forgiving
about wording — `mouse`, `Mouse` and `mice` all work, so does `ephys` — but it
will refuse `21/03/2025`, because that date means two different things
depending on where you live.

Re-running `export` later never overwrites what you typed.

## 5. Find things

```bash
python3 ndos.py query linked.json -w species=mouse -w sex=F \
    -w target_region=CA1 -w 'days_since_injection>=21'
```

Answers come in three groups, not two: sessions that match, sessions that are
ruled out, and **sessions that cannot be ruled out** because something was
never recorded. That third group matters — treating those as non-matches would
quietly bias whatever you do next.

Every match shows the field and value it was based on. If nothing matches, it
tells you which criterion was responsible.

## 6. Keep track of what is checked

```bash
python3 ndos.py tags set ./project/processed_data/M01/20250314/spikes.npy \
    --validated --note "curated in Phy"
python3 ndos.py tags list ./project --flag temp
python3 ndos.py tags sweep ./project
```

`sweep` shows what could be deleted and deletes nothing. Add `--apply` when you
have read it. A file marked `validated` is never removed, whatever else it is
flagged.

Once you have checked some data, write the index an analysis should read
instead of globbing a directory and hoping:

```bash
python3 ndos.py tags index ./project -o ./metadata/validated.csv
```

---

## When you are ready to share

```bash
python3 ndos.py convert bids ./project -d ./bids-export --write
python3 ndos.py convert nwb  ./project --metadata linked.json
```

`bids` builds a BIDS-shaped export. `nwb` writes a conversion plan for
NeuroConv and tells you which metadata is still missing.

## Recording how a result was made

Wrap any analysis command and NDOS records what went in and what came out:

```bash
python3 ndos.py prov run --input raw/ --output results/ -- python3 analyse.py
python3 ndos.py prov trace results/figure1.svg
```

Your script does not change. `trace` walks a figure back through every step to
the raw data behind it.

---

## Starting from scratch

If you are setting up for a new project rather than digging out an old one,
you do not need any of the steps above. Make the layout and start collecting:

```bash
python3 ndos.py init ~/projects/my-study
```

That creates the eight N-DOS directories and a README explaining what belongs
in each. Then, for each recording:

```bash
python3 ndos.py init ~/projects/my-study --subject M123 --date 2025-03-14
```

```
Acquire into: ~/projects/my-study/raw_data/M123/20250314
  Name files as M123_20250314_<type>, for example _raw.dat, _lfp.npy, _behavior.tsv
```

Point your acquisition software at that folder. The convention is applied for
you, so `SessionID` is `20250314` — and `20250314_02` if you record that animal
twice in a day, which you get with `--number 2`. Omit `--date` and it uses
today.

Once a session is acquired, close it:

```bash
python3 ndos.py protect ~/projects/my-study --apply
```

That makes everything under `raw_data/` read-only, so a later script cannot
overwrite a recording. `--check` tells you later whether anything became
writable again, and `--release` gives write back when you genuinely need it.

Everything from step 4 onward works the same on a project built this way:
export the metadata tables, fill them in as you go rather than years later, and
query across sessions once there is more than one.

The difference is only where the structure comes from. Collecting into it
costs nothing; reconstructing it afterwards is the expensive path, which is
what the rest of this guide is for.

## Try it on nothing first

There is a synthetic lab directory in the repository, with the problems real
ones have — a duplicated backup, an unopened archive, a failed recording left
as an empty file, inconsistent subject names:

```bash
python3 tests/fixtures/make_messy_lab.py /tmp/messy-lab
python3 ndos.py report /tmp/messy-lab
```

## If something goes wrong

Nothing you have run above modified your data, so there is nothing to undo
except a project directory you can delete.

**[RECIPES.md](RECIPES.md) covers the common ones**: everything landing in
`flagged_data/`, the wrong folder being read as the subject, a session split in
two, a scan that will not finish, and how to prove for yourself that nothing
was altered.

Please report what happened: <https://github.com/Elnazkarami/N-DOS-/issues>.
A wrong guess about your folder structure is a useful bug — it means the rules
do not yet cover a layout that real labs use.
