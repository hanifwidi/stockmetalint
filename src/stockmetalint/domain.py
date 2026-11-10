"""Typed domain model shared by the parser, validators, reporters and CLI."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

#: Version of the JSON report layout (see ``schemas/report-v1.schema.json``).
REPORT_SCHEMA_VERSION = "1.0"


class Severity(enum.StrEnum):
    """Diagnostic severity. Only ``error`` is blocking by default."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Higher is more severe."""
        return {Severity.ERROR: 3, Severity.WARNING: 2, Severity.INFO: 1}[self]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One finding.

    ``line`` is the 1-based *physical* line where the CSV record starts.
    ``row`` is the 1-based *data row* index (header and blank lines excluded).
    File-level findings have ``row`` set to ``None``.
    """

    code: str
    severity: Severity
    scope: str
    message: str
    source_url: str | None = None
    line: int | None = None
    row: int | None = None
    column: str | None = None
    filename: str | None = None
    suggestion: str | None = None

    def sort_key(self) -> tuple[int, int, int, str, str, str, str]:
        """File-level findings first, then by row, then by rule ID."""
        if self.row is None:
            return (
                0,
                self.line or 0,
                0,
                self.code,
                self.column or "",
                self.filename or "",
                self.message,
            )
        return (
            1,
            self.row,
            self.line or 0,
            self.code,
            self.column or "",
            self.filename or "",
            self.message,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "code": self.code,
            "scope": self.scope,
            "source_url": self.source_url,
            "line": self.line,
            "row": self.row,
            "column": self.column,
            "filename": self.filename,
            "message": self.message,
            "suggestion": self.suggestion,
        }


@dataclass(frozen=True, slots=True)
class Summary:
    errors: int
    warnings: int
    info: int
    data_rows: int | None
    fatal: bool
    assets_checked: bool
    media_inspected: bool

    @property
    def total(self) -> int:
        return self.errors + self.warnings + self.info

    def to_dict(self) -> dict[str, Any]:
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "total": self.total,
            "data_rows": self.data_rows,
            "fatal": self.fatal,
            "assets_checked": self.assets_checked,
            "media_inspected": self.media_inspected,
        }


@dataclass(frozen=True, slots=True)
class Report:
    """Result of one lint run. Pure data; rendering lives in ``reporters``."""

    tool_version: str
    platform: str
    profile: str
    rule_profile_version: str
    rule_verification: str
    source_file: str
    checked_at: str | None
    data_rows: int | None
    fatal: bool
    assets_checked: bool
    media_inspected: bool
    diagnostics: tuple[Diagnostic, ...] = field(default_factory=tuple)

    def count(self, severity: Severity) -> int:
        return sum(1 for d in self.diagnostics if d.severity is severity)

    @property
    def summary(self) -> Summary:
        return Summary(
            errors=self.count(Severity.ERROR),
            warnings=self.count(Severity.WARNING),
            info=self.count(Severity.INFO),
            data_rows=self.data_rows,
            fatal=self.fatal,
            assets_checked=self.assets_checked,
            media_inspected=self.media_inspected,
        )

    def exit_code(self, *, fail_on_warning: bool = False) -> int:
        """0 = no blocking findings, 1 = validation failure.

        A fatal report (content unreadable or not fully parsed) always fails, even
        when the underlying rule was suppressed with ``--ignore``.
        """
        if self.fatal or self.count(Severity.ERROR):
            return 1
        if fail_on_warning and self.count(Severity.WARNING):
            return 1
        return 0

    def codes(self) -> list[str]:
        return [d.code for d in self.diagnostics]

    def to_dict(self, *, fail_on_warning: bool = False) -> dict[str, Any]:
        summary = self.summary.to_dict()
        summary["exit_code"] = self.exit_code(fail_on_warning=fail_on_warning)
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "tool": "stockmetalint",
            "tool_version": self.tool_version,
            "platform": self.platform,
            "profile": self.profile,
            "rule_profile_version": self.rule_profile_version,
            "rule_verification": self.rule_verification,
            "source_file": self.source_file,
            "checked_at": self.checked_at,
            "disclaimer": (
                "Unofficial preflight check; not affiliated with Adobe. A clean report "
                "does not guarantee upload acceptance, approval or ranking."
            ),
            "summary": summary,
            "diagnostics": [d.to_dict() for d in self.diagnostics],
        }
