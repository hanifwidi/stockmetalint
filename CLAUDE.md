# CLAUDE.md

Read and follow [AGENTS.md](AGENTS.md); it applies in full.

Project quick facts:

* Package `stockmetalint` (src layout), Python 3.11+, zero runtime dependencies, argparse CLI.
* Single source of rule limits: `src/stockmetalint/rules/*.json`, loaded by `rules/registry.py`.
* Entry points: `engine.lint_path` (library) and `cli.main` (CLI). Exit codes 0/1/2.
* Checks: `ruff check src tests scripts && ruff format --check src tests scripts && mypy &&
  python -m pytest`.
* The Adobe rules are **unverified** against live pages; keep that label until a maintainer
  verifies them (docs/rule-sources.md).
* Unofficial project: never imply Adobe affiliation or guaranteed acceptance.
