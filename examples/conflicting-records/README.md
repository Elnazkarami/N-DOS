# Two records that disagree

Every link is valid. The identity is still wrong.

```bash
ndos table check examples/conflicting-records/metadata
```

The output is committed beside this file as
[`check-output.txt`](check-output.txt), so you can read the result without
running anything. A test regenerates it and fails if it drifts.

## What is wrong

`sessions.csv` has two rows. The second one sits in `raw_data/M202/20250211/`
and declares `subject_id = M201` — somebody typed the wrong animal.

| Row | Folder says | Declared | |
| --- | --- | --- | --- |
| `ndos-c001` | `M201` | `M201` | agrees |
| `ndos-c002` | `M202` | `M201` | **disagrees** |

## Why referential integrity does not catch it

Both `M201` and `M202` have rows in `animals.csv`. So every reference
resolves, nothing points at a missing animal, and a check that only validates
links reports no problems at all.

That is the case this example exists for. It was
[reported from outside](https://neurostars.org/t/36467) by someone who
pointed out that testing with only one animal present hides the bug behind a
broken-link error — which is exactly what the first attempt at testing it did.

Before this was fixed, the same metadata reported:

```
Ready to use    : 2 (100%)
Problems        : 0
```

Not merely failing to flag the disagreement — certifying the row.

## What it reports now

```
Ready to use    : 1 (50%)
Problems        : 0
Disagreements   : 1  (two records describing the same session do not match)
```

and names it rather than filing it under broken links, because a missing row
and two rows disagreeing are different faults:

```
SOURCES THAT DISAGREE
  Two records describe the same session and do not match. Every link can be
  valid and the identity still be wrong, so this is not a broken reference —
  it is a disagreement only a person can settle.
```

The message says NDOS cannot tell which of the two is wrong. It cannot: the
folder might be where the data was misfiled, or the spreadsheet might be where
the typo is. Choosing one silently is the thing being avoided.

A contradicted row stops counting as ready to use, `--strict` exits non-zero,
and `--emit` refuses to write `linked.json` from metadata whose identity is
disputed — so the contradiction cannot travel downstream into a cohort.

## The same idea in two other places

- `ndos organize` reports when a filename and a folder name different animals,
  and which claim it overruled.
- `ndos search` marks a document that sits under one animal and names only
  others — while leaving a cohort log naming several animals *including* its
  own alone, because that is a cohort log and not a contradiction.
