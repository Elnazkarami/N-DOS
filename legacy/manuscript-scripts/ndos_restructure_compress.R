#!/usr/bin/env Rscript
# Restructure files into N-DOS and compress per session.
# Usage:
#   Rscript ndos_restructure_compress.R --src /path/to/input --dst /path/to/project \
#     [--subject-pattern REGEX] [--session-pattern REGEX] [--dry-run] [--no-compress]

args <- commandArgs(trailingOnly = TRUE)
getArg <- function(flag, default=NULL){
  hit <- which(args == flag)
  if (length(hit)==0) return(default)
  if (hit == length(args)) return(TRUE)
  args[hit+1]
}

src <- getArg("--src")
dst <- getArg("--dst")
subj_pat <- getArg("--subject-pattern", "(?i)^(?:sub-|subject[-_]?)([A-Za-z0-9]+)|/(M\\d+|R\\d+|S\\d+)/")
sess_pat <- getArg("--session-pattern", "(?i)(\\\\d{8})(?:[-_]?\d{0,2})|/(\\\d{8})/")
dry_run <- !is.null(getArg("--dry-run"))
no_compress <- !is.null(getArg("--no-compress"))

if (is.null(src) || is.null(dst)) {
  stop("Missing --src or --dst")
}

first_group <- function(pattern, s, default) {
  m <- regexpr(pattern, s, perl=TRUE)
  if (m[1] == -1) return(default)
  # Extract groups
  matches <- attr(m, "capture.start")
  lens <- attr(m, "capture.length")
  if (is.null(matches)) return(substr(s, m[1], m[1]+attr(m,"match.length")-1))
  for (i in seq_along(matches)) {
    st <- matches[i]
    ln <- lens[i]
    if (!is.na(st) && ln > 0) {
      return(substr(s, st, st+ln-1))
    }
  }
  default
}

compute_dest <- function(f, dst_root, subj_pat, sess_pat){
  s <- normalizePath(f, winslash = "/", mustWork = FALSE)
  sub <- first_group(subj_pat, s, "unknown_subject")
  ses <- first_group(sess_pat, s, "unknown_session")
  file.path(dst_root, "raw_data", sub, ses, "raw", basename(f))
}

# move files
files <- list.files(src, recursive = TRUE, full.names = TRUE, all.files = FALSE, include.dirs = FALSE)
for (f in files) {
  dest <- compute_dest(f, dst, subj_pat, sess_pat)
  if (dry_run) {
    cat("[DRY]", f, "->", dest, "\n")
  } else {
    dir.create(dirname(dest), recursive = TRUE, showWarnings = FALSE)
    final <- dest
    i <- 1
    while (file.exists(final)) {
      ext <- tools::file_ext(dest)
      stem <- sub(paste0("\\\\.", ext, "$"), "", basename(dest))
      alt <- paste0(stem, "_", i, ifelse(nchar(ext)>0, paste0(".", ext), ""))
      final <- file.path(dirname(dest), alt)
      i <- i + 1
    }
    file.rename(f, final)
    cat("[MOVE]", f, "->", final, "\n")
  }
}

# compress per session
if (!dry_run && !no_compress) {
  archives <- file.path(dst, "archives")
  if (!dir.exists(archives)) dir.create(archives, recursive = TRUE, showWarnings = FALSE)
  raw_root <- file.path(dst, "raw_data")
  subs <- list.dirs(raw_root, recursive = FALSE, full.names = TRUE)
  for (sub in subs) {
    sess <- list.dirs(sub, recursive = FALSE, full.names = TRUE)
    for (se in sess) {
      raw_dir <- file.path(se, "raw")
      if (!dir.exists(raw_dir)) next
      tarfile <- file.path(archives, paste(basename(sub), basename(se), sep="_"))
      tarfile <- paste0(tarfile, ".tar.gz")
      old <- getwd(); setwd(dirname(raw_dir))
      utils::tar(tarfile, files = file.path(basename(se), "raw"), compression = "gzip")
      setwd(old)
      cat("[TAR]", tarfile, "\n")
    }
  }
}
