# feat: Adobe Stock CSV preflight linter MVP (v0.1.0)

## Summary

First implementation of **StockMetaLint**, an offline-first CLI and library that validates Adobe
Stock contributor metadata CSVs before batch upload. It is unofficial and not affiliated with
Adobe.

* CLI: `--version`, `doctor`, `rules list|show`, `lint`, `fix` (argparse, zero runtime
  dependencies); exit codes 0/1/2.
* Versioned registry `adobe-csv-2026-06` (30 Adobe-sourced rules) plus `stockmetalint-core-1`
  (42 tool-defined rules), each with source URL, page date, scope, severity, limit,
  verification status and `verified_at`.
* Strict UTF-8/CSV input with separate physical-line and data-row positions; header, filename,
  title, keyword, category, release and batch checks; Unicode-aware lengths; NFKC duplicates.
* `--assets` exact matching with case/Unicode mismatch detection, orphans and symlink
  containment; `--inspect` format checks (Pillow/ffprobe optional, INCONCLUSIVE when absent).
* `fix`: dry run by default, allow-listed mechanical rules, atomic output that cannot alias the
  source, formula-injection refusal by default, SHA-256 audit log.
* JSON report schema v1, deterministic ordering, `--reproducible`.
* CI on Linux/macOS/Windows × Python 3.11–3.13 with actions pinned to verified commit SHAs, a
  packaging smoke test and pip-audit. The Trusted Publishing release workflow is gated and
  disabled.

## Official sources (unverified against live pages)

`helpx.adobe.com` was blocked by the build environment's network policy, so every Adobe rule
is labelled `snippet-corroborated`, `summary-corroborated` or `partially-corroborated`, with
`verified_at: null`. Sources and verbatim snippets are in `docs/rule-sources.md`.

* CSV requirements (page dated 2026-06-11 per brief): https://helpx.adobe.com/stock/contributor/manage-your-portfolio/csv-requirements-content.html
* Tips for effective titles and keywords (2026-09 per brief): https://helpx.adobe.com/stock/contributor/content-policies-guidelines/metadata/tips-effective-titles-keywords.html
* Discrepancy: 50 keywords (CSV) vs 49 (guidance). Modelled as separate scopes; the 49 figure is
  a non-blocking `editorial` advisory (`docs/rule-discrepancies.md`).

## Tests (executed locally on 2026-11-09)

* `ruff check`, `ruff format --check`: clean. `mypy --strict`: no issues (27 files).
* pytest: **297 passed, 0 skipped** on Python 3.11.18, 3.12.3 and 3.13.18 (Linux).
* Branch coverage **95.4 %** total; validators 99–100 %.
* `python -m build` + `twine check --strict`: passed. Offline fresh-venv wheel smoke: 14/14.
* README quickstart replayed in a clean clone: all exit codes as documented.
* pip-audit: no known vulnerabilities. actionlint: no issues.

Details: `docs/qa-verification.md`.

## Known limitations

* Adobe limits are not verified against live pages; re-verification steps are in
  `docs/rule-sources.md`.
* Windows/macOS were not run locally; they are covered by the CI matrix.
* A passing report covers metadata structure only, not content, quality or acceptance.
* "StockMeta Pro" is an existing project with a similar name (`docs/competitive-landscape.md`).

## Review checklist

- [ ] CI green on all OS × Python jobs, package and audit
- [ ] Rule limits and header match the live Adobe pages (or the label stays "unverified")
- [ ] Security model reviewed: path traversal, symlinks, formula injection, alias-proof output
- [ ] JSON schema and exit codes acceptable as a v1 contract
- [ ] No merge, tag, release or PyPI publish without explicit owner approval
