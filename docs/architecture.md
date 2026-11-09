# Architecture

StockMetaLint is a small layered library with a thin CLI on top. Each layer depends only on
the layers below it, so the core can be reused without the CLI.

```text
cli.py ──────────────► engine.py ──► csv_input.py      (bytes -> UTF-8 -> csv records)
  │                       │     ├──► validators/        (header, fields, keywords, hygiene, batch)
  │                       │     ├──► asset_inventory.py (safe directory scan + name matching)
  │                       │     └──► inspection.py      (optional Pillow / ffprobe format checks)
  ├──► reporters/ (text, JSON, rules catalog)
  ├──► fixes/safe.py (allow-listed mechanical fixes)
  └──► safe_io.py (alias-proof, atomic output)
rules/registry.py ◄── rules/adobe_csv_2026_06.json + rules/core.json  (single source of limits)
domain.py (Severity, Diagnostic, Report) and errors.py are shared by every layer.
```

## Data flow of `lint`

1. **Input guard** (`csv_input.read_input_bytes`): regular files only, 32 MiB safety cap,
   directories/devices refused. These are exit-2 failures (`InputError`).
2. **Byte-level checks** (`parse_csv_bytes`): empty file, binary signatures (XLSX/XLS/PDF/images),
   UTF-16/32 BOMs, NUL bytes, UTF-8 BOM (accepted, reported as info), strict UTF-8 decoding with
   byte offset and line number for up to five invalid sequences.
3. **Strict CSV parsing** with the standard library (`csv.reader(strict=True)`). Each record
   keeps its physical start/end line (`reader.line_num`) and a separate data-row index.
   Parsing stops at the first malformed record; rows before it are still checked.
4. **Header mapping** (`validators/adobe.map_header`): exact template spelling is required.
   Near misses (case, spacing, plural, small typos) are reported but still mapped so row checks
   can continue.
5. **Row checks**: hygiene/security, filename, title, keywords, category, releases.
6. **Batch checks** (`validators/batch.py`): duplicates and review warnings, all O(n) via hashing.
7. **Assets** (optional): inventory, exact matching, orphans, then optional inspection.
8. **Report**: diagnostics filtered by `--ignore`, sorted deterministically (file-level first,
   then row, then rule ID) and wrapped in a frozen `Report`.

## Rule registry

Every diagnostic is created through `RuleRegistry.make(rule_id, ...)`, which copies severity,
scope and source URL from the JSON registry. Limits are read with `int_limit` / `range_limit`, so
changing a limit is a data change. The loader validates every field strictly (unknown scopes or
verification states, mismatched source URLs, duplicate IDs, and a `verified_at` without
`verification: "verified"` are all rejected), and tests mutate the JSON to prove each check fires.

## Design decisions

* **argparse instead of Typer/Click**: keeps zero runtime dependencies, and therefore a trivial
  offline install and no supply-chain surface for end users. The cost is a slightly more verbose CLI
  module.
* **Dataclasses instead of pydantic**: the model is small, immutable (`frozen=True, slots=True`)
  and fully typed under `mypy --strict`.
* **Standard-library CSV** in strict mode: well-tested and documented behaviour for quoting,
  embedded newlines and line counting.
* **Optional extras**: Pillow (`[images]`) and `ffprobe` are only used by `--inspect`. When they
  are missing, results are explicitly INCONCLUSIVE.
* **Never rewrite content**: `fix` performs only allow-listed mechanical changes (whitespace,
  empty/duplicate keyword items, NFC, header spelling). Titles, keyword choice and order,
  categories and file names are left to the contributor.

## Extending to another platform

Add `rules/<platform>_<date>.json` with its sources and rules, register it in
`rules/registry.PLATFORMS`, and add a validator module. The core rules (`core.json`) and the
asset, report and fix layers are platform-neutral.
