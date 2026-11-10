# Roadmap

Ordered by value to contributors. Nothing here is promised by a date.

## Next (0.1.x)

* **Verify every Adobe rule against the live pages** and promote them to `verified`. Today they
  are snippet-corroborated only; see [rule-sources.md](rule-sources.md).
* Download and compare the official CSV template once accessible, and pin its header.
* Confirm the multi-release separator and category numbering; then decide whether
  `ADOBE-CSV-CATEGORY-UNKNOWN` can become an error.

## Later

* Additional platform profiles (for example Shutterstock CSV), each with its own source-dated
  registry file and discrepancy notes.
* Optional read-only comparison between CSV metadata and embedded XMP/IPTC (ExifTool as an
  optional tool, reporting INCONCLUSIVE when absent).
* SARIF output for code-scanning dashboards.
* A pre-commit hook definition.
* Localized messages (Indonesian first).

## Explicitly out of scope

* Generating or translating titles and keywords; AI inference of any kind.
* Uploading, account login, or interacting with contributor portals or rate limits.
* Judging image content, quality or acceptance likelihood.
