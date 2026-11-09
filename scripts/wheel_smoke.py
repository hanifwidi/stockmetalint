"""Install a built wheel into a fresh virtual environment and smoke-test the CLI.

Usage: python scripts/wheel_smoke.py dist/stockmetalint-0.1.0-py3-none-any.whl

The wheel has no runtime dependencies, so it is installed with --no-index:
this also proves the CLI works fully offline. Exits non-zero on any mismatch.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def main(wheel: str) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        env_dir = Path(tmp) / "venv"
        venv.EnvBuilder(with_pip=True).create(env_dir)
        bindir = env_dir / ("Scripts" if sys.platform == "win32" else "bin")
        python = bindir / ("python.exe" if sys.platform == "win32" else "python")
        subprocess.run(
            [python, "-m", "pip", "install", "--no-index", "--no-deps", "-q", wheel], check=True
        )
        cli = bindir / ("stockmetalint.exe" if sys.platform == "win32" else "stockmetalint")
        out_dir = Path(tmp) / "out"
        checks: list[tuple[list[str], int]] = [
            (["--version"], 0),
            (["doctor"], 0),
            (["rules", "list", "--platform", "adobe-csv"], 0),
            (["rules", "show", "ADOBE-CSV-TITLE-LENGTH"], 0),
            (["lint", str(EXAMPLES / "adobe-valid.csv"), "--platform", "adobe-csv"], 0),
            (["lint", str(EXAMPLES / "adobe-valid.csv"), "--assets", str(EXAMPLES / "assets")], 0),
            (
                ["lint", str(EXAMPLES / "adobe-invalid.csv"), "--assets", str(EXAMPLES / "assets")],
                1,
            ),
            (
                [
                    "lint",
                    str(EXAMPLES / "adobe-invalid.csv"),
                    "--format",
                    "json",
                    "--output",
                    str(out_dir / "validation.json"),
                ],
                1,
            ),
            (["lint", str(EXAMPLES / "adobe-invalid.csv"), "--fail-on-warning"], 1),
            (
                ["lint", str(EXAMPLES / "adobe-valid.csv"), "--assets", str(Path(tmp) / "missing")],
                2,
            ),
            (["fix", str(EXAMPLES / "adobe-invalid.csv"), "--dry-run"], 1),
            (
                [
                    "fix",
                    str(EXAMPLES / "adobe-valid.csv"),
                    "--output",
                    str(out_dir / "proposed.csv"),
                ],
                0,
            ),
        ]
        failures = 0
        for args, expected in checks:
            proc = subprocess.run(
                [cli, *args], capture_output=True, text=True, encoding="utf-8", check=False
            )
            status = "ok" if proc.returncode == expected else "FAIL"
            failures += status == "FAIL"
            print(
                f"[{status}] stockmetalint {' '.join(args[:2])} ... -> exit {proc.returncode} "
                f"(expected {expected})"
            )
            if status == "FAIL":
                print(proc.stdout[-2000:], proc.stderr[-2000:], sep="\n")
        report = json.loads((out_dir / "validation.json").read_text(encoding="utf-8"))
        if report["summary"]["exit_code"] != 1 or not report["diagnostics"]:
            print("[FAIL] JSON report content unexpected")
            failures += 1
        if (out_dir / "proposed.csv").read_bytes() != (EXAMPLES / "adobe-valid.csv").read_bytes():
            print("[FAIL] fix changed a clean file")
            failures += 1
        print(f"{len(checks) + 2 - failures}/{len(checks) + 2} smoke checks passed")
        return 1 if failures else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    raise SystemExit(main(sys.argv[1]))
