"""Safe, allow-listed, mechanical fixes.

Guarantees:

* Only rules named in the allow-list run; the default list is whitespace-only.
* Filename cells are never modified; titles are never truncated or reworded;
  keywords are never generated, reordered or translated; Category is only trimmed.
* Rows whose field count does not match the header are copied unchanged.
* The output CSV is never written over the source (see ``safe_io``).
* Cells that a spreadsheet could execute as a formula are refused by default.
"""

from __future__ import annotations

import csv
import io
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from stockmetalint.csv_input import ParsedCsv
from stockmetalint.errors import ConfigError
from stockmetalint.textutil import formula_prefix, keyword_key
from stockmetalint.validators.adobe import canonical_header_names
from stockmetalint.validators.context import ColumnMap

FIX_RULES: dict[str, str] = {
    "trim-whitespace": "Strip leading/trailing whitespace from Title, each keyword, Category and "
                       "Releases. Filename is never modified.",
    "drop-empty-keywords": "Remove empty keyword items such as 'sky,,sun' or a trailing comma.",
    "dedupe-keywords": "Remove repeated keywords (case/whitespace-insensitive), keeping the first "
                       "occurrence and the original order.",
    "nfc": "Normalize Title and Keywords to Unicode NFC (canonically equivalent text).",
    "canonical-header": "Rename header cells that differ from the template only by case, spacing, "
                        "plural or small typo to the exact template spelling.",
}
DEFAULT_FIX_RULES: tuple[str, ...] = ("trim-whitespace", "drop-empty-keywords")
FORMULA_POLICIES = ("refuse", "escape")


def parse_fix_rules(spec: str | None) -> tuple[str, ...]:
    if spec is None:
        return DEFAULT_FIX_RULES
    names = tuple(dict.fromkeys(part.strip() for part in spec.split(",") if part.strip()))
    if not names:
        raise ConfigError("--fix-rules needs at least one rule name")
    unknown = [n for n in names if n not in FIX_RULES]
    if unknown:
        raise ConfigError(f"unknown fix rule(s): {', '.join(unknown)}; available: {', '.join(FIX_RULES)}")
    return tuple(n for n in FIX_RULES if n in names)  # canonical order


@dataclass(frozen=True, slots=True)
class Change:
    line: int
    row: int | None
    column: str
    rule: str
    before: str
    after: str

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "row": self.row, "column": self.column, "rule": self.rule,
                "before": self.before, "after": self.after}


@dataclass(frozen=True, slots=True)
class FormulaCell:
    line: int
    row: int | None
    column: str
    prefix: str

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "row": self.row, "column": self.column, "prefix": self.prefix}


@dataclass(slots=True)
class FixPlan:
    rules: tuple[str, ...]
    header: list[str]
    header_line: int
    records: list[list[str]]
    positions: list[tuple[int, int]]  # (line, row) per record
    newline: str
    had_bom: bool
    changes: list[Change] = field(default_factory=list)
    skipped_rows: list[int] = field(default_factory=list)
    formula_cells: list[FormulaCell] = field(default_factory=list)

    def render(self) -> bytes:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, lineterminator=self.newline, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(self.header)
        writer.writerows(self.records)
        return (b"\xef\xbb\xbf" if self.had_bom else b"") + buffer.getvalue().encode("utf-8")

    def _cells(self) -> list[tuple[int, int | None, list[str]]]:
        rows: list[tuple[int, int | None, list[str]]] = [(self.header_line, None, self.header)]
        rows += [(line, row, cells) for (line, row), cells in zip(self.positions, self.records,
                                                                  strict=True)]
        return rows

    def scan_formulas(self) -> None:
        self.formula_cells = []
        for line, row, cells in self._cells():
            for index, value in enumerate(cells):
                prefix = formula_prefix(value)
                if prefix is not None:
                    self.formula_cells.append(FormulaCell(line, row, self.column_name(index), prefix))

    def column_name(self, index: int) -> str:
        return self.header[index] if index < len(self.header) else f"field {index + 1}"

    def escape_formulas(self) -> None:
        """Prefix formula-like cells with an apostrophe. Alters values; opt-in only."""
        for line, row, cells in self._cells():
            for index, value in enumerate(cells):
                if formula_prefix(value) is not None:
                    cells[index] = "'" + value
                    self.changes.append(Change(line, row, self.column_name(index), "formula-escape",
                                               value, cells[index]))


def _join_trimmed(items: list[str], separator: str) -> str:
    """Join stripped keywords with *separator*; empty items stay empty (no stray spaces)."""
    if not items:
        return ""
    out = items[0]
    for item in items[1:]:
        out += "," + (separator[1:] if item else "") + item
    return out


def _keyword_steps(rules: tuple[str, ...]) -> list[tuple[str, Callable[[list[str]], list[str]]]]:
    def trim(items: list[str]) -> list[str]:
        return [i.strip() for i in items]

    def drop_empty(items: list[str]) -> list[str]:
        return [i for i in items if i.strip()]

    def dedupe(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in items:
            key = keyword_key(item)
            if key and key in seen:
                continue
            seen.add(key)
            out.append(item)
        return out

    def nfc(items: list[str]) -> list[str]:
        return [unicodedata.normalize("NFC", i) for i in items]

    table = {"trim-whitespace": trim, "drop-empty-keywords": drop_empty, "dedupe-keywords": dedupe,
             "nfc": nfc}
    return [(name, table[name]) for name in rules if name in table]


def plan_fixes(parsed: ParsedCsv, mapping: ColumnMap, rules: Iterable[str],
               template: tuple[str, ...]) -> FixPlan:
    rules = tuple(rules)
    if parsed.header is None:
        raise ConfigError("cannot plan fixes without a header row")
    header = list(parsed.header)
    plan = FixPlan(rules, header, parsed.header_line or 1, [], [], parsed.newline, parsed.had_bom)

    if "canonical-header" in rules:
        for index, canonical in enumerate(canonical_header_names(parsed.header, template)):
            if canonical and header[index] != canonical and mapping.get(canonical) == index:
                plan.changes.append(Change(plan.header_line, None, header[index], "canonical-header",
                                           header[index], canonical))
                header[index] = canonical

    steps = _keyword_steps(rules)
    for record in parsed.records:
        fields = list(record.fields)
        plan.records.append(fields)
        plan.positions.append((record.line, record.row))
        if len(fields) != len(header):
            plan.skipped_rows.append(record.row)
            continue
        changes = plan.changes
        for column in ("Title", "Category", "Releases"):
            index = mapping.get(column)
            if index is None:
                continue
            if "trim-whitespace" in rules and fields[index] != fields[index].strip():
                changes.append(Change(record.line, record.row, column, "trim-whitespace",
                                      fields[index], fields[index].strip()))
                fields[index] = fields[index].strip()
            if column == "Title" and "nfc" in rules:
                normalized = unicodedata.normalize("NFC", fields[index])
                if normalized != fields[index]:
                    changes.append(Change(record.line, record.row, column, "nfc", fields[index],
                                          normalized))
                    fields[index] = normalized

        index = mapping.get("Keywords")
        if index is None or not fields[index]:
            continue
        separator = ", " if ", " in fields[index] else ","
        items = fields[index].split(",")
        current = fields[index]
        trimmed = False
        for name, step in steps:
            items = step(items)
            trimmed = trimmed or name == "trim-whitespace"
            rendered = _join_trimmed(items, separator) if trimmed else ",".join(items)
            if rendered != current:
                changes.append(Change(record.line, record.row, "Keywords", name, current, rendered))
                current = rendered
        fields[index] = current

    plan.scan_formulas()
    return plan
