#!/usr/bin/env python3
"""Generate a synthetic, deliberately messy animal-neuroscience project.

Every problem represented here was chosen because it shows up repeatedly in
real preclinical labs: duplicated backups, unextracted archives, failed
acquisitions left as zero-byte files, inconsistent subject naming, a stray
space in a path, and analysis outputs living next to raw data.

Files are small; sizes are simulated with sparse-ish padding so the report has
something meaningful to rank. Nothing here is real data.

    python3 tests/fixtures/make_messy_lab.py /tmp/messy-lab
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

#: (relative path, byte size, content seed). Files sharing a seed are made
#: byte-identical so duplicate detection has something true to find.
LAYOUT = (
    # --- Subject M01: the tidy one -----------------------------------------
    ("2025-03-14/M01/ses-01/raw/M01_ses01_g0_t0.imec0.ap.bin", 900_000, "ap01"),
    ("2025-03-14/M01/ses-01/raw/M01_ses01_g0_t0.imec0.ap.meta", 2_000, "meta01"),
    ("2025-03-14/M01/ses-01/raw/M01_ses01_g0_t0.imec0.lf.bin", 120_000, "lf01"),
    ("2025-03-14/M01/ses-01/raw/behaviour.csv", 45_000, "behav01"),
    ("2025-03-14/M01/ses-01/raw/tracking.avi", 700_000, "vid01"),
    ("2025-03-14/M01/ses-01/notes.txt", 1_200, "notes01"),
    ("2025-03-14/M01/ses-01/processed/spikes.npy", 300_000, "spk01"),
    ("2025-03-14/M01/ses-01/processed/cluster_info.tsv", 8_000, "clu01"),

    # --- Subject M02: inconsistent naming, missing metadata ----------------
    ("2025-03-21/m02/session2/raw/recording.bin", 850_000, "ap02"),
    ("2025-03-21/m02/session2/raw/recording.meta", 2_000, "meta02"),
    ("2025-03-21/m02/session2/raw/behav data.csv", 40_000, "behav02"),
    ("2025-03-21/m02/session2/raw/video.avi", 0, "empty"),          # failed capture
    ("2025-03-21/m02/session2/analysis/theta_power.mat", 150_000, "theta02"),
    ("2025-03-21/m02/session2/analysis/figure1.png", 220_000, "fig02"),

    # --- Subject M03: everything still in an archive -----------------------
    ("2025-04-02/M03/ses-01/M03_ses01_raw.zip", 1_400_000, "zip03"),
    ("2025-04-02/M03/ses-01/README", 800, "readme03"),

    # --- A full duplicate backup of M01 ------------------------------------
    ("backup/2025-03-14/M01/ses-01/raw/M01_ses01_g0_t0.imec0.ap.bin", 900_000, "ap01"),
    ("backup/2025-03-14/M01/ses-01/raw/M01_ses01_g0_t0.imec0.ap.meta", 2_000, "meta01"),
    ("backup/2025-03-14/M01/ses-01/raw/tracking.avi", 700_000, "vid01"),
    ("backup/2025-03-14/M01/ses-01/raw/behaviour.csv", 45_000, "behav01"),

    # --- Histology, stored entirely separately from the recordings ---------
    ("histology/M01/slide_01_DAPI.tif", 1_100_000, "histo01"),
    ("histology/M01/slide_02_GFP.tif", 1_100_000, "histo02"),
    ("histology/m02/slide_01.tif", 1_050_000, "histo03"),
    ("histology/notes.docx", 15_000, "histonotes"),

    # --- Lab-wide loose files ---------------------------------------------
    ("surgery_log.xlsx", 60_000, "surglog"),
    ("animal_list.xlsx", 25_000, "animals"),
    ("analysis_scripts/preprocess.m", 9_000, "code01"),
    ("analysis_scripts/plot_theta.py", 6_000, "code02"),
    ("analysis_scripts/old/preprocess.m", 9_000, "code01"),        # duplicate
    ("scratch/untitled.dat", 500_000, "scratch01"),
    ("scratch/test", 0, "empty2"),

    # --- Junk that should be excluded, not counted ------------------------
    (".DS_Store", 6_148, "junk"),
    ("2025-03-14/.DS_Store", 6_148, "junk"),
    ("histology/Thumbs.db", 4_000, "junk"),
)


def _content(seed: str, size: int) -> bytes:
    """Deterministic bytes: identical seeds yield byte-identical files."""
    if size == 0:
        return b""
    block = (seed.encode("utf-8") + b"-ndos-fixture-").ljust(64, b"\0")
    repeats = size // len(block) + 1
    return (block * repeats)[:size]


def build(root: Path, force: bool = False) -> Path:
    root = root.expanduser().resolve()
    if root.exists():
        if not force:
            raise FileExistsError(
                f"{root} already exists; pass --force to replace it"
            )
        shutil.rmtree(root)

    for relative, size, seed in LAYOUT:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_content(seed, size))
    return root


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a synthetic messy lab directory for NDOS demos and tests."
    )
    parser.add_argument("root", type=Path, help="Directory to create")
    parser.add_argument(
        "--force", action="store_true", help="Replace the directory if it exists"
    )
    args = parser.parse_args()

    try:
        root = build(args.root, force=args.force)
    except (FileExistsError, OSError) as error:
        parser.error(str(error))

    print(f"Created {len(LAYOUT)} files under {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
