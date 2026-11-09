# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `stockmetalint` CLI with `--version`, `doctor`, `rules list|show`, `lint` and `fix`, plus a
  typed library API (`lint_path`, `lint_bytes`, `LintOptions`, `Report`).
- Versioned rule registry `adobe-csv-2026-06` (30 Adobe-sourced rules) and `stockmetalint-core-1`
  (42 tool-defined rules). Every rule records its source URL, page date, verification status and
  `verified_at`. All Adobe rules are **unverified** against live pages
  (see docs/rule-sources.md).
- Strict CSV input: UTF-8 with BOM support; detection of binary/XLSX, UTF-16, NUL bytes, invalid
  UTF-8 (with byte offsets), malformed quoting, field-count mismatches and blank records; separate
  physical line and data-row positions.
- Adobe CSV checks: file type, 1 MB (MB/MiB-aware) size, 5,000 rows, exact template header,
  Filename (≤30, extension, no paths), Title (≤70 code points, comma advisory), Keywords (1–50),
  Category (numeric, seed list 1–21), Releases (≤30). The 49-keyword guidance is a separate,
  non-blocking `editorial` profile rule.
- Keyword hygiene: case/whitespace and NFKC duplicates, empty items, non-comma separators,
  heuristic low-value terms. Batch checks: duplicate or colliding filenames, review warnings for
  identical titles and identical or near-duplicate keyword sets.
- Security checks: formula-injection prefixes, bidi and invisible characters, terminal-safe
  output.
- `--assets` matching with case/Unicode mismatch detection, orphans, symlink containment,
  `--recursive`, `--releases`, and `--inspect` (signatures; optional Pillow decode and ffprobe
  probe, INCONCLUSIVE when unavailable).
- `fix`: dry run by default, allow-listed mechanical rules, atomic alias-proof output, formula
  refusal by default, SHA-256 audit log.
- JSON report schema v1, deterministic ordering, `--reproducible`.
- CI on Linux/macOS/Windows × Python 3.11–3.13, packaging smoke test, dependency audit, and a
  disabled-by-default Trusted Publishing release workflow.
