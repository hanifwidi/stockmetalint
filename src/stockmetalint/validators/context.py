"""Shared state for one lint run."""

from __future__ import annotations

from dataclasses import dataclass, field

from stockmetalint.csv_input import CsvRecord
from stockmetalint.domain import Diagnostic
from stockmetalint.rules.registry import RuleRegistry

#: canonical template column name -> 0-based index in the CSV header
ColumnMap = dict[str, int]


@dataclass
class LintContext:
    registry: RuleRegistry
    profile: str = "standard"
    diagnostics: list[Diagnostic] = field(default_factory=list)

    def emit(
        self,
        rule_id: str,
        message: str,
        *,
        line: int | None = None,
        row: int | None = None,
        column: str | None = None,
        filename: str | None = None,
        suggestion: str | None = None,
    ) -> None:
        """Record a diagnostic unless the rule is disabled for the active profile."""
        if not self.registry.get(rule_id).enabled_for(self.profile):
            return
        self.diagnostics.append(
            self.registry.make(
                rule_id,
                message,
                line=line,
                row=row,
                column=column,
                filename=filename,
                suggestion=suggestion,
            )
        )


@dataclass(frozen=True, slots=True)
class RowView:
    """A data record viewed through the header mapping.

    A field is ``None`` when its column is not in the header. ``aligned`` is
    False when the record has more fields than the header, in which case
    content checks are skipped for the row.
    """

    record: CsvRecord
    aligned: bool
    filename: str | None
    title: str | None
    keywords: str | None
    category: str | None
    releases: str | None

    @property
    def row(self) -> int:
        return self.record.row

    @property
    def line(self) -> int:
        return self.record.line

    def cells(self) -> list[tuple[str, str]]:
        """(column, value) pairs for mapped columns, in template order."""
        pairs = (
            ("Filename", self.filename),
            ("Title", self.title),
            ("Keywords", self.keywords),
            ("Category", self.category),
            ("Releases", self.releases),
        )
        return [(name, value) for name, value in pairs if value is not None]
