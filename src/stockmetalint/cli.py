"""Command-line interface (argparse; no runtime dependencies).

Exit status: 0 = no blocking findings, 1 = validation failure,
2 = usage, configuration, input/output or internal failure.
With ``--format json`` stdout carries only JSON; messages go to stderr.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import platform as platform_mod
import subprocess
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from stockmetalint._version import __version__
from stockmetalint.csv_input import DEFAULT_MAX_INPUT_BYTES, display_name
from stockmetalint.engine import (
    LintOptions,
    analyze_bytes,
    analyze_path,
    timestamp,
    validate_options,
)
from stockmetalint.errors import ConfigError, StockMetaLintError
from stockmetalint.fixes.safe import (
    FIX_RULES,
    FORMULA_POLICIES,
    FixPlan,
    parse_fix_rules,
    plan_fixes,
)
from stockmetalint.inspection import find_ffprobe, load_pillow
from stockmetalint.reporters.json_report import dumps, render_json
from stockmetalint.reporters.rules_report import (
    render_list_json,
    render_list_markdown,
    render_list_text,
    render_rule_json,
    render_rule_text,
)
from stockmetalint.reporters.text_report import DISCLAIMER, render_text, should_use_color
from stockmetalint.rules.registry import PLATFORMS, PROFILES, load_registry
from stockmetalint.safe_io import atomic_write_bytes, check_output_path, sha256_bytes
from stockmetalint.textutil import escape_for_terminal

EXAMPLES = """\
examples:
  stockmetalint lint batch.csv
  stockmetalint lint batch.csv --assets ./photos
  stockmetalint lint batch.csv --format json --output reports/validation.json
  stockmetalint fix batch.csv                       (dry run: shows proposed changes)
  stockmetalint fix batch.csv --output proposed.csv (writes a new file; source untouched)
  stockmetalint rules list
  stockmetalint rules show ADOBE-CSV-TITLE-LENGTH

