"""Report renderers (pure functions from data to text)."""

from __future__ import annotations

from stockmetalint.reporters.json_report import render_json
from stockmetalint.reporters.text_report import render_text

__all__ = ["render_json", "render_text"]
