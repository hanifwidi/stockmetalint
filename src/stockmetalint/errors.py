"""Exception hierarchy.

Every exception here maps to CLI exit status 2 (configuration, runtime or
input failure). Validation findings are never exceptions: they are
:class:`~stockmetalint.domain.Diagnostic` objects and map to exit status 1.
"""

from __future__ import annotations


class StockMetaLintError(Exception):
    """Base class for failures that prevent a check from running."""

    exit_code = 2


class InputError(StockMetaLintError):
    """An input file or directory is missing, unreadable, or unsafe to process."""


class ConfigError(StockMetaLintError):
    """Invalid options: unknown platform, profile, rule ID, or fix rule."""


class RegistryError(ConfigError):
    """The bundled rule registry is malformed (a packaging bug)."""


class OutputError(StockMetaLintError):
    """An output path is unsafe (for example it aliases the source) or unwritable."""
