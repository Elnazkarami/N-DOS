#!/usr/bin/env python3
Restructure files into N-DOS raw_data/<Subject>/<Session>/raw and compress.
Usage:
  python ndos_restructure_compress.py --src /path/to/input --dst /path/to/project \
      [--subject-pattern REGEX] [--session-pattern REGEX] [--dry-run] [--no-compress]

import argparse, re, tarfile
from pathlib import Path
import shutil

DEF_SUBJ = r"(?i)^(?:sub-|subject[-_]?)([A-Za-z0-9]+)|/(M\d+|R\d+|S\d+)/"
DEF_SESS = r"(?i)(\d{8})(?:[-_]?\d{0,2})|/(\d{8})/"

def _first_group(pattern: str, s: str, default: str):
    m = re.search(pattern, s)
    if not m:
        return default
    for g in (m.groups() or ()):
        if g:
            return g
    return m.group(0) if m else default

def compute_dest(f: Path, dst_root: Path, subj_pat: str, sess_pat: str) -> Path:
    s = str(f)
    sub = _first_group(subj_pat, s, "unknown_subject")
    ses = _first_group(sess_pat, s, "unknown_session")
    return dst_root / "raw_data" / sub / ses / "raw" / f.name

def restructure(src: Path, dst: Path, subj_pat: str, sess_pat: str, dry_run: bool=False):
    src, dst = Path(src), Path(dst)
    moved = []
    for f in src.rglob("*"):
        if not f.is_file():
            continue
        if f.name.startswith("."):
            continue
        dest = compute_dest(f, dst, subj_pat, sess_pat)
        if dry_run:
            print(f"[DRY] {f} -> {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        # avoid overwrite
        final = dest
        i = 1
        while final.exists():
            final = dest.with_name(f"{dest.stem}_{i}{dest.suffix}")
            i += 1
        shutil.move(str(f), str(final))
        print(f"[MOVE] {f} -> {final}")
        moved.append(final)
    return moved

def compress_per_session(dst_root: Path):
    dst_root = Path(dst_root)
    archives_dir = dst_root / "archives"
    archives_dir.mkdir(parents=True, exist_ok=True)
    for sub_dir in (dst_root / "raw_data").glob("*"):
        if not sub_dir.is_dir():
            continue
        for ses_dir in sub_dir.glob("*"):
            raw_dir = ses_dir / "raw"
            if not raw_dir.exists():
                continue
            tar_path = archives_dir / f"{sub_dir.name}_{ses_dir.name}.tar.gz"
            with tarfile.open(tar_path, "w:gz") as tf:
                tf.add(raw_dir, arcname=f"{sub_dir.name}/{ses_dir.name}/raw")
            print(f"[TAR] {tar_path}")

def main():
    ap = argparse.ArgumentParser(description="Restructure and compress into N-DOS layout")
    ap.add_argument("--src", type=Path, required=True, help="Source folder to scan")
    ap.add_argument("--dst", type=Path, required=True, help="Project root (N-DOS)")
    ap.add_argument("--subject-pattern", type=str, default=DEF_SUBJ, help="Regex for SubjectID (first capture used)")
    ap.add_argument("--session-pattern", type=str, default=DEF_SESS, help="Regex for SessionID (first capture used)")
    ap.add_argument("--dry-run", action="store_true", help="Only print planned moves")
    ap.add_argument("--no-compress", action="store_true", help="Skip compression step")
    args = ap.parse_args()

    restructure(args.src, args.dst, args.subject_pattern, args.session_pattern, args.dry_run)
    if not args.no_compress and not args.dry_run:
        compress_per_session(args.dst)

if __name__ == "__main__":
    main()
