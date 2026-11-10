"""Versioned, machine-readable rule registry (JSON files plus a typed loader)."""

from __future__ import annotations

from stockmetalint.rules.registry import (
    PLATFORMS,
    PROFILES,
    Rule,
    RuleRegistry,
    Source,
    load_registry,
)

__all__ = ["PLATFORMS", "PROFILES", "Rule", "RuleRegistry", "Source", "load_registry"]
