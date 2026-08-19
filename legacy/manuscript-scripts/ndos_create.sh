#!/usr/bin/env bash
# Create N-DOS project scaffold.
# Usage: ./ndos_create.sh /path/to/project [--force]

set -euo pipefail

ROOT="${1:-}"
FORCE="${2:-}"
if [[ -z "$ROOT" ]]; then
  echo "Usage: $0 /path/to/project [--force]"; exit 1
fi

mkdir -p "$ROOT"
for d in raw_data processed_data analysis figures scripts; do
  if [[ -d "$ROOT/$d" && "$FORCE" != "--force" ]]; then
    continue
  fi
  mkdir -p "$ROOT/$d"
done

README="$ROOT/README.md"
if [[ ! -f "$README" || "$FORCE" == "--force" ]]; then
  printf "# N-DOS Project\n\nThis project follows the N-DOS layout.\n" > "$README"
fi

echo "[OK] Created/updated N-DOS scaffold at: $ROOT"
