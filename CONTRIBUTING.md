# Contributing

Thanks for helping stock contributors ship clean batches.

## Ground rules

* **Synthetic data only.** Never commit real contributor images, videos, CSVs, credentials or
  private file names. Generate fixtures in tests.
* **Source-backed rules.** A new or changed platform rule needs a source URL, the page's "last
  updated" date, the date you checked it, a verification status, and a test. Never mark a rule
  `verified` unless you read it on the live official page.
* **Honest results.** Do not weaken assertions, add `xfail`/`skip` to get a green build, or claim
  test results you did not run. Platform skips must say why.
* **No content rewriting.** Fixes must be mechanical, deterministic and allow-listed.

## Setup

```bash
python -m venv .venv
```

```bash
.venv/bin/python -m pip install -e ".[dev]"
```

## Checks (all must pass)

```bash
.venv/bin/ruff check src tests scripts
```

```bash
.venv/bin/ruff format --check src tests scripts
```

```bash
.venv/bin/mypy
```

```bash
.venv/bin/python -m pytest --cov=stockmetalint
```

If you change the registry, regenerate the catalog (a test fails when it is stale):

```bash
.venv/bin/stockmetalint rules list --format markdown > docs/rules.md
```

## Adding a rule

1. Add the rule to `src/stockmetalint/rules/*.json` with every required field.
2. Emit it through `ctx.emit("RULE-ID", ...)`.
3. Add a trigger to `tests/integration/test_rule_catalog.py` (every rule must be triggerable).
4. Add boundary tests, regenerate `docs/rules.md`, and update `CHANGELOG.md`.

## Pull requests

Use the PR template, keep changes focused, and describe what you verified and how.
