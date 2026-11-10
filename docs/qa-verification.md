# QA verification record

This file records checks that were **actually executed**, when, and with what result. CI
results on GitHub are not listed here because they live in the Actions run logs and artifacts.

## Local verification — 2026-11-09 (build environment: Linux x86_64, cloud container)

| Check | Command | Result |
|---|---|---|
| Lint | `ruff check src tests scripts` | All checks passed |
| Format | `ruff format --check src tests scripts` | 43 files already formatted |
| Types | `mypy` (strict, 27 source files) | Success: no issues found |
| Tests, Python 3.11.18 | `python -m pytest` | **315 passed**, 0 skipped, 0 failed |
| Tests, Python 3.12.3 | `python -m pytest --cov=stockmetalint --cov-branch` | **315 passed**, 0 skipped, 0 failed |
| Tests, Python 3.13.18 | `python -m pytest` | **315 passed**, 0 skipped, 0 failed |
| Coverage (3.12, branch) | see table below (2026-11-09; 95.3 % after the 2026-11-10 fixes) | **95.4 % total** |
| Build | `python -m build` | sdist + wheel built (`stockmetalint-0.1.0`) |
| Metadata | `twine check --strict dist/*` | PASSED (both files) |
| Wheel smoke | `python scripts/wheel_smoke.py dist/*.whl` (fresh venv, `--no-index --no-deps`) | 14/14 checks passed |
| README replay | clean `git clone` → `python -m venv` → `pip install .` → every README command | all exit codes as documented; README valid-output block identical to real output |
| Dependency audit | `pip-audit --skip-editable` (dev environment) | No known vulnerabilities found |
| Workflow lint | `actionlint .github/workflows/*.yml` | no issues |
| Secret / private-path scan | `git grep` for key, token and private-key patterns, home paths, email | no findings (only synthetic `secret.jpg` test names) |
| Tracked binaries | scan of `git ls-files` | 5 synthetic JPEGs in `examples/assets/` (632–633 bytes each) |

Optional tools present during the run: Pillow 13.0.0 and ffprobe 6.1.1, so the image-decode and
video-probe tests ran instead of being skipped.

### Branch coverage by module (Python 3.12)

| Module | Cover |
|---|---|
| validators/batch.py, context.py, hygiene.py, keywords.py, textutil.py, reporters/json_report.py, reporters/rules_report.py, errors.py | 100 % |
| validators/adobe.py | 99.3 % |
| domain.py | 97.5 % |
| cli.py | 96.3 % |
| fixes/safe.py | 95.2 % |
| rules/registry.py, safe_io.py | 94.7 % |
| csv_input.py | 93.9 % |
| engine.py | 93.5 % |
| asset_inventory.py | 92.8 % |
| inspection.py | 90.5 % |
| reporters/text_report.py | 88.5 % |
| `__main__.py` | 0 % (two-line entry shim; exercised through the `python -m stockmetalint` subprocess tests, which coverage does not trace) |

Uncovered lines are mostly OS-error branches (permission errors while listing directories,
`OSError` during `stat`) that cannot be triggered portably when tests run as root, plus a
few defensive fallbacks. No branch was excluded to raise the number.

## Adversarial review — 2026-11-10

An 8-dimension review workflow (parsing, Adobe rules, asset security, fix/IO safety, CLI contract,
cross-platform CI, spec honesty, test quality) reported about 40 candidate defects. Independent
verification finished for only part of them because the account usage limit was reached. Every
issue listed below was reproduced and fixed, and each has a regression test in
`tests/integration/test_review_regressions.py`:

* `fix` silently dropped all rows after a malformed record and exited 0 → now refuses (exit 1,
  nothing written).
* `--ignore` on a fatal rule turned an unreadable file into PASS → fatal reports always exit 1.
* The audit log overwrote existing files without `--overwrite` → now requires it; the audit is
  written first and removed if the CSV write fails.
* FIFOs and devices were accepted as `--output` → refused.
* A near-miss header ("Titles") claimed the column of a later exact header → exact headers win.
* A Category with >4,300 digits crashed (int conversion limit) → handled.
* Cells containing only zero-width characters passed required checks → now treated as empty.
* NFC/NFD-equivalent keywords were not duplicates → keyword keys are NFC-normalized.
* A near-duplicate check was skipped after an identical row → fixed.
* One diagnostic per blank line allowed memory exhaustion → capped at 20 plus a summary; `fix`
  records dropped blank records in the audit log.
* Non-UTF-8 file names crashed JSON output → encoded with escapes.
* PNG/progressive JPEG bombs below Pillow's limit were fully decoded → >40 MP is not decoded
  (INCONCLUSIVE, dimensions only).
* Pillow errors leaked absolute paths → scrubbed.
* `ffprobe` lookup could search the current directory on Windows → explicit PATH.
* Windows directory junctions were not treated like symlinks → now classified and never followed.
* Release extensions were case-sensitive, a "closest file" hint was quadratic, an out-of-range
  `SOURCE_DATE_EPOCH` crashed, usage errors echoed escape sequences, and string paths broke the
  library API → all fixed.
* A test (`test_case_variant_alias...`) would have failed on macOS/Windows → corrected.

Not changed (judged acceptable or deferred): an extension check that accepts any final dot segment,
and `PASS` with INCONCLUSIVE inspection info (documented: INCONCLUSIVE is not a pass, but it does
not block).

## What the suite proves

* **Boundaries** with fixture sanity checks: title 69/70/71, filename 29/30/31, keywords
  0/1/49/50/51 in both profiles, rows 5,000/5,001, bytes 1,000,000 / 1,000,001 / 1,048,576 /
  1,048,577.
* **Every one of the 72 rules fires** on a minimal synthetic input
  (`tests/integration/test_rule_catalog.py`). The test fails if a rule is added without a trigger.
* **Negative controls**: fixtures are asserted to be what they claim (exact lengths, really
  invalid UTF-8). `test_negative_control_limits_are_what_the_tests_depend_on` shows the boundary
  test fails when the limit is changed. The registry loader is fed 17 kinds of malformed JSON,
  and each is rejected.
* **No network**: lint with `--assets --inspect` succeeds while `socket` is patched to raise.
* **Performance**: a 5,000-row file lints in well under the 10 s budget with a traced peak below
  64 MiB.
* **Determinism**: repeated runs produce identical reports; `--reproducible` JSON is
  byte-identical.
* **End to end**: a subprocess flow goes generated CSV → lint → JSON file → exit 1 → fix output,
  and the original checksum is unchanged.

## Not verified yet

* **GitHub Actions** (Linux/macOS/Windows × 3.11–3.13): not run. The repository
  `hanifwidi/stockmetalint` did not exist yet and this session cannot create it.
* **Windows and macOS** behaviour was not executed locally. Platform-specific tests skip with an
  explicit reason (symlinks on Windows, case-sensitive file system on Windows/macOS).
* **Adobe limits on live pages**: not verified (network policy). See rule-sources.md.
