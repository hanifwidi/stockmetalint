from __future__ import annotations

import json
from importlib import resources
from typing import Any

import pytest

from stockmetalint.errors import ConfigError, RegistryError
from stockmetalint.rules import registry as reg
from stockmetalint.rules.registry import RULE_ID_RE, load_registry


def _raw(name: str) -> dict[str, Any]:
    text = resources.files("stockmetalint.rules").joinpath(name).read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def test_registry_loads_with_required_per_rule_fields() -> None:
    registry = load_registry()
    assert registry.profile_id == "adobe-csv-2026-06"
    assert registry.template_header == ("Filename", "Title", "Keywords", "Category", "Releases")
    assert registry.required_columns == {"Filename", "Title", "Keywords"}
    for rule in registry.rules.values():
        assert RULE_ID_RE.match(rule.rule_id)
        assert rule.source_url.startswith("https://")
        assert rule.description and rule.title
        assert rule.verified_at is None  # nothing could be verified against live pages
        assert rule.verification != "verified"


def test_adobe_rules_cite_adobe_sources_and_are_labelled_unverified() -> None:
    registry = load_registry()
    adobe = [r for r in registry.rules.values() if r.rule_id.startswith("ADOBE-")]
    assert len(adobe) == 30
    for rule in adobe:
        assert rule.source_url.startswith("https://helpx.adobe.com/stock/contributor/")
    assert registry.verification_label == "unverified"


@pytest.mark.parametrize(("rule_id", "limit"), [
    ("ADOBE-CSV-TITLE-LENGTH", 70), ("ADOBE-CSV-FILENAME-LENGTH", 30),
    ("ADOBE-CSV-KEYWORDS-MAX", 50), ("ADOBE-GUIDANCE-KEYWORDS-49", 49),
    ("ADOBE-CSV-ROW-LIMIT", 5000), ("ADOBE-CSV-FILE-SIZE", 1048576),
    ("ADOBE-CSV-FILE-SIZE-DECIMAL", 1000000), ("ADOBE-CSV-RELEASE-NAME-LENGTH", 30),
])
def test_source_backed_limits(rule_id: str, limit: int) -> None:
    assert load_registry().int_limit(rule_id) == limit


def test_scoped_keyword_limits_are_separate_rules() -> None:
    registry = load_registry()
    csv_rule = registry.get("ADOBE-CSV-KEYWORDS-MAX")
    guidance = registry.get("ADOBE-GUIDANCE-KEYWORDS-49")
    assert csv_rule.scope == "adobe-csv" and csv_rule.severity.value == "error"
    assert guidance.scope == "adobe-guidance" and guidance.severity.value == "warning"
    assert guidance.profiles == ("editorial",)
    assert csv_rule.source_url != guidance.source_url


def test_lookup_errors_and_helpers() -> None:
    registry = load_registry()
    with pytest.raises(ConfigError, match="Did you mean"):
        registry.get("ADOBE-CSV-TITLE-LENGHT")
    with pytest.raises(RegistryError):
        registry.int_limit("ADOBE-CSV-CATEGORY-UNKNOWN")  # range limit, not int
    with pytest.raises(RegistryError):
        registry.range_limit("ADOBE-CSV-TITLE-LENGTH")
    assert registry.range_limit("ADOBE-CSV-CATEGORY-UNKNOWN") == (1.0, 21.0)
    with pytest.raises(ConfigError, match="unknown platform"):
        load_registry("shutterstock")
    assert sum(registry.verification_counts().values()) == len(registry.rules)


def _mutate(monkeypatch: pytest.MonkeyPatch, mutate: Any) -> None:
    original = reg._load_json

    def fake(name: str) -> dict[str, Any]:
        data = original(name)
        if name == "adobe_csv_2026_06.json":
            mutate(data)
        return data

    monkeypatch.setattr(reg, "_load_json", fake)
    reg.load_registry.cache_clear()


@pytest.mark.parametrize("mutation", [
    lambda d: d["rules"][0].update(severity="fatal"),
    lambda d: d["rules"][0].update(scope="nowhere"),
    lambda d: d["rules"][0].update(verification="trust-me"),
    lambda d: d["rules"][0].update(verified_at="2026-11-09"),          # without status 'verified'
    lambda d: d["rules"][0].update(source_url="https://example.com/"),  # mismatching source
    lambda d: d["rules"][0].update(source_updated="1999-01-01"),
    lambda d: d["rules"][0].update(limit=True),
    lambda d: d["rules"][0].update(profiles=["strict"]),
    lambda d: d["rules"][0].update(rule_id="lowercase-id"),
    lambda d: d["rules"][0].pop("notes"),
    lambda d: d["rules"].append(dict(d["rules"][0])),                  # duplicate ID
    lambda d: d["sources"]["adobe-csv-requirements"].update(verification="??"),
    lambda d: d.update(required_columns=["Nope"]),
    lambda d: d.update(platform="other"),
    lambda d: d.update(registry_format=2),
    lambda d: d["categories"]["values"].update({"x": "Bad"}),
    lambda d: d.update(profiles={"standard": "only one"}),
])
def test_malformed_registry_is_rejected(monkeypatch: pytest.MonkeyPatch, mutation: Any) -> None:
    _mutate(monkeypatch, mutation)
    try:
        with pytest.raises(RegistryError):
            reg.load_registry("adobe-csv")
    finally:
        reg.load_registry.cache_clear()


def test_unloadable_registry_file(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(RegistryError, match="cannot load"):
        reg._load_json("does-not-exist.json")


def test_raw_json_has_brief_mandated_fields() -> None:
    for name in ("adobe_csv_2026_06.json", "core.json"):
        for rule in _raw(name)["rules"]:
            for key in ("rule_id", "source_url", "source_updated", "verified_at", "scope",
                        "severity", "description", "limit", "notes"):
                assert key in rule
