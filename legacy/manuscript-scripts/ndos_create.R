#!/usr/bin/env Rscript
# Create N-DOS project scaffold.
# Usage: Rscript ndos_create.R /path/to/project [--force]

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 1) {
  stop("Usage: Rscript ndos_create.R /path/to/project [--force]")
}
root <- args[1]
force <- any(args == "--force")

dirs <- c("raw_data","processed_data","analysis","figures","scripts")
if (!dir.exists(root)) dir.create(root, recursive = TRUE, showWarnings = FALSE)
for (d in dirs) {
  p <- file.path(root, d)
  if (dir.exists(p) && !force) next
  dir.create(p, recursive = TRUE, showWarnings = FALSE)
}
readme <- file.path(root, "README.md")
if (!file.exists(readme) || force) {
  writeLines(c("# N-DOS Project", "", "This project follows the N-DOS layout."), readme)
}
cat("[OK] Created/updated N-DOS scaffold at:", root, "\n")
