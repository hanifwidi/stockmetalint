"""StockMetaLint: offline-first stock media metadata preflight linter.

Unofficial and not affiliated with, endorsed by, or sponsored by Adobe.
A clean StockMetaLint report is not a guarantee of upload acceptance,
approval, or ranking on any platform.
"""

from __future__ import annotations

__version__ = "0.1.0"

from stockmetalint.domain import Diagnostic, Report, Severity
from stockmetalint.engine import LintOptions, lint_bytes, lint_path

__all__ = [
    "Diagnostic",
    "LintOptions",
    "Report",
    "Severity",
    "__version__",
    "lint_bytes",
    "lint_path",
]
