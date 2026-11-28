# Bundle format (v1.0 draft)

**Status: v1.0 schemas and validator built; nothing writes bundles yet.** This page is the
contract. Once v1.0 is released, it changes only as described under "Versions".

- Schemas: `smpldoc/domain/schemas/bundle/1.0/*.schema.json` (JSON Schema 2020-12).
- Example: `tests/fixtures/bundles/1.0/invoice/` (fictional).
- Check one: `python -m smpldoc bundle-validate FOLDER` (no configuration needed).

A **bundle** is everything smpldoc knows about one document. One email can carry several
documents, so one job can have several bundles.

## Layout

```
bundles/<company>/<bundle-id>/
  manifest.json
  original/<file name as received>
  text.json
  layout.json
  fields.json
  card.json
  pages/0001.png ...      optional, regenerable
  history/<version>/...   older derived files, kept after an upgrade
```

`<bundle-id>` and `job_id` are smpldoc ids: 32 lowercase hex characters, time ordered. Paths are
the same in a folder and in a bucket. All JSON is strict UTF-8 (no duplicate keys, no `NaN`), keys
in `snake_case`, times in UTC ISO 8601 ending in `Z`, dates `YYYY-MM-DD`, and amounts as decimal
strings (`"1234.56"`), never floats.

## Files

### `manifest.json`

```json
{
  "format": "smpldoc.bundle",
  "version": "1.0",
  "bundle_id": "019ac8f0c4000000000000000000b001",
  "company": "acme",
  "job_id": "019ac8f0c4000000000000000000a001",
  "created_at": "2026-12-01T09:30:00Z",
  "source": {"kind": "mail", "sender": "scanner@example.com", "subject": "Scan", "received_at": "2026-12-01T09:29:58Z"},
  "original": {"path": "original/scan-0001.pdf", "content_type": "application/pdf", "size": 182044, "sha256": "..."},
  "engines": [{"step": "ocr", "name": "tesseract", "version": "5.3.0"}],
  "files": {"text.json": "sha256...", "layout.json": "sha256...", "fields.json": "sha256...", "card.json": "sha256..."},
  "upgraded_from": []
}
```

### `text.json`: the raw data and where it is

Every piece of text read from the document, in reading order. Positions are fractions of the page
(0 to 1, origin top left), so they do not depend on the scan resolution.

```json
{"pages": [{"page": 1, "width_pt": 612, "height_pt": 792, "rotation": 0, "source": "ocr",
  "words": [{"id": "p1w1", "text": "Invoice", "box": [0.08, 0.06, 0.21, 0.09], "confidence": 0.97}]}]}
```

`source` is `pdf-text` when the PDF carried its own text, or `ocr` when it was read from pixels.

### `layout.json`: enough to rebuild the document

The structure on top of `text.json`, by reference to word ids: blocks (heading, paragraph, table,
form field, signature, stamp), lines, table cells, and reading order. A renderer can rebuild the
document's content and layout from `text.json` and `layout.json` alone. It is a faithful
replica, not a pixel copy: the original stays in the bundle for that.

### `fields.json`: the answer, with its evidence

```json
{"kind": "invoice",
 "fields": [{"name": "amount_due", "value": "1234.56", "confidence": 0.93,
             "evidence": ["p1w88", "p1w89"], "engine": "rules"}]}
```

Every value points to the words it was read from, so a person or an agent can check it.

### `card.json`: the quick read

Small on purpose (at most 2048 bytes), so thousands can be searched at once.

```json
{"kind": "invoice", "category": "financial", "title": "Invoice 4471 from Example Supply Co",
 "parties": ["Example Supply Co", "Acme Ltd"], "dates": {"issued": "2026-11-28", "due": "2026-12-28"},
 "totals": {"currency": "USD", "amount_due": "1234.56"}, "pages": 2, "language": "en",
 "summary": "Invoice for 40 pallets of packaging, due 28 December.", "tags": []}
```

Categories in v1.0: `financial`, `legal`, `logistics`, `identity`, `correspondence`, `other`.
Kinds start with `invoice`, `bill`, `receipt`, `statement`, `contract`, `delivery-note`,
`purchase-order`, `letter`, `form`, `document` (unknown).

## Versions

`version` is `MAJOR.MINOR`.

- **Minor (1.0 to 1.1):** only adds optional fields or new kinds and categories. A 1.0 reader
  checks a 1.1 bundle leniently: unknown fields and unknown list values are accepted, everything
  else is checked. A bundle of the reader's own version is checked strictly: an unknown field is an
  error. A 1.1 reader reads 1.0 as is.
- **Major (1.x to 2.0):** may rename or restructure. It ships with an upgrade.
- smpldoc always reads every older version. It writes only the current one.

### Upgrades

Each version step has:

1. an upgrade note at `docs/bundle-upgrades/<from>-to-<to>.md`: what changed, why, and whether the
   upgrade is a **migrate** (rewrite the derived files from the old ones, fast, no engine needed) or
   a **reprocess** (read the original again, slower, may use an AI service),
2. an upgrade function with tests,
3. example bundles of the old version that must upgrade with nothing lost.

An upgrade never touches `original/`. It moves the old derived files to `history/<old version>/`,
writes the new ones, and adds a line to `upgraded_from` in the manifest, so it can be undone.

## Rules

- Allowed files: `manifest.json`, the original under `original/`, the four derived files, and
  anything under `pages/` or `history/`. Every file except the manifest and the original is listed
  in `files` with its SHA-256; the original carries its own hash and size.
- Paths are relative, use `/`, and have no empty, `.` or `..` parts. A link is never followed.
- Word ids are `p<page>w<n>` and unique; blocks are `p<page>b<n>`. Every id in `layout.json` and in
  `fields.json` evidence must be a word in `text.json`. Pages are numbered from 1, in order, and the
  card's page count matches. The card's kind matches `fields.json`.
- A bundle holds only what came in and what was read from it. No secrets, no tokens, no settings.
- Every file is listed with its hash in the manifest. `bundle validate` fails on a mismatch.
- Bundles are data. Nothing in a bundle is ever executed.
