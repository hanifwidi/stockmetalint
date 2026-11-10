# Release checklist (0.1.0) — preparation only

Nothing in this checklist has been executed for publication. **No tag, GitHub release or PyPI
upload exists or may be created without the owner's explicit approval.**

## Already verified locally (see qa-verification.md)

- [x] `python -m build` produces `stockmetalint-0.1.0.tar.gz` and
      `stockmetalint-0.1.0-py3-none-any.whl`
- [x] `twine check --strict dist/*` passes
- [x] Wheel installs offline into a fresh venv (`--no-index --no-deps`) and the CLI smoke test
      passes (`scripts/wheel_smoke.py`)
- [x] Distribution name: `https://pypi.org/pypi/stockmetalint/json` returned HTTP 404 on
      2026-11-09 (name not registered at that time; re-check right before publishing)

## Before tagging

- [x] CI green on `main` for merge commit 7941ecf (15/15 checks, 2026-11-10)
- [x] Release notes clearly say the Adobe rules are "unverified" (live re-verification still open)
- [x] `CHANGELOG.md` has the release date (2026-11-10); `_version.py` is `0.1.0`
- [ ] README quickstart re-run on a clean machine
- [x] Owner approved release of v0.1.0 on 2026-11-10 (including the name)

## One-time PyPI Trusted Publisher setup (owner only)

1. Sign in to PyPI and open **Your projects → Publishing → Add a new pending publisher**.
2. Enter: PyPI project name `stockmetalint`, owner `hanifwidi`, repository `stockmetalint`,
   workflow `release-pypi.yml`, environment `pypi`.
3. On GitHub, create **Settings → Environments → `pypi`** with required reviewers (the owner),
   and restrict deployments to the `main` branch.
4. Set the repository variable **`PYPI_PUBLISHING_APPROVED`** to `true` (Settings → Secrets and
   variables → Actions → Variables). Until then the workflow's jobs are skipped.

No API token is created or stored; publishing uses short-lived OIDC credentials.

## Publishing (only after explicit approval)

1. Merge the release PR (owner approval).
2. Create the tag and GitHub release `v0.1.0` from `main`.
3. Run **Actions → Release to PyPI → Run workflow** with `version=0.1.0`, then approve the
   `pypi` environment deployment.
4. In a fresh environment, install `stockmetalint==0.1.0` from PyPI, then run
   `stockmetalint --version` and `stockmetalint doctor`.
