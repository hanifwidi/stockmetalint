"""Allow ``python -m stockmetalint``."""

from __future__ import annotations

from stockmetalint.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
