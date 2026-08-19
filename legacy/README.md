# Legacy prototypes (unsupported)

Code that predates NDOS Core. It is kept because it is the evidence base for
earlier work, not because it should be used.

| Directory | Origin | What it does |
| --- | --- | --- |
| `manuscript-scripts/` | this repository, `main` before NDOS Core | Python/R/Bash trio supporting the 2025 N-DOS manuscript: scaffold a project, then restructure and compress a folder into it |
| `miniscope-prototype/` | [`Elnazkarami/data-management-`](https://github.com/Elnazkarami/data-management-) | Earlier Miniscope-specific extractor and restructurer |

## Why these are not the NDOS Core workflow

Both sets **move files out of their original locations**. The manuscript
scripts do offer `--dry-run`, which was the right instinct, but neither
records a manifest, a checksum, a collision report, or a rollback log, so a
partial or mistaken run cannot be undone or even fully described afterwards.

NDOS Core inverts this. Scanning is read-only and always produces a durable
record first; any operation that writes requires an explicit plan you approve
before it runs.

They are also duplicated across three languages, which triples the maintenance
cost and lets the implementations drift apart. Per the project plan, Python is
now the reference implementation, and other languages are supported through
stable JSON contracts rather than parallel rewrites.

## What to use instead

```bash
python3 ndos_report.py /path/to/data          # understand what is there
python3 ndos_scan.py /path/to/data -o m.json  # durable read-only manifest
```

The state of this repository at the time of the 2025 manuscript is preserved
under the `v0-manuscript-2025` tag and the `manuscript-2025` branch.
