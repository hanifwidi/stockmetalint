# Rule sources and verification record

**Status on 2026-11-09: no Adobe rule could be verified against a live official page.**

The build environment's network policy blocked `helpx.adobe.com`. Both direct HTTP and the
fetch tool failed with "host not in allowed domains". The only evidence available was:

* the project brief's seed facts (which state the page dates below), and
* **web-search result snippets** that quote the official pages, retrieved on 2026-11-09.

So every Adobe rule has `verified_at: null` and one of these verification states (see
`stockmetalint rules show <RULE-ID>`):

| State | Meaning |
|---|---|
| `verified` | Read on the live official page on `verified_at` (none in this release) |
| `snippet-corroborated` | Search-engine snippets quoting the official page support the fact |
| `summary-corroborated` | Only a search-engine summary supports it (no verbatim quote) |
| `partially-corroborated` | Part of the fact is supported (e.g. category names, not all numbers) |
| `seed-unverified` | Only the project brief supports it |
| `standard-reference` | A public standard (RFC, Unicode, OWASP, WHATWG), not re-fetched |
| `tool-defined` | StockMetaLint's own integrity/hygiene/security rule, not an Adobe policy |

## Adobe sources

| Source | URL | Page date (basis) | Evidence (accessed 2026-11-09) |
|---|---|---|---|
| CSV requirements for Adobe Stock | https://helpx.adobe.com/stock/contributor/manage-your-portfolio/csv-requirements-content.html | 2026-06-11 (brief) | Snippets: "Limit your CSV to a maximum of 5,000 rows. The overall document must be 1MB or smaller."; "Use the exact headers from the official template without changes."; "Exact filename including extension (e.g., Myphoto1.jpg, Myvideo1.mov)."; "Title, 70 characters maximum, plain text description without commas or special characters."; "Include a maximum of 50 keywords, and don't include technical data."; "Enter the number of the category that best describes the content."; "Other columns are optional, but we highly recommend that you add categories."; "Releases need to be JPEGs with filenames that are 30 characters or fewer."; "If we find multiple releases with the same name, we'll use the most recent one."; "If you're located outside the US and using Excel to create a CSV file, you need save your document as CSV UTF-8."; "CSV only (comma-separated values)" |
| Create a CSV file | https://helpx.adobe.com/stock/contributor/manage-your-portfolio/create-csv-file.html | 2026-06-11 (brief) | None obtained |
| Upload a CSV file | https://helpx.adobe.com/stock/contributor/manage-your-portfolio/upload-csv-file.html | 2026-06-11 (brief) | None obtained |
| Tips for effective titles and keywords | https://helpx.adobe.com/stock/contributor/content-policies-guidelines/metadata/tips-effective-titles-keywords.html | 2026-09 (brief) | Snippet on the same-titled page at `.../stock/contributor/help/titles-and-keyword.html`: "Including keywords (up to 49 per content submission) helps customers discover your content." |
| Maximize metadata to get discovered | https://helpx.adobe.com/stock/contributor/help/artist-hub-migration/maximize-metadata-to-get-discovered.html | unknown | Snippet: "While you can add up to 49 keyword tags for all types of assets on Adobe Stock, more isn't always better." |
| Contributor content upload guidelines | https://helpx.adobe.com/stock/contributor/content-policies-guidelines/content-policies/content-upload-guidelines.html | 2026-09 (brief) | None obtained |
| Photo technical requirements | https://helpx.adobe.com/stock/contributor/submit-your-content/submit-photos/technical-legal-requirements-photo-submission.html | unknown | Search summary only: 4–100 MP, 45 MB maximum, JPEG/sRGB |
| Video requirements | https://helpx.adobe.com/stock/contributor/help/video-requirements.html | unknown | Search summary only: 5–60 s, MOV/MP4 with H.264 |
| Adobe Stock categories | https://helpx.adobe.com/stock/contributor/help/categories.html | unknown | Names Animals, Buildings and Architecture, Business, Drinks in that order; a third-party source maps 7 Food, 8 Graphic Resources, 19 Technology, 20 Transport. Other numbers are a maintainer seed. |

**Header spelling** `Filename,Title,Keywords,Category,Releases` comes from the brief. It is
corroborated only by third-party usage: a GitHub code search on 2026-11-09 returned 38 files
containing exactly that header line. The official template file could not be downloaded.

## Measurement decisions

* **Characters** = Unicode code points after UTF-8 decoding, without normalization. A separate
  `META-LENGTH-UTF16` warning fires when text fits by code points but not by UTF-16 code units
  (what browser `maxlength` counts). Messages also show the NFC length when it differs.
* **1 MB**: an error above 1,048,576 bytes (exceeds both MB and MiB) and a warning between
  1,000,001 and 1,048,576 bytes. Size is measured in bytes on disk, including any BOM.
* **5,000 rows** = data rows, excluding the header and blank records.
* **Keywords** = non-empty items of the Keywords cell split on ASCII commas.

## How to re-verify (maintainers)

1. Open each Adobe URL above in a browser and record the "Last updated" date.
2. Compare every limit and header with `stockmetalint rules show <RULE-ID>`.
3. Update the JSON. Set `verification: "verified"` and `verified_at: "<date>"` only for facts you
   read on the page; the loader rejects `verified_at` without `verified`.
4. Regenerate the catalog (`stockmetalint rules list --format markdown > docs/rules.md`), run the
   tests, and record the change in CHANGELOG.md and docs/rule-discrepancies.md.
