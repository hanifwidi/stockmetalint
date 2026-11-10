"""Machine-readable JSON report (layout: ``schemas/report-v1.schema.json``)."""

from __future__ import annotations

import json
from typing import Any

from stockmetalint.domain import Report


def dumps(data: Any) -> str:
    """Stable JSON: UTF-8 text (not ASCII-escaped), 2-space indent, trailing newline."""
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def render_json(report: Report, *, fail_on_warning: bool = False) -> str:
    return dumps(report.to_dict(fail_on_warning=fail_on_warning))
