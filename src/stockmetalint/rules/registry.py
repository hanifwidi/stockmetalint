"""Load and strictly validate the bundled JSON rule registry.

The JSON files are the single source of truth for rule IDs, severities,
limits, scopes and source citations. Code looks limits up here instead of
hard-coding them, so a rule-profile update is a data change with tests.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

from stockmetalint.domain import Diagnostic, Severity
from stockmetalint.errors import ConfigError, RegistryError

#: platform name -> platform registry file. Core rules are always merged in.
PLATFORMS: dict[str, str] = {"adobe-csv": "adobe_csv_2026_06.json"}
CORE_FILE = "core.json"
PROFILES: tuple[str, ...] = ("standard", "editorial")

VERIFICATION_STATUSES = frozenset(
    {
        "verified",
        "snippet-corroborated",
        "summary-corroborated",
        "partially-corroborated",
        "seed-unverified",
        "standard-reference",
        "tool-defined",
    }
)
SCOPES = frozenset(
    {
        "csv-structure",
        "adobe-csv",
        "adobe-guidance",
        "adobe-media",
        "hygiene",
        "heuristic",
        "integrity",
        "security",
        "assets",
        "media-format",
    }
)
RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
_RULE_KEYS = (
    "rule_id", "title", "severity", "scope", "source_id", "source_url", "source_updated",
    "verified_at", "verification", "description", "limit", "notes", "profiles", "fix_rule",
)
_SOURCE_KEYS = (
    "title", "url", "page_updated", "page_updated_basis", "verification", "evidence_accessed",
    "evidence",
)


@dataclass(frozen=True, slots=True)
class Source:
    source_id: str
    title: str
    url: str
    page_updated: str | None
    page_updated_basis: str
    verification: str
    evidence_accessed: str | None
    evidence: str


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    title: str
    severity: Severity
    scope: str
    source_id: str
    source_url: str
    source_updated: str | None
    verified_at: str | None
    verification: str
    description: str
    limit: int | str | None
    notes: str
    profiles: tuple[str, ...]
    fix_rule: str | None
    registry_file: str

    def enabled_for(self, profile: str) -> bool:
        return profile in self.profiles

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "title": self.title,
            "severity": self.severity.value,
            "scope": self.scope,
            "source_id": self.source_id,
            "source_url": self.source_url,
            "source_updated": self.source_updated,
            "verified_at": self.verified_at,
            "verification": self.verification,
            "description": self.description,
            "limit": self.limit,
            "notes": self.notes,
            "profiles": list(self.profiles),
            "fix_rule": self.fix_rule,
            "registry_file": self.registry_file,
        }


@dataclass(frozen=True, slots=True)
class RuleRegistry:
    platform: str
    profile_id: str
    title: str
    verification_summary: str
    template_header: tuple[str, ...]
    template_header_verification: str
    required_columns: frozenset[str]
    categories: Mapping[int, str]
    categories_verification: str
    profiles: Mapping[str, str]
    sources: Mapping[str, Source]
    rules: Mapping[str, Rule]

    def get(self, rule_id: str) -> Rule:
        try:
            return self.rules[rule_id]
        except KeyError:
            close = difflib.get_close_matches(rule_id.upper(), list(self.rules), n=3)
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise ConfigError(f"unknown rule ID {rule_id!r}.{hint}") from None

    def int_limit(self, rule_id: str) -> int:
        limit = self.get(rule_id).limit
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise RegistryError(f"rule {rule_id} has no integer limit")
        return limit

    def range_limit(self, rule_id: str) -> tuple[float, float]:
        limit = self.get(rule_id).limit
        if not isinstance(limit, str) or "-" not in limit:
            raise RegistryError(f"rule {rule_id} has no 'low-high' range limit")
        low, high = limit.split("-", 1)
        return float(low), float(high)

    def make(
        self,
        rule_id: str,
        message: str,
        *,
        line: int | None = None,
        row: int | None = None,
        column: str | None = None,
        filename: str | None = None,
        suggestion: str | None = None,
    ) -> Diagnostic:
        rule = self.get(rule_id)
        return Diagnostic(
            code=rule.rule_id,
            severity=rule.severity,
            scope=rule.scope,
            message=message,
            source_url=rule.source_url,
            line=line,
            row=row,
            column=column,
            filename=filename,
            suggestion=suggestion,
        )

    def verification_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for rule in self.rules.values():
            counts[rule.verification] = counts.get(rule.verification, 0) + 1
        return dict(sorted(counts.items()))

    @property
    def verification_label(self) -> str:
        """Short label for reports: 'verified' only if every platform rule is verified."""
        platform_rules = [r for r in self.rules.values() if r.registry_file != CORE_FILE]
        if platform_rules and all(r.verification == "verified" for r in platform_rules):
            return "verified"
        return "unverified"


def _require(mapping: Mapping[str, Any], key: str, where: str, kind: type | tuple[type, ...]) -> Any:
    if key not in mapping:
        raise RegistryError(f"{where}: missing key {key!r}")
    value = mapping[key]
    if not isinstance(value, kind):
        raise RegistryError(f"{where}: key {key!r} has wrong type {type(value).__name__}")
    return value


def _opt_str(mapping: Mapping[str, Any], key: str, where: str) -> str | None:
    value = _require(mapping, key, where, (str, type(None)))
    return value if value is None else str(value)


def _load_json(filename: str) -> dict[str, Any]:
    try:
        text = resources.files("stockmetalint.rules").joinpath(filename).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, ValueError) as exc:
        raise RegistryError(f"cannot load rule registry {filename}: {exc}") from exc
    if not isinstance(data, dict) or data.get("registry_format") != 1:
        raise RegistryError(f"{filename}: unsupported registry_format")
    return data


def _parse_sources(data: Mapping[str, Any], filename: str) -> dict[str, Source]:
    raw = _require(data, "sources", filename, dict)
    sources: dict[str, Source] = {}
    for source_id, entry in raw.items():
        where = f"{filename}: source {source_id}"
        if not isinstance(entry, dict) or set(entry) != set(_SOURCE_KEYS):
            raise RegistryError(f"{where}: keys must be exactly {sorted(_SOURCE_KEYS)}")
        verification = _require(entry, "verification", where, str)
        if verification not in VERIFICATION_STATUSES:
            raise RegistryError(f"{where}: unknown verification {verification!r}")
        sources[source_id] = Source(
            source_id=source_id,
            title=_require(entry, "title", where, str),
            url=_require(entry, "url", where, str),
            page_updated=_opt_str(entry, "page_updated", where),
            page_updated_basis=_require(entry, "page_updated_basis", where, str),
            verification=verification,
            evidence_accessed=_opt_str(entry, "evidence_accessed", where),
            evidence=_require(entry, "evidence", where, str),
        )
    return sources


def _parse_rule(entry: Any, filename: str, sources: Mapping[str, Source]) -> Rule:
    if not isinstance(entry, dict) or set(entry) != set(_RULE_KEYS):
        raise RegistryError(f"{filename}: every rule needs exactly the keys {sorted(_RULE_KEYS)}")
    rule_id = _require(entry, "rule_id", filename, str)
    where = f"{filename}: {rule_id}"
    if not RULE_ID_RE.match(rule_id):
        raise RegistryError(f"{where}: invalid rule ID format")
    try:
        severity = Severity(_require(entry, "severity", where, str))
    except ValueError as exc:
        raise RegistryError(f"{where}: invalid severity") from exc
    scope = _require(entry, "scope", where, str)
    if scope not in SCOPES:
        raise RegistryError(f"{where}: unknown scope {scope!r}")
    verification = _require(entry, "verification", where, str)
    if verification not in VERIFICATION_STATUSES:
        raise RegistryError(f"{where}: unknown verification {verification!r}")
    verified_at = _opt_str(entry, "verified_at", where)
    if (verified_at is None) == (verification == "verified"):
        raise RegistryError(f"{where}: verified_at must be set if and only if verification is 'verified'")
    source_id = _require(entry, "source_id", where, str)
    if source_id not in sources:
        raise RegistryError(f"{where}: unknown source_id {source_id!r}")
    source = sources[source_id]
    source_url = _require(entry, "source_url", where, str)
    if source_url != source.url and not source_url.startswith(source.url + "#"):
        raise RegistryError(f"{where}: source_url does not match source {source_id}")
    source_updated = _opt_str(entry, "source_updated", where)
    if source_updated != source.page_updated:
        raise RegistryError(f"{where}: source_updated does not match source {source_id}")
    limit = _require(entry, "limit", where, (int, str, type(None)))
    if isinstance(limit, bool):
        raise RegistryError(f"{where}: limit must not be boolean")
    profiles = _require(entry, "profiles", where, list)
    if not profiles or any(p not in PROFILES for p in profiles):
        raise RegistryError(f"{where}: profiles must be a non-empty subset of {PROFILES}")
    return Rule(
        rule_id=rule_id,
        title=_require(entry, "title", where, str),
        severity=severity,
        scope=scope,
        source_id=source_id,
        source_url=source_url,
        source_updated=source_updated,
        verified_at=verified_at,
        verification=verification,
        description=_require(entry, "description", where, str),
        limit=limit,
        notes=_require(entry, "notes", where, str),
        profiles=tuple(profiles),
        fix_rule=_opt_str(entry, "fix_rule", where),
        registry_file=filename,
    )


@cache
def load_registry(platform: str = "adobe-csv") -> RuleRegistry:
    """Load the platform registry merged with the core registry (cached)."""
    if platform not in PLATFORMS:
        raise ConfigError(f"unknown platform {platform!r}; supported: {', '.join(PLATFORMS)}")
    platform_file = PLATFORMS[platform]
    platform_data = _load_json(platform_file)
    core_data = _load_json(CORE_FILE)
    if platform_data.get("platform") != platform:
        raise RegistryError(f"{platform_file}: platform field does not match {platform!r}")

    rules: dict[str, Rule] = {}
    all_sources: dict[str, Source] = {}
    for filename, data in ((CORE_FILE, core_data), (platform_file, platform_data)):
        sources = _parse_sources(data, filename)
        overlap = set(sources) & set(all_sources)
        if overlap:
            raise RegistryError(f"{filename}: duplicate source IDs {sorted(overlap)}")
        all_sources.update(sources)
        for entry in _require(data, "rules", filename, list):
            rule = _parse_rule(entry, filename, sources)
            if rule.rule_id in rules:
                raise RegistryError(f"duplicate rule ID {rule.rule_id}")
            rules[rule.rule_id] = rule

    header = _require(platform_data, "template_header", platform_file, list)
    required = _require(platform_data, "required_columns", platform_file, list)
    if not set(required) <= set(header) or len(set(header)) != len(header):
        raise RegistryError(f"{platform_file}: required_columns must be a subset of template_header")
    categories_block = _require(platform_data, "categories", platform_file, dict)
    raw_categories = _require(categories_block, "values", platform_file, dict)
    try:
        categories = {int(k): str(v) for k, v in raw_categories.items()}
    except ValueError as exc:
        raise RegistryError(f"{platform_file}: category keys must be integers") from exc
    profiles = _require(platform_data, "profiles", platform_file, dict)
    if tuple(profiles) != PROFILES:
        raise RegistryError(f"{platform_file}: profiles must be exactly {PROFILES}")

    return RuleRegistry(
        platform=platform,
        profile_id=_require(platform_data, "profile_id", platform_file, str),
        title=_require(platform_data, "title", platform_file, str),
        verification_summary=_require(platform_data, "verification_summary", platform_file, str),
        template_header=tuple(str(h) for h in header),
        template_header_verification=_require(
            platform_data, "template_header_verification", platform_file, str
        ),
        required_columns=frozenset(str(c) for c in required),
        categories=categories,
        categories_verification=_require(categories_block, "verification", platform_file, str),
        profiles={str(k): str(v) for k, v in profiles.items()},
        sources=all_sources,
        rules=rules,
    )