exit status: 0 no blocking findings, 1 validation failure, 2 usage/runtime/input error.
Unofficial tool, not affiliated with Adobe. Works offline; never uploads anything.
"""


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {value!r}") from None
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stockmetalint",
        description="Catch stock metadata problems before your batch upload. Offline preflight "
        "linter for Adobe Stock contributor CSV files.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"stockmetalint {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    doctor = sub.add_parser(
        "doctor",
        help="show environment, optional tools and rule status",
        description="Report Python, platform, rule-profile verification status "
        "and optional inspection tools. Makes no network requests.",
    )
    doctor.add_argument("--format", choices=("text", "json"), default="text")

    rules = sub.add_parser(
        "rules",
        help="list or show validation rules",
        description="Inspect the versioned rule registry.",
    )
    rules_sub = rules.add_subparsers(dest="rules_command", metavar="ACTION", required=True)
    rules_list = rules_sub.add_parser("list", help="list all rules")
    rules_list.add_argument("--platform", choices=sorted(PLATFORMS), default="adobe-csv")
    rules_list.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    rules_show = rules_sub.add_parser("show", help="show one rule with its source and verification")
    rules_show.add_argument("rule_id", metavar="RULE_ID")
    rules_show.add_argument("--platform", choices=sorted(PLATFORMS), default="adobe-csv")
    rules_show.add_argument("--format", choices=("text", "json"), default="text")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("csv", type=Path, metavar="CSV", help="metadata CSV file to check")
        p.add_argument(
            "--platform",
            choices=sorted(PLATFORMS),
            default="adobe-csv",
            help="rule platform (default: adobe-csv)",
        )
        p.add_argument(
            "--profile",
            choices=PROFILES,
            default="standard",
            help="'editorial' adds non-blocking guidance advisories (default: standard)",
        )
        p.add_argument("--format", choices=("text", "json"), default="text", help="output format")
        p.add_argument(
            "--color",
            choices=("auto", "always", "never"),
            default="auto",
            help="colorize text output (auto respects NO_COLOR and TTY detection)",
        )
        p.add_argument(
            "--max-input-bytes",
            type=_positive_int,
            default=DEFAULT_MAX_INPUT_BYTES,
            metavar="N",
            help=f"safety cap for input size (default: {DEFAULT_MAX_INPUT_BYTES})",
        )
        p.add_argument(
            "--show-paths",
            action="store_true",
            help="show input paths as given instead of base names",
        )
        p.add_argument(
            "--reproducible",
            action="store_true",
            help="omit the wall-clock timestamp (uses SOURCE_DATE_EPOCH if set)",
        )

    lint = sub.add_parser(
        "lint",
        help="validate a metadata CSV (and optionally the asset folder)",
        description="Validate a metadata CSV against the rule profile.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common(lint)
    lint.add_argument(
        "--assets",
        type=Path,
        metavar="DIR",
        help="match Filename values against files in DIR (exact names)",
    )
    lint.add_argument(
        "--recursive",
        action="store_true",
        help="with --assets, include subdirectories (symlinked dirs are never followed)",
    )
    lint.add_argument(
        "--inspect",
        action="store_true",
        help="with --assets, check file signatures; decode images (Pillow) and probe "
        "videos (ffprobe) when available",
    )
    lint.add_argument(
        "--releases",
        type=Path,
        metavar="DIR",
        help="check that release names in the Releases column exist in DIR",
    )
    lint.add_argument(
        "--output",
        "-o",
        type=Path,
        metavar="PATH",
        help="write the report to PATH instead of stdout",
    )
    lint.add_argument("--fail-on-warning", action="store_true", help="exit 1 on warnings too")
    lint.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="RULE_ID",
        help="suppress a rule (repeatable or comma-separated)",
    )
    lint.add_argument("--verbose", "-v", action="store_true", help="show source URLs per finding")

    fix = sub.add_parser(
        "fix",
        help="propose safe mechanical fixes (dry run by default)",
        description="Propose allow-listed mechanical fixes. Without --output nothing "
        "is written. The source CSV is never modified.",
        epilog="fix rules:\n"
        + "\n".join(f"  {k:<20} {v}" for k, v in FIX_RULES.items())
        + "\n\ndefault fix rules: trim-whitespace,drop-empty-keywords",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common(fix)
    mode = fix.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="show proposed changes only (default)")
    mode.add_argument(
        "--output",
        "-o",
        type=Path,
        metavar="PATH",
        help="write the proposed CSV to PATH (must not be the source)",
    )
    fix.add_argument(
        "--fix-rules", metavar="LIST", help="comma-separated allow-list of fix rules (see below)"
    )
    fix.add_argument(
        "--audit-log",
        type=Path,
        metavar="PATH",
        help="where to write the JSON audit log (default: OUTPUT.audit.json)",
    )
    fix.add_argument(
        "--overwrite",
        action="store_true",
        help="allow replacing an existing output file (never the source)",
    )
    fix.add_argument(
        "--formula-policy",
        choices=FORMULA_POLICIES,
        default="refuse",
        help="cells starting with = + - @ tab/CR: refuse to write (default) or escape "
        "with a leading apostrophe",
    )
    return parser


# --------------------------------------------------------------------------- output helpers


def _write_stdout(text: str) -> None:
    """Write UTF-8 to stdout regardless of the console code page."""
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        sys.stdout.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    else:  # pragma: no cover - exotic stdout replacements
        sys.stdout.write(text)


def _note(message: str) -> None:
    print(escape_for_terminal(message), file=sys.stderr)


def _configure_streams() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            with contextlib.suppress(ValueError, OSError):  # detached or closed stream
                stream.reconfigure(errors="backslashreplace")


# --------------------------------------------------------------------------- commands


def _cmd_doctor(args: argparse.Namespace) -> int:
    registry = load_registry("adobe-csv")
    image = load_pillow()
    ffprobe = find_ffprobe()
    ffprobe_version = None
    if ffprobe:
        try:
            # Fixed argument list from shutil.which(); no shell, no user input.
            proc = subprocess.run(  # noqa: S603
                [ffprobe, "-version"], capture_output=True, timeout=10, check=False
            )
            ffprobe_version = (
                proc.stdout.decode("utf-8", "replace").splitlines()[0] if proc.stdout else None
            )
        except (OSError, subprocess.TimeoutExpired):
            ffprobe_version = None
    pillow_version = getattr(sys.modules.get("PIL"), "__version__", None) if image else None
    info: dict[str, Any] = {
        "tool_version": __version__,
        "python": platform_mod.python_version(),
        "implementation": platform_mod.python_implementation(),
        "platform": platform_mod.platform(),
        "rule_profiles": [
            {
                "platform": registry.platform,
                "rule_profile_version": registry.profile_id,
                "rules": len(registry.rules),
                "verification": registry.verification_label,
                "verification_counts": registry.verification_counts(),
                "verification_summary": registry.verification_summary,
            }
        ],
        "optional_tools": {
            "pillow": {
                "available": image is not None,
                "version": pillow_version,
                "used_for": "lint --inspect image decode and dimension checks",
            },
            "ffprobe": {
                "available": ffprobe is not None,
                "version": ffprobe_version,
                "used_for": "lint --inspect video container/codec/duration checks",
            },
        },
        "stdout_encoding": getattr(sys.stdout, "encoding", None),
        "color": should_use_color(sys.stdout, "auto"),
        "no_color_env": bool(os.environ.get("NO_COLOR")),
        "network": "StockMetaLint makes no network requests.",
    }
    if args.format == "json":
        _write_stdout(dumps(info))
        return 0
    yes_no = {True: "available", False: "not installed"}
    lines = [
        f"stockmetalint {__version__}",
        f"Python {info['python']} ({info['implementation']}) on {info['platform']}",
        "",
        (
            f"Rule profile {registry.profile_id} (platform {registry.platform}): "
            f"{len(registry.rules)} rules, status {registry.verification_label.upper()}"
        ),
        "  " + ", ".join(f"{k}: {v}" for k, v in registry.verification_counts().items()),
        f"  {registry.verification_summary}",
        "",
        "Optional inspection tools:",
        f"  Pillow : {yes_no[image is not None]}"
        + (f" ({pillow_version})" if pillow_version else " - image checks report INCONCLUSIVE"),
        f"  ffprobe: {yes_no[ffprobe is not None]}"
        + (
            f" ({ffprobe_version})"
            if ffprobe_version
            else ""
            if ffprobe
            else " - video checks report INCONCLUSIVE"
        ),
        "",
        (
            f"stdout encoding: {info['stdout_encoding']}; color: "
            f"{'on' if info['color'] else 'off'}"
            f"{' (NO_COLOR set)' if info['no_color_env'] else ''}"
        ),
        info["network"],
    ]
    _write_stdout("\n".join(lines) + "\n")
    return 0


def _cmd_rules(args: argparse.Namespace) -> int:
    registry = load_registry(args.platform)
    if args.rules_command == "list":
        renderers = {
            "text": render_list_text,
            "json": render_list_json,
            "markdown": render_list_markdown,
        }
        _write_stdout(renderers[args.format](registry))
        return 0
    rule = registry.get(args.rule_id.strip().upper())
    _write_stdout(render_rule_json(rule) if args.format == "json" else render_rule_text(rule))
    return 0


def _ignore_codes(values: Sequence[str]) -> frozenset[str]:
    codes = {part.strip().upper() for value in values for part in value.split(",") if part.strip()}
    return frozenset(codes)


def _lint_options(args: argparse.Namespace) -> LintOptions:
    return LintOptions(
        platform=args.platform,
        profile=args.profile,
        assets_dir=getattr(args, "assets", None),
        recursive=getattr(args, "recursive", False),
        inspect=getattr(args, "inspect", False),
        releases_dir=getattr(args, "releases", None),
        max_input_bytes=args.max_input_bytes,
        ignore=_ignore_codes(getattr(args, "ignore", [])),
        show_paths=args.show_paths,
        reproducible=args.reproducible,
    )


def _cmd_lint(args: argparse.Namespace) -> int:
    options = _lint_options(args)
    if args.output is not None:
        check_output_path(args.output, protected=[args.csv], overwrite=True)
    report = analyze_path(args.csv, options).report
    if args.format == "json":
        text = render_json(report, fail_on_warning=args.fail_on_warning)
    else:
        color = args.output is None and should_use_color(sys.stdout, args.color)
        text = render_text(
            report, color=color, verbose=args.verbose, fail_on_warning=args.fail_on_warning
        )
    if args.output is not None:
        atomic_write_bytes(args.output, text.encode("utf-8"))
        shown = display_name(args.output, show_paths=args.show_paths)
        _note(
            f"report written to {shown} ({report.summary.errors} error(s), "
            f"{report.summary.warnings} warning(s))"
        )
    else:
        _write_stdout(text)
    return report.exit_code(fail_on_warning=args.fail_on_warning)


def _fix_summary(
    plan: FixPlan | None,
    remaining: dict[str, Any] | None,
    *,
    written: bool,
    output: str | None,
    audit: str | None,
    policy: str,
    refused: bool,
    exit_code: int,
    rules: tuple[str, ...],
    source: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "tool": "stockmetalint",
        "tool_version": __version__,
        "mode": "write" if output else "dry-run",
        "source_file": source,
        "fix_rules": list(rules),
        "formula_policy": policy,
        "changes": [c.to_dict() for c in plan.changes] if plan else [],
        "skipped_rows": plan.skipped_rows if plan else [],
        "formula_cells": [c.to_dict() for c in plan.formula_cells] if plan else [],
        "refused": refused,
        "written": written,
        "output_file": output,
        "audit_log": audit,
        "remaining": remaining,
        "exit_code": exit_code,
    }


def _cmd_fix(args: argparse.Namespace) -> int:
    rules = parse_fix_rules(args.fix_rules)
    options = _lint_options(args)
    output: Path | None = args.output
    audit: Path | None = args.audit_log
    if audit is not None and output is None:
        raise ConfigError("--audit-log requires --output")
    if output is not None:
        check_output_path(output, protected=[args.csv], overwrite=args.overwrite)
        audit = audit or output.with_name(output.name + ".audit.json")
        check_output_path(audit, protected=[args.csv, output], overwrite=True)

    analysis = analyze_path(args.csv, options)
    source_name = analysis.report.source_file
    if analysis.parsed.unreadable or analysis.mapping is None:
        message = "cannot propose fixes: the CSV could not be read or has no usable header."
        if args.format == "json":
            _write_stdout(
                dumps(
                    _fix_summary(
                        None,
                        analysis.report.summary.to_dict(),
                        written=False,
                        output=None,
                        audit=None,
                        policy=args.formula_policy,
                        refused=False,
                        exit_code=1,
                        rules=rules,
                        source=source_name,
                    )
                )
            )
        else:
            _write_stdout(render_text(analysis.report, color=False))
            _note(message)
        return 1

    plan = plan_fixes(analysis.parsed, analysis.mapping, rules, analysis.registry.template_header)
    refused = bool(plan.formula_cells) and args.formula_policy == "refuse"
    if plan.formula_cells and args.formula_policy == "escape":
        plan.escape_formulas()
        plan.scan_formulas()
    data = plan.render()
    proposed = analyze_bytes(
        data, source_name=source_name, options=options, registry=analysis.registry
    ).report
    remaining = proposed.summary.to_dict()
    exit_code = 1 if refused or proposed.exit_code() else 0

    written = False
    if output is not None and not refused:
        assert audit is not None  # noqa: S101 - set together with output above
        atomic_write_bytes(output, data)
        source_bytes = args.csv.read_bytes()
        audit_doc = {
            "schema_version": "1.0",
            "tool": "stockmetalint",
            "tool_version": __version__,
            "created_at": timestamp(reproducible=args.reproducible),
            "source_file": source_name,
            "source_sha256": sha256_bytes(source_bytes),
            "output_file": display_name(output, show_paths=args.show_paths),
            "output_sha256": sha256_bytes(data),
            "fix_rules": list(rules),
            "formula_policy": args.formula_policy,
            "changes": [c.to_dict() for c in plan.changes],
            "skipped_rows": plan.skipped_rows,
        }
        atomic_write_bytes(audit, dumps(audit_doc).encode("utf-8"))
        written = True

    out_name = display_name(output, show_paths=args.show_paths) if output else None
    audit_name = display_name(audit, show_paths=args.show_paths) if (audit and written) else None
    if args.format == "json":
        _write_stdout(
            dumps(
                _fix_summary(
                    plan,
                    remaining,
                    written=written,
                    output=out_name,
                    audit=audit_name,
                    policy=args.formula_policy,
                    refused=refused,
                    exit_code=exit_code,
                    rules=rules,
                    source=source_name,
                )
            )
        )
        return exit_code

    esc = escape_for_terminal
    lines = [f"{esc(source_name)}: fix rules {', '.join(rules)}"]
    lines.append(
        "Dry run: no files were written."
        if output is None
        else (
            "Refused: nothing was written."
            if refused
            else f"Wrote {esc(out_name or '')} and audit log {esc(audit_name or '')}; source unchanged."
        )
    )
    lines.append(f"Changes: {len(plan.changes)}")
    for c in plan.changes:
        where = (
            f"line {c.line}" + (f" · row {c.row}" if c.row is not None else "") + f" · {c.column}"
        )
        lines += [
            f"  {esc(where)} [{c.rule}]",
            f"    - {esc(repr(c.before))}",
            f"    + {esc(repr(c.after))}",
        ]
    if plan.skipped_rows:
        lines.append(
            "Rows copied unchanged (field count mismatch): "
            + ", ".join(str(r) for r in plan.skipped_rows)
        )
    if plan.formula_cells:
        verb = "would be refused" if output is None else "refused"
        lines.append(
            f"Formula-like cells: {len(plan.formula_cells)} "
            + (
                f"(output {verb}; edit them or use --formula-policy escape)"
                if refused
                else "(remaining after escape)"
            )
        )
        for cell in plan.formula_cells[:10]:
            row = f" · row {cell.row}" if cell.row is not None else ""
            lines.append(
                f"  line {cell.line}{row} · {esc(cell.column)} starts with {cell.prefix!r}"
            )
    lines.append(
        f"Remaining after fixes: {remaining['errors']} error(s), {remaining['warnings']} "
        f"warning(s), {remaining['info']} info (exit {exit_code}). Fixes never resolve "
        "content problems such as long titles; edit those yourself."
    )
    lines.append(DISCLAIMER)
    _write_stdout("\n".join(lines) + "\n")
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    _configure_streams()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse: --help/--version exit 0, usage errors exit 2
        return exc.code if isinstance(exc.code, int) else 2
    handlers = {"doctor": _cmd_doctor, "rules": _cmd_rules, "lint": _cmd_lint, "fix": _cmd_fix}
    try:
        if args.command in ("lint", "fix"):
            validate_options(_lint_options(args))
        return handlers[args.command](args)
    except StockMetaLintError as exc:
        _note(f"stockmetalint: error: {exc}")
        return exc.exit_code
    except KeyboardInterrupt:
        _note("stockmetalint: interrupted")
        return 2
    except Exception as exc:  # noqa: BLE001 - last-resort guard; exit 2 with a short message
        _note(f"stockmetalint: internal error: {type(exc).__name__}: {exc}")
        if os.environ.get("STOCKMETALINT_DEBUG"):
            traceback.print_exc(file=sys.stderr)
        else:
            _note("Set STOCKMETALINT_DEBUG=1 for a traceback and please report the bug.")
        return 2
