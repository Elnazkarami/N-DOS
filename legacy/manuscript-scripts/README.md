# N-DOS Manuscript Scripts

Minimal, tool-agnostic scripts to support the N-DOS manuscript.
They do two things:

1. **Create** an N-DOS project scaffold
2. **Read a folder, restructure into N-DOS**, and **compress per session**

Languages provided: **Python**, **R**, **Bash**.

```
.
├── ndos_create.py
├── ndos_restructure_compress.py
├── ndos_create.R
├── ndos_restructure_compress.R
├── ndos_create.sh
└── ndos_restructure_compress.sh
```

---

## N-DOS layout (target)

```
PROJECT_ROOT/
├── raw_data/
│   └── <SubjectID>/
│       └── <SessionID>/
│           └── raw/
├── processed_data/
├── analysis/
├── figures/
├── scripts/
└── README.md
```

* Files moved by restructuring end up in:
  `raw_data/<SubjectID>/<SessionID>/raw/<original_filename>`
* Per-session archives are written to:
  `PROJECT_ROOT/archives/<SubjectID>_<SessionID>.tar.gz`

---

## Requirements

* **Python** ≥ 3.8 (stdlib only)
* **R** (base R; uses `utils::tar`)
* **Bash** (with `tar`, `find`, `awk`; uses system `python3` for robust regex in the Bash script)

> Make shell scripts executable first:
>
> ```bash
> chmod +x ndos_create.sh ndos_restructure_compress.sh
> ```

---

## 1) Create an N-DOS project scaffold

### Python

```bash
python ndos_create.py /path/to/PROJECT_ROOT [--force]
```

### R

```bash
Rscript ndos_create.R /path/to/PROJECT_ROOT [--force]
```

### Bash

```bash
./ndos_create.sh /path/to/PROJECT_ROOT [--force]
```

* Creates `raw_data/`, `processed_data/`, `analysis/`, `figures/`, `scripts/`, and a basic `README.md`.
* `--force` overwrites an existing `README.md` and ensures folders exist.

---

## 2) Restructure a folder into N-DOS and compress per session

You provide a **source** directory (where your files currently live) and a **destination** project root (the N-DOS project).
Scripts detect **SubjectID** and **SessionID** via **regex** (configurable), move files into the N-DOS layout, and (by default) create **per-session `.tar.gz` archives**.

### Defaults for ID detection

* **SubjectID pattern** (first capture group used):

  ```
  (?i)^(?:sub-|subject[-_]?)([A-Za-z0-9]+)|/(M\d+|R\d+|S\d+)/
  ```

  Matches things like `sub-01`, `subject_A12`, or lab conventions like `M123`, `R07`, `S5`.

* **SessionID pattern** (first capture group used):

  ```
  (?i)(\d{8})(?:[-_]?\d{0,2})|/(\d{8})/
  ```

  Matches `YYYYMMDD` (e.g., `20230915`), optionally with a small suffix like `_01`.

> Anything not matched falls back to `unknown_subject` or `unknown_session`.

### Python

```bash
python ndos_restructure_compress.py \
  --src /path/to/input \
  --dst /path/to/PROJECT_ROOT \
  --subject-pattern '(?i)^(?:sub-|subject[-_]?)([A-Za-z0-9]+)|/(M\d+|R\d+|S\d+)/' \
  --session-pattern '(?i)(\d{8})(?:[-_]?\d{0,2})|/(\d{8})/' \
  [--dry-run] [--no-compress]
```

### R

```bash
Rscript ndos_restructure_compress.R \
  --src /path/to/input \
  --dst /path/to/PROJECT_ROOT \
  --subject-pattern '(?i)^(?:sub-|subject[-_]?)([A-Za-z0-9]+)|/(M\\d+|R\\d+|S\\d+)/' \
  --session-pattern '(?i)(\\d{8})(?:[-_]?\\d{0,2})|/(\\d{8})/' \
  [--dry-run] [--no-compress]
```

### Bash

```bash
./ndos_restructure_compress.sh \
  --src /path/to/input \
  --dst /path/to/PROJECT_ROOT \
  [--subject-pattern '(?i)^(?:sub-|subject[-_]?)([A-Za-z0-9]+)|/(M[0-9]+|R[0-9]+|S[0-9]+)/'] \
  [--session-pattern '(?i)([0-9]{8})(?:[-_]?[0-9]{0,2})|/([0-9]{8})/'] \
  [--dry-run] [--no-compress]
```

* `--dry-run` prints the planned moves without touching files.
* `--no-compress` skips archive creation.
* Existing destination filenames are not overwritten; numeric suffixes are appended.

---

## Examples

### A. Quick scaffold + restructure + compress (Python)

```bash
python ndos_create.py /data/project
python ndos_restructure_compress.py --src /data/inbox --dst /data/project
```

### B. Preview first (dry run), custom patterns (Bash)

```bash
./ndos_restructure_compress.sh \
  --src /mnt/ephys_dump \
  --dst /mnt/ndos_project \
  --subject-pattern '(?i)/(mouse_[A-Za-z0-9]+)/' \
  --session-pattern '(?i)/(202[3-5][01][0-9][0-3][0-9])/' \
  --dry-run
```

### C. R workflow (no compression)

```bash
Rscript ndos_create.R ~/ndos_proj
Rscript ndos_restructure_compress.R --src ~/downloads/data --dst ~/ndos_proj --no-compress
```

---

## Tips on regex tuning

* **Subjects**: include your lab’s labels (e.g., `M\\d+`, `rat\\d+`, `sub-[A-Za-z0-9]+`).
* **Sessions**: most labs embed dates; adjust to your convention (e.g., `YYYY-MM-DD`, `YYMMDD`).
* Use **non-capturing groups** `(?: )` for structure; ensure the **first capturing group** corresponds to the ID you want.

---

## Output artifacts

* Moved files: `PROJECT_ROOT/raw_data/<SubjectID>/<SessionID>/raw/...`
* Archives: `PROJECT_ROOT/archives/<SubjectID>_<SessionID>.tar.gz`

Each archive contains the `raw` directory for that session, preserving relative structure.

---

## Troubleshooting

* **Nothing moved / many “unknown\_subject/session”**
  Your regex likely needs tweaking. Try `--dry-run` with broader patterns and refine.
* **Permission errors**
  Ensure you have write permissions to `PROJECT_ROOT` and that the input files aren’t read-only.
* **Shell quoting**
  When passing regex on the command line, wrap patterns in single quotes `'...'` to avoid escaping issues.
* **Bash script needs Python**
  The Bash version uses a tiny embedded Python helper for regex robustness. Ensure `python3` is available in `PATH`.

---

## License

MIT (do whatever you want, attribution appreciated).

