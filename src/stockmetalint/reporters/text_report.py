"""Human-readable terminal report.

All text that may contain CSV content is passed through
:func:`~stockmetalint.textutil.escape_for_terminal` so control characters and
escape sequences from a CSV can never reach the terminal raw.
"""

from __future__ import annotations

import os
from typing import TextIO

from stockmetalint.domain import Diagnostic, Report, Severity
from stockmetalint.textutil import escape_for_terminal

_COLORS = {Severity.ERROR: "31", Severity.WARNING: "33", Severity.INFO: "36"}
DISCLAIMER = (
    "Unofficial preflight check, not affiliated with Adobe. A clean result does not "
    "guarantee upload acceptance, approval or ranking."
)


def should_use_color(stream: TextIO, mode: str) -> bool:
    """``always``/``never`` win; ``auto`` needs a TTY, no NO_COLOR, and TERM != dumb."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _paint(text: str, code: str, color: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if color else text


def location(d: Diagnostic) -> str:
    parts: list[str] = []
    if d.line is not None:
        parts.append(f"line {d.line}")
    if d.row is not None:
        parts.append(f"row {d.row}")
    if d.column:
        parts.append(d.column)
    if not parts and d.filename:
        parts.append(d.filename)
    return " · ".join(parts) if parts else "file"


def render_text(
    report: Report, *, color: bool = False, verbose: bool = False, fail_on_warning: bool = False
) -> str:
    esc = escape_for_terminal
    lines: list[str] = []
    rows = "unknown" if report.data_rows is None else str(report.data_rows)
    lines.append(
        f"{esc(report.source_file)}: {rows} data row(s) · platform {report.platform} · profile "
        f"{report.profile} · rules {report.rule_profile_version} ({report.rule_verification})"
    )
    if report.diagnostics:
        lines.append("")
    width = max((len(d.severity.value) for d in report.diagnostics), default=7)
    for d in report.diagnostics:
        sev = _paint(d.severity.value.ljust(width), _COLORS[d.severity], color)
        lines.append(f"  {esc(location(d))}")
        lines.append(f"    {sev}  {_paint(d.code, '1', color)}  {esc(d.message)}")
        if d.suggestion:
            lines.append(f"    {' ' * width}  -> {esc(d.suggestion)}")
        if verbose and d.source_url:
            lines.append(f"    {' ' * width}  source: {d.source_url}")
    summary = report.summary
    exit_code = report.exit_code(fail_on_warning=fail_on_warning)
    verdict = _paint("FAIL", "31;1", color) if exit_code else _paint("PASS", "32;1", color)
    lines.append("")
    extra = []
    if report.fatal:
        extra.append("row checks incomplete (see errors above)")
    if report.assets_checked:
        extra.append("assets matched")
    if report.media_inspected:
        extra.append("media inspected")
    tail = f" [{'; '.join(extra)}]" if extra else ""
    lines.append(
        f"Result: {summary.errors} error(s), {summary.warnings} warning(s), {summary.info} info "
        f"-> {verdict} (exit {exit_code}){tail}"
    )
    if not verbose and report.diagnostics:
        lines.append("Details for any rule: stockmetalint rules show <RULE-ID>")
    lines.append(DISCLAIMER)
    return "\n".join(lines) + "\n"
