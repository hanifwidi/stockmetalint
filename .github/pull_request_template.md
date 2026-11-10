## Summary

<!-- What changes and why. -->

## Rule sources (if a platform rule changed)

<!-- Official URL, page "last updated" date, date you checked it, verification status. -->

## Verification

<!-- Commands you actually ran and their real results. Do not claim results you did not observe. -->

- [ ] `ruff check src tests scripts` and `ruff format --check src tests scripts`
- [ ] `mypy`
- [ ] `python -m pytest --cov=stockmetalint`
- [ ] `docs/rules.md` regenerated if the registry changed
- [ ] New rules have a trigger in `tests/integration/test_rule_catalog.py`

## Checklist

- [ ] Synthetic test data only; no real contributor files, metadata or credentials
- [ ] No skipped/xfailed/weakened tests to get green
- [ ] No implied Adobe affiliation or acceptance guarantee
- [ ] CHANGELOG.md updated
