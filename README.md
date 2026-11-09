# StockMetaLint

**Catch stock metadata problems before your batch upload.**

StockMetaLint is an offline-first Python CLI and library that checks an Adobe Stock contributor
metadata CSV *before* you upload it. It validates the file against a versioned, source-cited
rule registry, matches every `Filename` to your local media files, flags deterministic
metadata problems (lengths, counts, duplicates, broken headers, encoding, CSV injection, path
traversal) and emits stable JSON that you can gate a CI pipeline on.

> **Unofficial — not affiliated with, endorsed by, or sponsored by Adobe.** "Adobe" and
> "Adobe Stock" are trademarks of Adobe. A clean StockMetaLint report does **not** guarantee
> upload acceptance, approval, moderation outcome or search ranking.

> **Rule verification status: UNVERIFIED.** The official Adobe help pages could not be fetched
> from the build environment (network policy), so limits are seeded from the project brief and
> corroborated with search-engine snippets of those pages. Every rule records its source URL and
> verification status; run `stockmetalint rules show <RULE-ID>`. See
> [docs/rule-sources.md](docs/rule-sources.md) before relying on a limit.

## Why another tool?

Existing tools mostly *generate* metadata (often with AI), rename files, or validate generic CSV
structure. StockMetaLint does none of that. It is a **preflight verifier**:

| | StockMetaLint |
|---|---|
| Generates titles/keywords | **No** — never invents, reorders or truncates metadata |
| Needs an account, API key or network | **No** — fully offline, zero runtime dependencies |
| Knows the Adobe CSV template and limits | Yes, versioned and source-cited |
| Matches CSV rows to your media folder | Yes, exact names, symlink-safe |
| Machine-readable output for CI | Yes, JSON with a published schema and exit codes |
| Modifies your files | Never in place; `fix` is a dry run unless you pass `--output` |

See [docs/competitive-landscape.md](docs/competitive-landscape.md) for an honest comparison with
related projects.

## Install

Requires Python 3.11+. StockMetaLint is **not yet published on PyPI**; install from a clone:

```bash
git clone https://github.com/hanifwidi/stockmetalint.git
```

```bash
cd stockmetalint
```

```bash
python -m venv .venv
```

Activate the environment (Linux/macOS: `source .venv/bin/activate`; Windows PowerShell:
`.venv\Scripts\Activate.ps1`), then:

```bash
python -m pip install .
```

Optional image decode checks for `lint --inspect` need Pillow:

```bash
python -m pip install ".[images]"
```

Video checks use `ffprobe` from FFmpeg if it is on your `PATH`. Without these tools the
affected checks are reported as **INCONCLUSIVE**, never as passed.

## Quick start

A valid batch exits 0:

```text
$ stockmetalint lint examples/adobe-valid.csv
adobe-valid.csv: 5 data row(s) · platform adobe-csv · profile standard · rules adobe-csv-2026-06 (unverified)

Result: 0 error(s), 0 warning(s), 0 info -> PASS (exit 0)
Unofficial preflight check, not affiliated with Adobe. A clean result does not guarantee upload acceptance, approval or ranking.
```

An invalid batch exits 1 with exact physical line and data-row positions (output shortened):

```text
$ stockmetalint lint examples/adobe-invalid.csv --assets examples/assets
adobe-invalid.csv: 6 data row(s) · platform adobe-csv · profile standard · rules adobe-csv-2026-06 (unverified)

  coffee-cup-003.jpg
    warning  ASSET-ORPHAN  "coffee-cup-003.jpg" has no row in the CSV.
             -> Add a CSV row for it or move it out of the batch folder.
  line 2 · row 1 · Title
    error    ADOBE-CSV-TITLE-LENGTH  Title is 87 characters; the limit is 70: "Golden sunrise over a calm tropical beach with palm trees, …"
             -> Shorten the title to 70 characters or fewer. StockMetaLint never truncates text.
  line 2 · row 1 · Keywords
    warning  META-KEYWORD-DUPLICATE  Duplicate keywords: "Beach" (#4) repeats "beach" (#2).
             -> Remove the repeats (fix rule: dedupe-keywords keeps the first occurrence).
  line 3 · row 2 · Filename
    error    ASSET-CASE-MISMATCH  No file named "Rice-Terrace-002.jpg"; "rice-terrace-002.jpg" differs only by letter case.
  ...
Result: 9 error(s), 9 warning(s), 1 info -> FAIL (exit 1) [assets matched]
```

`line` is the physical line where the record starts (quoted cells can span lines); `row` is the
data-row number (header and blank records excluded).

