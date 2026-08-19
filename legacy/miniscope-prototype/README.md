# Legacy prototypes (unsupported)

These scripts predate NDOS Core. They were written for a specific Miniscope
project and they **move, extract, and rename source files in place**. That
behaviour is deliberately not part of NDOS Core, which is read-only by default
and requires an explicit reviewed plan before anything is written.

They are kept for historical reference and because the directory conventions
they encode (`Session_Date/Subject_ID/Session_ID/raw/`) are a useful example of
a real lab layout that NDOS has to be able to read.

| File | Role |
| --- | --- |
| `read_compressed.py` | Entry point; walks a directory and drives the others |
| `compression_handler.py` | Extracts zip/tar/gz/bz2 archives |
| `data_extractor.py` | Classifies files by extension |
| `data_restructurer.py` | Creates the output tree and moves files into it |
| `error_handler.py` | Error logging |
| `read_compressed.sh` | Shell wrapper |

## Do not use these on data you care about

`data_restructurer.py` moves files out of their original location. There is no
manifest, no checksum, no collision report, and no rollback log. If you want to
reorganise data, use the NDOS `plan` / `apply` workflow instead, which records
what it intends to do before it does it.

To inventory a directory these scripts previously operated on, use:

```bash
python3 ndos_scan.py /path/to/data --output manifest.json
```
