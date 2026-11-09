# Rule discrepancies and how they are modelled

## 1. Keyword limit: 50 (CSV) vs 49 (guidance)

* CSV requirements page (snippet): "Include a maximum of 50 keywords".
* Guidance pages (snippets): "up to 49 per content submission" (*Tips for effective titles and
  keywords*) and "up to 49 keyword tags for all types of assets" (*Maximize metadata to get
  discovered*).
* The project brief attributes the 49 figure to the *editorial* submission metadata guide. The
  search evidence shows it on general guidance pages too, so the figure may apply beyond editorial
  content. This could not be confirmed on live pages.

**Model:** two rules with different scopes.

| Rule | Scope | Limit | Severity | Profiles |
|---|---|---|---|---|
| `ADOBE-CSV-KEYWORDS-MAX` | `adobe-csv` | 50 | error | standard, editorial |
| `ADOBE-GUIDANCE-KEYWORDS-49` | `adobe-guidance` | 49 | warning (advisory) | editorial only |

A CSV row with exactly 50 keywords **passes** in both profiles (exit 0). In `--profile editorial`
it also carries a non-blocking advisory. Tests: `test_keyword_count_scopes` (0, 1, 49, 50, 51).

## 2. Filename length (30) appears only on some page versions

A search summary noted that the 30-character filename limit appears on some localized versions
of the CSV requirements page but not others. It is kept as an error, since the snippet text exists,
with a note in `ADOBE-CSV-FILENAME-LENGTH` to re-verify.

## 3. "MB" is not defined

The source says "1MB or smaller" without saying whether that means 1,000,000 or 1,048,576 bytes.
Above 1,048,576 bytes is an error; the band in between is a warning (`ADOBE-CSV-FILE-SIZE-DECIMAL`).

## 4. "Special characters" in titles is not defined

The title snippet says "without commas or special characters". Only commas are checked
(`ADOBE-CSV-TITLE-COMMA`, warning). Inventing a "special character" list would present guesses
as policy.

## 5. Header order and optional columns

"Use the exact headers from the official template without changes" supports exact spelling.
Whether the uploader enforces **order**, or rejects files that **omit** optional columns, is not
documented. Both are warnings (`ADOBE-CSV-HEADER-ORDER`, `ADOBE-CSV-HEADER-OPTIONAL-MISSING`).
Misspelled, unknown or duplicate headers are errors.

## 6. Category numbers

The CSV page says to enter a category number; the full numbered list could not be verified.
A non-numeric value is an error. A number outside the seed list 1–21 is only a warning
(`ADOBE-CSV-CATEGORY-UNKNOWN`).

## 7. Multiple releases in one cell

The separator for several release names is not documented in the evidence. StockMetaLint
splits on commas and checks each name's length.

## 8. Adobe Missions are out of scope

Adobe Missions use their own brief and scene rules. None of them are applied to normal Adobe Stock
CSV validation.
