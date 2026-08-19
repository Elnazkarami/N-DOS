#!/usr/bin/env bash
# Restructure into N-DOS and compress per session.
# Usage:
#   ./ndos_restructure_compress.sh --src DIR --dst PROJECT_ROOT \
#     [--subject-pattern REGEX] [--session-pattern REGEX] [--dry-run] [--no-compress]

set -euo pipefail

SRC=""; DST=""; SUBJ_PAT='(?i)^(?:sub-|subject[-_]?)([A-Za-z0-9]+)|/(M[0-9]+|R[0-9]+|S[0-9]+)/'; SESS_PAT='(?i)([0-9]{8})(?:[-_]?[0-9]{0,2})|/([0-9]{8})/'; DRY=0; NOCMP=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --src) SRC="$2"; shift 2 ;;
    --dst) DST="$2"; shift 2 ;;
    --subject-pattern) SUBJ_PAT="$2"; shift 2 ;;
    --session-pattern) SESS_PAT="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    --no-compress) NOCMP=1; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$SRC" || -z "$DST" ]]; then
  echo "Missing --src or --dst"; exit 1
fi

# Requires Python for robust regex extraction (portable approach)
_extract_ids_py='
import os, re, sys
subj_pat = re.compile(os.environ["SUBJ_PAT"])
sess_pat = re.compile(os.environ["SESS_PAT"])
def first_group(pat, s, default):
    m = pat.search(s)
    if not m: return default
    for g in m.groups() or []:
        if g: return g
    return m.group(0)
for p in sys.stdin:
    p=p.strip()
    if not p: continue
    s = p
    sub = first_group(subj_pat, s, "unknown_subject")
    ses = first_group(sess_pat, s, "unknown_session")
    print(f"{p}\t{sub}\t{ses}")
'

export SUBJ_PAT="$SUBJ_PAT"
export SESS_PAT="$SESS_PAT"

# Move files
while IFS= read -r f; do
  [[ -f "$f" ]] || continue
  line=$(printf "%s\n" "$f" | python3 -c "$_extract_ids_py")
  path=$(echo "$line" | awk -F'\t' '{print $1}')
  sub=$(echo "$line"  | awk -F'\t' '{print $2}')
  ses=$(echo "$line"  | awk -F'\t' '{print $3}')
  dest="$DST/raw_data/$sub/$ses/raw/$(basename "$path")"
  if [[ "$DRY" -eq 1 ]]; then
    echo "[DRY] $path -> $dest"
  else
    mkdir -p "$(dirname "$dest")"
    if [[ -e "$dest" ]]; then
      i=1; base="${dest%.*}"; ext="${dest##*.}"
      [[ "$ext" == "$dest" ]] && ext=""
      while [[ -e "$dest" ]]; do
        if [[ -n "$ext" ]]; then
          dest="${base}_$i.$ext"
        else
          dest="${base}_$i"
        fi
        i=$((i+1))
      done
    fi
    mv "$path" "$dest"
    echo "[MOVE] $path -> $dest"
  fi
done < <(find "$SRC" -type f ! -name ".*")

# Compress per session
if [[ "$DRY" -eq 0 && "$NOCMP" -eq 0 ]]; then
  mkdir -p "$DST/archives"
  find "$DST/raw_data" -mindepth 2 -maxdepth 2 -type d | while read -r sesdir; do
    raw="$sesdir/raw"
    [[ -d "$raw" ]] || continue
    sub=$(basename "$(dirname "$sesdir")")
    ses=$(basename "$sesdir")
    tarpath="$DST/archives/${sub}_${ses}.tar.gz"
    tar -czf "$tarpath" -C "$(dirname "$sesdir")" "$(basename "$sesdir")/raw"
    echo "[TAR] $tarpath"
  done
fi
