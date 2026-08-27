# When it doesn't do what you expected

[QUICKSTART.md](QUICKSTART.md) walks through the happy path. This is the other
half: what to do when NDOS reads your data wrongly, which it will, because no
set of rules covers every way a lab has ever organised a folder.

**None of the situations below can lose data.** Layouts are built from
shortcuts and undone by deleting them; scans never write. The worst outcome is
a project directory that is wrong, which you delete and rebuild.

---

## "Everything ended up in flagged_data/"

That means NDOS could not work out which animal or which session a file
belongs to. Look at why — it says so for every file:

```bash
python3 ndos.py organize plan /path/to/data -d ./project | head -40
cat ./project/flagged_data/flagged_notes.json
```

Usually one of three things:

**Your subject and session folders are deeper than NDOS looked.** Tell it
where they are. Levels are counted from the top of the directory you scanned,
starting at 0:

```
study7/cohortB/rat14/day3/rec.dat
  0      1       2     3
```

```bash
python3 ndos.py organize plan /path/to/data -d ./project \
    --subject-depth 2 --session-depth 3
```

**There is a wrapper folder above everything.** If your whole dataset sits
inside one directory that means nothing (`export/`, `backup_2024/`), skip it:

```bash
python3 ndos.py organize plan /path/to/data -d ./project --strip 1
```

**The information genuinely is not in the paths.** If the animal ID only
exists inside a spreadsheet, no tool can recover it from the folder names.
Organise what can be organised, and record the rest with
`python3 ndos.py table`.

## "It picked the wrong folder as the subject"

Common when a cohort or range folder sits above the animal, like
`A0600/A0634/`. NDOS prefers the deeper one and says so in the plan. When it
still gets it wrong, name the level explicitly with `--subject-depth`.

The plan tells you what it decided before anything is built. Read it.

## "One session got split into two"

Two acquisition systems that start seconds apart are one recording, and NDOS
treats times within ten minutes as a single session. If your systems start
further apart than that, they will look like separate sessions
(`20250314_01`, `20250314_02`).

Point at the session level directly so the folder decides, not the clock:

```bash
python3 ndos.py organize plan /path/to/data -d ./project --session-depth 2
```

## "Two sessions got merged into one"

The opposite: two genuine recordings on one day, in folders that do not record
a time. There is nothing to tell them apart, so they land together. Use
`--session-depth` to point at whatever folder does distinguish them.

## "My sessions are single archives named after the animal"

Files like `A3302-190809.zip`, with the animal in the name and the folder
above holding a cohort, are read correctly: the animal comes from the
filename, and a two-digit year is resolved to this century. If yours use a
different separator or ordering and end up in `flagged_data/`, that is worth
reporting — see the last section.

## "I don't like the new filenames"

NDOS renames to `SubjectID_SessionID_type` because the standard says so. To
keep your originals:

```bash
python3 ndos.py organize apply /path/to/data -d ./project --keep-original-names
```

If a file was given a type you disagree with, that is worth reporting — the
type comes from the extension and the filename, and the rules only know the
formats they have seen.

## "The scan is taking forever"

Ask before you commit to it:

```bash
python3 ndos.py scan /path/to/data --estimate
```

If that says hours, it is telling the truth — external drives are often far
slower than people expect. Two ways forward:

```bash
python3 ndos.py scan /path/to/data --cache      # resumable; stop and restart freely
python3 ndos.py scan /path/to/data --no-checksum  # seconds, but no duplicate detection
```

With `--cache`, stopping costs you at most the file it was working on.

## "I need the actual files out of a zip"

Look first, extract only what you want:

```bash
python3 ndos.py archive inspect /path/to/data -c archives.json
python3 ndos.py archive search archives.json '*.avi'
python3 ndos.py archive plan archives.json --dest ./work --name '*.avi'
python3 ndos.py archive extract archives.json --dest ./work --name '*.avi'
```

`plan` tells you how much disk it needs before you start. Nothing is unpacked
until you confirm.

`inspect` reads `.zip` archives only, because a `.tar` or `.tar.gz` has to be
read end to end to be listed, which on a slow drive is expensive enough to be
your decision. It tells you how many it left alone and how much they hold; add
`--include-tar` when you want them.

## "I built a project and want to start over"

```bash
python3 ndos.py organize undo ./project/.ndos-layout-log.json
```

That removes everything it created and nothing it did not. Or delete the
project directory — it holds only shortcuts, unless you used `--mode copy` or
`--mode move`.

If you used `--mode move`, `undo` puts your files back where they came from.
Use the log, not `rm`.

## "Did it change my data?"

No, unless you ran one of three commands and confirmed a prompt:
`organize --mode move`, `archive extract`, or `tags sweep --apply`. Everything
else reads.

To satisfy yourself rather than take this on trust:

```bash
# Write the manifests somewhere else, or the second scan will find the first
# scan's own output sitting in the directory and report it as a difference.
python3 ndos.py scan /path/to/data -o ~/before.json
# ... do whatever you were going to do ...
python3 ndos.py scan /path/to/data -o ~/after.json

python3 - ~/before.json ~/after.json <<'PY'
import json, sys
def digests(path):
    with open(path) as handle:
        return {f["path"]: f["sha256"] for f in json.load(handle)["files"]}
before, after = digests(sys.argv[1]), digests(sys.argv[2])
changed = [p for p in before.keys() & after.keys() if before[p] != after[p]]
print("changed :", changed or "none")
print("removed :", sorted(before.keys() - after.keys()) or "none")
print("added   :", sorted(after.keys() - before.keys()) or "none")
PY
```

Three `none`s mean every file is byte-for-byte what it was.

## "A query returns nothing"

It will tell you which criterion was responsible:

```
Nothing matched. The constraint that excluded the most sessions was
'species=rat' (3 excluded). Try dropping or widening it.
```

If instead it says a field was *never entered*, the fix is filling in the
spreadsheet, not changing the query. Those are different problems and NDOS
distinguishes them.

Watch for the third group, "cannot be ruled out" — sessions that meet
everything checkable but are missing the deciding value. Treating those as
non-matches is how a cohort quietly acquires a bias.

## "My layout looks nothing like the examples"

Run this and send us the output:

```bash
python3 ndos.py report /path/to/data --no-checksum
```

It shows the structure NDOS thinks it sees, including which folder names do
*not* fit. A layout the rules cannot read is a genuinely useful bug report —
it means a real lab organises data in a way the rules have not met yet.

<https://github.com/Elnazkarami/N-DOS/issues>

---

## Reporting something usefully

Helpful:

- what you ran, exactly
- what you expected, and what happened
- the output of `python3 ndos.py report <dir> --no-checksum`, which describes
  the shape of your data without disclosing any of its contents
- `python3 ndos.py --version`

Not needed: your data. Every command above describes structure, not contents.
