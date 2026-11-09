# Competitive landscape

Checked on **2026-11-09**. Repository facts (last push, license) come from the GitHub search
API; descriptions come from each project's README. Commercial products were checked only through
search-result snippets. No stars, download counts or user numbers are quoted, because adoption
is not evidence of fitness for this purpose.

| Project | What it does | Last push / license | Overlap | How StockMetaLint differs | Verified via |
|---|---|---|---|---|---|
| [stock-gate](https://github.com/jasveerai88/stock-gate) | Stdlib-only Python CLI that checks a metadata CSV against encoded Adobe/Vecteezy/Dreamstime rules; `--json`, exit codes 0/1/2 | 2026-11-04 / MIT | **Closest match**: title/filename/row/size limits, repeated keywords, local-only, JSON | Its README describes lenient headers (aliases, extra columns) and a 49-keyword Adobe cap. No fixer, asset-file matching, or formula/path checks were found in its README or source. | search API, README, source grep |
| [riefkyhd/adobe-stock-csv-generator](https://github.com/riefkyhd/adobe-stock-csv-generator) | Resumable CLI generating Adobe CSV rows with local or cloud LLMs, validating rows before writing | 2026-03-31 / MIT | Exact header, UTF-8, numeric category 1–21, `--validate-only` | Generator first; 49-keyword cap; no JSON diagnostics or security checks documented | search API, README, `docs/CSV_SPEC.md` |
| [israk404/adobe-stock-metadata-csv-generator](https://github.com/israk404/adobe-stock-metadata-csv-generator) | Gemini-based generator of titles/keywords/category; renames and moves files | 2026-07-29 / MIT | Same 5-column CSV, keyword dedupe, dry run | Cloud AI; moves files; validates only its own output | search API, README |
| [zaknbr/adobe-stock-seo](https://github.com/zaknbr/adobe-stock-seo) | Browser app generating metadata with Gemini and exporting CSV | 2026-10-02 / none detected | Same header | Cloud generation; no validation described | search API, README |
| [savelevvo/photostock-csv-skills](https://github.com/savelevvo/photostock-csv-skills) | Claude Code plugin: AI image analysis that writes and validates Adobe/Shutterstock CSVs | 2026-07-26 / MIT | Row/size/filename/keyword limits | LLM-driven, not deterministic | search API, README |
| [stock-export-core](https://github.com/talexdes-plg/stock-export-core) | Dependency-free Python library/CLI that turns JSON records into agency CSVs | 2026-08-13 / MIT | Deterministic, offline, no AI | Exporter, not a linter of existing CSVs | search API, README |
| [StockMeta Pro (Kiriiaq/StockMeta)](https://github.com/Kiriiaq/StockMeta) | Windows GUI: metadata from IPTC, optional local LLM, CSV export, FTP upload | 2026-07-30 / MIT code, paid Pro key | Offline-first, per-image pre-upload checks | GUI generator/uploader; checks images, not the CSV; no CI/JSON output documented. **Similar name: see note.** | search API, README |
| [Xpiks](https://github.com/ribtoks/xpiks) | Open-source Qt keywording/upload app with pre-upload checks | 2023-12-15 / unverified | Pre-upload checks | Edits embedded XMP/IPTC, not CSV; maintenance unverified | search API, fork README |
| [ExifTool](https://github.com/exiftool/exiftool) | Reads/writes embedded metadata; `-csv` import/export | 2026-11-05 / GPL-3.0 (GitHub API) | Local metadata ↔ CSV | Tag-level CSVs; no Adobe rules | search API, README |
| [frictionless-py](https://github.com/frictionlessdata/frictionless-py) | Generic tabular data validation framework | 2026-10-15 / MIT | Schema validation reports | Generic; no Adobe template or asset matching | search API, README |
| [csvlint.rb](https://github.com/Data-Liberation-Front/csvlint.rb) | Ruby CSV structure/dialect/schema validator | 2026-11-08 / MIT | Structural linting | Generic, Ruby | search API, README |
| [csvkit](https://github.com/wireservice/csvkit) | CSV CLI suite; `csvclean` reports and fixes structural errors | 2026-11-09 / MIT | Structural checks, mechanical fixes | Generic; no Adobe or security rules | search API, README |
| [defusedcsv](https://github.com/raphaelm/defusedcsv) | Drop-in `csv` writer that defuses spreadsheet formula injection | 2025-09-03 / Apache-2.0 | Formula-injection defence | Escapes on write; does not lint metadata | search API description |
| StockSubmitter | Commercial app for filling metadata and uploading to many agencies | unknown / proprietary | Metadata preparation | Closed, upload-centric; no CSV linting found | search snippets only |

## Differentiation

1. **Preflight verification, not generation.** StockMetaLint never creates or rewrites titles or
   keywords. AI generators are complementary: lint their output before uploading it.
2. **Source-locked, versioned rules** with per-rule citations and an explicit verification
   status, including documented discrepancies (50 vs 49 keywords).
3. **Asset matching with containment**: exact/case/Unicode mismatches, orphans, symlink escape.
4. **Security-aware CSV handling**: formula injection, terminal escape sequences, path traversal,
   and alias-proof atomic output.
5. **CI-grade output**: stable JSON schema, deterministic ordering, precise exit codes.

## Notes and limitations

* **Name similarity:** "StockMeta Pro" (Kiriiaq/StockMeta) exists. "StockMetaLint" is distinct,
  but the maintainer may want to consider this before publishing.
* Commercial products (StockSubmitter, ImStocker, ProStockMaster and similar) were seen only in
  search snippets; their features are unverified.
* This research was done by searching GitHub and the web on one day. It is not exhaustive and
  shows no evidence of market demand.
