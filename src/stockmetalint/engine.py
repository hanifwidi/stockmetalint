"""Lint orchestration: parse -> header -> rows -> batch -> assets -> sorted report.

This module is the public library entry point; the CLI is a thin layer on top.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from stockmetalint._version import __version__
from stockmetalint.asset_inventory import check_assets, check_releases, scan_assets
from stockmetalint.csv_input import (
    DEFAULT_MAX_INPUT_BYTES,
    ParsedCsv,
    display_name,
    parse_csv_bytes,
    read_input_bytes,
)
from stockmetalint.domain import Report
from stockmetalint.errors import ConfigError
from stockmetalint.inspection import find_ffprobe, inspect_assets, load_pillow
from stockmetalint.rules.registry import PROFILES, RuleRegistry, load_registry
from stockmetalint.validators import adobe, batch, hygiene, keywords
from stockmetalint.validators.context import ColumnMap, LintContext, RowView


@dataclass(frozen=True, slots=True)
class LintOptions:
    platform: str = "adobe-csv"
    profile: str = "standard"
    assets_dir: Path | None = None
    recursive: bool = False
    inspect: bool = False
    releases_dir: Path | None = None
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES
    ignore: frozenset[str] = field(default_factory=frozenset)
    show_paths: bool = False
    reproducible: bool = False


@dataclass(frozen=True, slots=True)
class Analysis:
    """Full result of a lint run, including parsed data (used by ``fix``)."""

    report: Report
    parsed: ParsedCsv
    mapping: ColumnMap | None
    rows: tuple[RowView, ...]
    registry: RuleRegistry


def validate_options(options: LintOptions) -> RuleRegistry:
    registry = load_registry(options.platform)
    if options.profile not in PROFILES:
        raise ConfigError(f"unknown profile {options.profile!r}; choose from {', '.join(PROFILES)}")
    for code in sorted(options.ignore):
        registry.get(code)  # raises ConfigError with suggestions
    if (options.inspect or options.recursive) and options.assets_dir is None:
        raise ConfigError("--inspect and --recursive require --assets DIR")
    if options.max_input_bytes <= 0:
        raise ConfigError("--max-input-bytes must be positive")
    return registry


def timestamp(*, reproducible: bool, now: datetime | None = None) -> str | None:
    """UTC timestamp; in reproducible mode use SOURCE_DATE_EPOCH or None."""
    if reproducible:
        epoch = os.environ.get("SOURCE_DATE_EPOCH", "")
        if not epoch.isdigit():
            return None
        moment = datetime.fromtimestamp(int(epoch), UTC)
    else:
        moment = now or datetime.now(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def lint_path(path: Path | str, options: LintOptions | None = None) -> Report:
    """Lint a CSV file on disk. Raises :class:`StockMetaLintError` for exit-2 failures."""
    return analyze_path(path, options).report


def lint_bytes(
    data: bytes, *, source_name: str = "input.csv", options: LintOptions | None = None
) -> Report:
    """Lint CSV content already in memory (no file system access unless assets are given)."""
    opts = options or LintOptions()
    return analyze_bytes(data, source_name=source_name, options=opts,
                         registry=validate_options(opts)).report


def analyze_path(path: Path | str, options: LintOptions | None = None) -> Analysis:
    opts = options or LintOptions()
    registry = validate_options(opts)
    source = Path(path)
    data = read_input_bytes(source, opts.max_input_bytes)
    return analyze_bytes(data, source_name=display_name(source, show_paths=opts.show_paths),
                         options=opts, registry=registry)


def analyze_bytes(
    data: bytes, *, source_name: str, options: LintOptions, registry: RuleRegistry
) -> Analysis:
    ctx = LintContext(registry, options.profile)
    adobe.check_file(ctx, source_name, len(data))
    parsed = parse_csv_bytes(data, ctx.emit)

    mapping: ColumnMap | None = None
    rows: list[RowView] = []
    if not parsed.unreadable:
        if parsed.header is None:
            ctx.emit("ADOBE-CSV-HEADER-ABSENT", "No header row: the file contains only blank records.",
                     suggestion="Add the template header: " + ",".join(registry.template_header))
        else:
            mapping = adobe.map_header(ctx, parsed.header, parsed.header_line or 1)
        if mapping is not None:
            rows = adobe.build_rows(ctx, parsed, mapping)
            _check_rows(ctx, rows)
            batch.check_batch(ctx, rows)
            adobe.check_category_summary(ctx, rows)
        adobe.check_row_limit(ctx, len(parsed.records))

    assets_checked = False
    media_inspected = False
    if options.assets_dir is not None:
        inventory = scan_assets(options.assets_dir, recursive=options.recursive)
        if mapping is not None and "Filename" in mapping:
            matched = check_assets(ctx, rows, inventory)
            assets_checked = True
            if options.inspect:
                inspect_assets(ctx, matched, image_module=load_pillow(), ffprobe=find_ffprobe())
                media_inspected = True
    if options.releases_dir is not None:
        releases = scan_assets(options.releases_dir, label="releases")
        if mapping is not None and "Releases" in mapping:
            check_releases(ctx, rows, releases)

    diagnostics = sorted(
        (d for d in ctx.diagnostics if d.code not in options.ignore), key=lambda d: d.sort_key()
    )
    report = Report(
        tool_version=__version__,
        platform=registry.platform,
        profile=options.profile,
        rule_profile_version=registry.profile_id,
        rule_verification=registry.verification_label,
        source_file=source_name,
        checked_at=timestamp(reproducible=options.reproducible),
        data_rows=None if parsed.unreadable else len(parsed.records),
        fatal=parsed.unreadable or parsed.parse_stopped or mapping is None,
        assets_checked=assets_checked,
        media_inspected=media_inspected,
        diagnostics=tuple(diagnostics),
    )
    return Analysis(report, parsed, mapping, tuple(rows), registry)


def _check_rows(ctx: LintContext, rows: list[RowView]) -> None:
    for row in rows:
        if not row.aligned:
            continue
        hygiene.check_cells(ctx, row)
        if row.filename is not None:
            adobe.check_filename(ctx, row, row.filename)
        if row.title is not None:
            adobe.check_title(ctx, row, row.title)
        if row.keywords is not None:
            keywords.check_keywords(ctx, row, row.keywords)
        if row.category is not None:
            adobe.check_category(ctx, row, row.category)
        if row.releases is not None:
            adobe.check_releases(ctx, row, row.releases)
