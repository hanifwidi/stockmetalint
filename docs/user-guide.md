# User guide

## 1. Prepare the CSV

Use the template header exactly: `Filename,Title,Keywords,Category,Releases`. Put the whole
keyword list in **one quoted cell**: `"sunset, beach, ocean"`. If you work in Excel, save with
**CSV UTF-8 (Comma delimited)**.

## 2. Lint the metadata

```bash
stockmetalint lint batch.csv
```

Read each finding as `location · severity · RULE-ID · message`, followed by a `->` suggestion.
`stockmetalint rules show RULE-ID` explains a rule, its source and its verification status.

* **error**: blocks (exit 1). Fix it before uploading.
* **warning**: likely problem or documented guidance (exit 0 unless `--fail-on-warning`).
* **info**: hint; never blocks.

Use `--profile editorial` to add the non-blocking 49-keyword guidance advisory.

## 3. Check the media folder

```bash
stockmetalint lint batch.csv --assets ./upload-folder
```

This reports rows without a matching file (`ASSET-MISSING`), case or Unicode spelling mismatches,
files without a row (`ASSET-ORPHAN`), empty files, and links that leave the folder. Add
`--recursive` for subfolders (symlinked folders are never followed) and `--inspect` for format
checks:

```bash
stockmetalint lint batch.csv --assets ./upload-folder --inspect
```

`--inspect` checks file signatures against extensions (a `.jpg` that is really a PNG), decodes
JPEG/PNG with Pillow, and probes MP4/MOV with ffprobe when they are installed. These are **format**
checks plus advisories from Adobe's media pages (resolution, size, codec, duration); they never
judge content or quality. Missing tools produce `ASSET-INSPECT-INCONCLUSIVE`.

To check release names against local release JPEGs:

```bash
stockmetalint lint batch.csv --releases ./releases
```

## 4. Apply safe fixes (optional)

```bash
stockmetalint fix batch.csv
```

Without `--output` this is a dry run that prints every proposed change. To write a new file:

```bash
stockmetalint fix batch.csv --output batch.fixed.csv
```

This also writes `batch.fixed.csv.audit.json` with SHA-256 checksums and every change. The source
CSV is never modified.

| Fix rule | Default | What it does |
|---|---|---|
| `trim-whitespace` | yes | trims Title, each keyword, Category, Releases (never Filename) |
| `drop-empty-keywords` | yes | removes empty items such as `sky,,sun` |
| `dedupe-keywords` | no | removes repeated keywords, keeping the first occurrence and order |
| `nfc` | no | Unicode NFC for Title and Keywords |
| `canonical-header` | no | renames near-miss headers (`filename` → `Filename`) |

Choose rules explicitly with `--fix-rules trim-whitespace,dedupe-keywords`. Content problems
(long titles, too many keywords, wrong category) are never "fixed" automatically.

## 5. Use it in CI

```bash
stockmetalint lint metadata/batch.csv --assets media/ --format json --output reports/stockmetalint.json --reproducible
```

Exit codes: `0` pass, `1` validation failure, `2` usage or runtime failure. The JSON layout is
`src/stockmetalint/schemas/report-v1.schema.json`. `--reproducible` removes the wall-clock
timestamp (or uses `SOURCE_DATE_EPOCH`), making reports byte-identical between runs.

## 6. Library use

```python
from stockmetalint import LintOptions, lint_path

report = lint_path("batch.csv", LintOptions(assets_dir="media"))
for d in report.diagnostics:
    print(d.severity, d.code, d.row, d.message)
```
