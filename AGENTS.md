# Guidance for AI coding agents and automated contributors

These rules apply to any agent (Claude Code, Codex, Copilot, etc.) working in this repository.

## Non-negotiable

1. **Never claim results you did not observe.** Report test counts, coverage and CI status only
   from actual command output. If something was not run, say "not run".
2. **Never weaken tests to pass**: no skipping, `xfail`, loosened assertions, or fake platform
   fallbacks that return the expected answer. A platform skip must state its reason.
3. **Never mark a platform rule `verified`** unless the live official page was read in this
   change; record `verified_at` and the page's "last updated" date.
4. **Synthetic data only.** Do not add real contributor media, CSVs, credentials or private paths.
5. **No network access in product code**, and no telemetry, uploads or AI calls.
6. **Do not merge, tag, release or publish** without the owner's explicit approval.
7. **Fixes stay mechanical**: never generate, reorder, translate or truncate titles or keywords.

## Workflow

* Run the full check set before proposing changes:
  `ruff check src tests scripts`, `ruff format --check src tests scripts`, `mypy`,
  `pytest --cov=stockmetalint`.
* Keep `docs/rules.md` generated from the registry (`stockmetalint rules list --format markdown`).
* Add every new rule to the registry JSON *and* to `tests/integration/test_rule_catalog.py`.
* Keep zero runtime dependencies; optional tools must degrade to INCONCLUSIVE.
* Write source files in ASCII; express invisible or bidi characters as `\uXXXX` escapes.
