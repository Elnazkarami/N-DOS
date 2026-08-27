# Superseded code

Two sets of scripts preceded NDOS Core. Neither is part of it, and neither is
in this branch any more.

| What | Where it is now |
| --- | --- |
| Python/R/Bash scripts supporting the 2025 manuscript | tag [`v0-manuscript-2025`](https://github.com/Elnazkarami/N-DOS/tree/v0-manuscript-2025), branch [`manuscript-2025`](https://github.com/Elnazkarami/N-DOS/tree/manuscript-2025) |
| Miniscope extractor and restructurer | [`Elnazkarami/data-management-`](https://github.com/Elnazkarami/data-management-) |

Nothing was deleted. Both remain reachable, with their history, and the tag
records exactly the state the 2025 manuscript describes.

## Why they are not here

**They move data.** `ndos_restructure_compress.py` and `data_restructurer.py`
both relocate files, with no manifest, no checksum, no collision report and no
rollback. A partial or mistaken run cannot be undone or even described
afterwards. That is the opposite of how NDOS Core works, where scanning is
read-only and anything that writes shows a plan and asks first.

Leaving them in a repository being handed to people to try meant someone might
run one on real data before reading why they should not.

**One contradicts the standard.** `ndos_restructure_compress.py` writes to
`raw_data/<subject>/<session>/raw/`, one level deeper than the manuscript's
`raw_data/SubjectID/SessionID/`. The manuscript is the standard; the script was
never updated to match it.

**They were duplicated across three languages**, which triples the maintenance
and lets the implementations drift. NDOS Core is one reference implementation
in Python, with stable JSON contracts that any language can read.

## What to use instead

```bash
python3 ndos.py report /path/to/data          # understand what is there
python3 ndos.py organize plan /path/to/data -d ./project
```

`organize` does what the restructuring scripts did, derived from the structure
you already have, showing every decision before it acts, and building the
layout from links so nothing moves at all unless you ask for `--mode move`.
