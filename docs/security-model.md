# Security model

## Assets and trust boundaries

* **Untrusted input**: CSV bytes, file names inside the CSV, names and contents of files in the
  asset and releases directories.
* **Trusted**: the command-line arguments given by the user who runs the tool, and the bundled
  rule registry.
* **Must never happen**: executing CSV content; reading outside the asset directory through
  links or paths taken from the CSV; overwriting or truncating the source CSV; network access;
  leaking private paths into shareable reports.

## Threats and mitigations

| Threat | Mitigation | Tests |
|---|---|---|
| Path traversal via `Filename` (`../x.jpg`, `/etc/x`, `C:\x`, `\\server\x`, URLs) | Reported as `ADOBE-CSV-FILENAME-PATH`; such names are never looked up on disk | `test_path_problem`, `test_path_like_filenames_are_not_matched` |
| Symlink escape from the asset folder | Links are resolved only to classify them; targets outside the root are reported (`ASSET-SYMLINK-ESCAPE`) and never read; symlinked directories are never descended | `test_symlink_escape_and_broken_links_are_not_followed` |
| Spreadsheet formula injection (`= + - @`, tab, CR) | Reported (`SEC-FORMULA-PREFIX`); `fix` refuses to write such cells unless `--formula-policy escape` is chosen explicitly | `test_formula_prefix`, `test_fix_refuses_source_and_formula_cells` |
| Terminal escape injection through CSV text | All untrusted text in text output is escaped (`\x1b`, bidi controls) | `test_escape_for_terminal_neutralizes_escape_sequences`, `test_text_report_escapes_terminal_sequences` |
| Visual spoofing (bidi overrides, zero-width characters) | `SEC-INVISIBLE-CHAR`; filenames also flag joiners | `test_hygiene_checks` |
| Audit log or output over an existing or special file | `--audit-log` honours `--overwrite`; FIFOs/devices refused; the audit is removed if the CSV write fails | `test_audit_log_respects_overwrite_and_never_hits_source`, `test_special_file_output_is_refused` |
| Windows directory junctions | Classified like symlinks and never descended | code path only (no Windows runner locally) |
| Overwriting the source with `fix` or `lint --output` | Refused if the output is the same file (path, `..`, symlink, hard link via `samefile`, case-variant on macOS/Windows); existing outputs need `--overwrite` | `test_output_must_not_alias_source`, `test_output_symlink_is_refused`, `test_case_variant_alias_on_case_insensitive_platforms` |
| Partial or corrupt output after a crash | Temp file in the same directory, `fsync`, atomic `replace`; temp file removed on any error | `test_atomic_write_success_and_cleanup_on_failure` |
| Memory exhaustion | 32 MiB input cap (configurable), 128 KiB csv field limit, 200,000-entry and depth-32 caps on directory scans, JPEG decoded at 1/8 scale with Pillow's decompression-bomb guard | `test_read_input_guards`, `test_entry_cap`, `test_5000_row_batch_is_fast_and_bounded` |
| Malicious media triggering network access in ffprobe | Only files whose signature matches MP4/MOV reach ffprobe; `-protocol_whitelist file`; absolute path argument; no shell; 30 s timeout | `test_ffprobe_codec_duration_and_unreadable`, `test_ffprobe_failures_are_inconclusive` |
| Privacy leak of local paths in shared reports | Base names by default; `--show-paths` is opt-in; ffprobe stderr is scrubbed of the absolute path | `test_json_report_to_file_and_paths` |
| Network access | None in the code; tests patch `socket` to fail and lint still succeeds | `test_no_network_during_lint` |

## Formula-escape round-trip trade-off

Prefixing `'` neutralizes a formula in spreadsheet applications, but the apostrophe becomes part
of the value that Adobe imports (for example the title `'=HYPERLINK(...)`). The safe default is
therefore to **refuse** and let the contributor rephrase the cell. `escape` exists for users who
only want a spreadsheet-safe review copy.

## Supply chain

* Zero runtime dependencies. Optional Pillow is used only for `--inspect`.
* GitHub Actions are pinned to full commit SHAs that were resolved with `git ls-remote` on
  2026-11-09; Dependabot proposes monthly grouped updates.
* CI uses a read-only token, `persist-credentials: false`, needs no secrets, and runs
  `pip-audit`.
* Publishing uses PyPI Trusted Publishing (OIDC) and is gated behind a protected environment
  and a repository variable. It is disabled until the maintainer approves.