## Commands

```bash
stockmetalint --version
stockmetalint doctor
stockmetalint rules list --platform adobe-csv
stockmetalint rules show ADOBE-CSV-TITLE-LENGTH
stockmetalint lint ./examples/adobe-valid.csv --platform adobe-csv
stockmetalint lint ./examples/adobe-invalid.csv --platform adobe-csv --assets ./examples/assets
stockmetalint lint ./examples/adobe-invalid.csv --platform adobe-csv --format json --output ./reports/validation.json
stockmetalint lint ./examples/adobe-invalid.csv --platform adobe-csv --fail-on-warning
stockmetalint fix ./examples/adobe-invalid.csv --platform adobe-csv --dry-run
stockmetalint fix ./examples/adobe-invalid.csv --platform adobe-csv --output ./reports/adobe-proposed.csv
```

Note: the last command exits 1 without writing anything, because the example contains a
formula-like title (`=HYPERLINK(...)`). Output containing such cells is refused unless you pass
`--formula-policy escape` (see [Security](#security-and-privacy)).

Useful `lint` options: `--profile editorial` (adds non-blocking guidance advisories),
`--assets DIR` (`--recursive`, `--inspect`), `--releases DIR`, `--ignore RULE-ID`,
`--reproducible` (no wall-clock timestamp; honours `SOURCE_DATE_EPOCH`), `--show-paths`,
`--color auto|always|never` (auto respects `NO_COLOR` and TTY detection). Run
`stockmetalint lint --help` for everything.

## Exit statuses

| Code | Meaning |
|---|---|
| `0` | No blocking findings (warnings and info do not fail unless `--fail-on-warning`) |
| `1` | Validation failure: at least one error (including unreadable/empty/non-UTF-8 CSV), or a warning with `--fail-on-warning`; for `fix`, refused output or remaining errors |
| `2` | Usage, configuration, input/output or internal failure: unknown option or rule ID, missing/unreadable file or directory, input above the safety cap, output path that aliases the input |

## JSON report

`--format json` prints only JSON on stdout (messages go to stderr). The layout is versioned
(`schema_version`) and described by
[`src/stockmetalint/schemas/report-v1.schema.json`](src/stockmetalint/schemas/report-v1.schema.json).
Diagnostics are sorted deterministically: file-level findings first, then by row and rule ID.

```json
{
  "schema_version": "1.0",
  "tool": "stockmetalint",
  "tool_version": "0.1.0",
  "platform": "adobe-csv",
  "profile": "standard",
  "rule_profile_version": "adobe-csv-2026-06",
  "rule_verification": "unverified",
  "source_file": "adobe-invalid.csv",
  "checked_at": null,
  "summary": {"errors": 7, "warnings": 7, "info": 1, "total": 15, "data_rows": 6,
              "fatal": false, "assets_checked": false, "media_inspected": false, "exit_code": 1},
  "diagnostics": [
    {
      "severity": "warning",
      "code": "ADOBE-CSV-TITLE-COMMA",
      "scope": "adobe-csv",
      "source_url": "https://helpx.adobe.com/stock/contributor/manage-your-portfolio/csv-requirements-content.html",
      "line": 2,
      "row": 1,
      "column": "Title",
      "filename": "sunrise-beach-001.jpg",
      "message": "Title contains a comma: \"Golden sunrise over a calm tropical beach with palm trees, …\"",
      "suggestion": "Rephrase without commas; keep keyword lists in the Keywords column."
    }
  ]
}
```

(Excerpt of `stockmetalint lint examples/adobe-invalid.csv --format json --reproducible`; the
real output also contains a `disclaimer` field and all diagnostics.)

## Adobe CSV rules (profile `adobe-csv-2026-06`)

| Rule | Limit | Severity |
|---|---|---|
| File type | `.csv` | error |
| File size | > 1,048,576 bytes is an error; 1,000,001–1,048,576 bytes is a warning (MB vs MiB is not specified) | error / warning |
| Data rows | 5,000 | error |
| Encoding | UTF-8 (a UTF-8 BOM is accepted) | error |
| Header | exactly `Filename,Title,Keywords,Category,Releases`; Filename/Title/Keywords required | error (optional/ordering: warning) |
| Filename | bare file name with extension, ≤ 30 characters | error |
| Title | required, ≤ 70 characters (Unicode code points); commas discouraged | error / warning |
| Keywords | 1–50 comma-separated keywords (CSV scope) | error |
| Category | ASCII digits; outside seed list 1–21 → warning | error / warning |
| Releases | each release name ≤ 30 characters | error |

**Known discrepancy:** the CSV page allows **50** keywords while Adobe guidance pages say
"up to **49** per content submission". These are modelled as two separate rules with different
scopes: CSV rows only fail above 50, and the 49 figure is a non-blocking advisory in
`--profile editorial`. Details: [docs/rule-discrepancies.md](docs/rule-discrepancies.md). Full
catalog of all 72 rules: [docs/rules.md](docs/rules.md).

Rules named `META-*`, `BATCH-*`, `SEC-*`, `ASSET-*` and `CSV-*` are StockMetaLint's own
integrity, hygiene and security checks, not Adobe policy. Heuristic checks are labelled
**HEURISTIC** or **REVIEW** and never claim that Adobe will reject anything.

## Feature support matrix

| Feature | Status |
|---|---|
| Adobe Stock CSV structure, header, field and batch rules | Supported |
| Unicode-aware lengths (code points; UTF-16 advisory), NFC/NFKC duplicate detection | Supported |
| Asset folder matching (exact/case/Unicode mismatches, orphans, symlink containment) | Supported |
| File signature checks (`--inspect`) | Supported |
| JPEG decode + resolution advisory (`--inspect`) | Needs Pillow (`[images]` extra) |
| Video container/codec/duration advisory (`--inspect`) | Needs `ffprobe` |
| Safe mechanical fixes (whitespace, empty/duplicate keywords, NFC, header spelling) | Supported, opt-in allow-list |
| Other agencies (Shutterstock, Getty, …) | Not yet — see [roadmap](docs/roadmap.md) |
| Embedded XMP/IPTC metadata | Not yet |
| Visual/semantic checks (does the title match the image?) | Out of scope: needs human review |

## Security and privacy

* **Offline by default.** No network calls, telemetry, uploads or account logins.
* CSV content is never executed. Text output escapes control characters and terminal escape
  sequences.
* `Filename` values that look like paths (`../`, `/abs`, `C:\`, URLs) are errors and are never
  resolved against the file system.
* The asset scan never follows a symlinked directory and never reads a file that links outside
  the asset directory.
* `fix` never overwrites the source (direct path, symlink, hard link or case-variant alias) and
  writes atomically. Cells starting with `= + - @`, tab or CR are **refused** in output unless you
  explicitly choose `--formula-policy escape`, which prefixes `'`. This changes the value Adobe
  would import, so review the file before uploading it.
* Reports show base file names by default, so home-directory paths do not leak; `--show-paths`
  opts in.

Details: [docs/security-model.md](docs/security-model.md). Vulnerability reports:
[SECURITY.md](SECURITY.md).

## Limitations

* Adobe limits are **unverified against the live pages** in this release (see above).
* A passing report covers metadata structure only. It says nothing about content quality,
  intellectual-property clearance, model releases or moderation.
* Title, filename and release lengths are counted in Unicode code points; how Adobe counts is
  not documented. A UTF-16 advisory flags emoji-heavy text.
* Keyword relevance cannot be judged deterministically. The low-value keyword list is a small
  heuristic.

## Troubleshooting

* **"Invalid UTF-8 byte 0xE9 …" (Windows/Excel):** save with *File → Save As → CSV UTF-8
  (Comma delimited)*. Plain "CSV (Comma delimited)" uses a legacy code page.
* **Garbled characters in a Windows console:** use Windows Terminal, or set
  `PYTHONUTF8=1`. JSON output is always UTF-8.
* **"File content is a ZIP container" (CSV-FILE-BINARY):** you passed an `.xlsx` workbook;
  export it as CSV first.
* **`ASSET-UNICODE-MISMATCH` on macOS:** the file name on disk is decomposed (NFD). Rename the
  file or the cell so both use the same spelling.
* **Colors:** disabled automatically when output is not a terminal or `NO_COLOR` is set; force
  with `--color always|never`.

## Development

```bash
python -m pip install -e ".[dev]"
```

```bash
python -m pytest
```

```bash
ruff check src tests scripts && ruff format --check src tests scripts && mypy
```

CI runs lint, strict typing, and the test suite on Linux, macOS and Windows for Python 3.11–3.13.
It also builds the sdist and wheel, installs the wheel offline into a fresh environment, smoke-tests
the CLI, and runs a dependency audit. See [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/qa-verification.md](docs/qa-verification.md).

## License

[MIT](LICENSE) © 2026 hanifwidi. All example data in this repository is synthetic.
