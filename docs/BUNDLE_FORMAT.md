# Bundle format (v1.0 draft)

**Status: draft, nothing writes bundles yet.** This page is the contract. Once v1.0 is released,
it changes only as described under "Versions". JSON Schemas for each file arrive with step 1 of
[ROADMAP.md](ROADMAP.md) Chapter 2.

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

`<bundle-id>` is a ULID. Paths are the same in a folder and in a bucket. All JSON is UTF-8, keys
in `snake_case`, times in UTC ISO 8601, and amounts as decimal strings (`"1234.56"`), never floats.

## Files

### `manifest.json`

```json
{
  "format": "smpldoc.bundle",
  "version": "1.0",
  "bundle_id": "01JD0000000000000000000000",
  "company": "acme",
  "job_id": "01JD0000000000000000000001",
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
{"kind": "invoice", "schema": "smpldoc.kind.invoice/1",
 "fields": [{"name": "amount_due", "value": "1234.56", "confidence": 0.93,
             "evidence": ["p1w88", "p1w89"], "engine": "rules"}]}
```

Every value points to the words it was read from, so a person or an agent can check it.

### `card.json`: the quick read

Small on purpose (target under 2 KB), so thousands can be searched at once.

```json
{"kind": "invoice", "category": "financial", "title": "Invoice 4471 from Example Supply Co",
 "parties": ["Example Supply Co", "Acme Ltd"], "dates": {"issued": "2026-11-28", "due": "2026-12-28"},
 "totals": {"amount_due": "1234.56", "currency": "USD"}, "pages": 2, "language": "en",
 "summary": "Invoice for 40 pallets of packaging, due 28 December.", "tags": []}
```

Categories in v1.0: `financial`, `legal`, `logistics`, `identity`, `correspondence`, `other`.
Kinds start with `invoice`, `bill`, `receipt`, `statement`, `contract`, `delivery-note`,
`purchase-order`, `letter`, `form`, `document` (unknown).

## Versions

`version` is `MAJOR.MINOR`.

- **Minor (1.0 to 1.1):** only adds optional fields or new kinds. A 1.0 reader ignores what it does
  not know. A 1.1 reader reads 1.0 as is.
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

- A bundle holds only what came in and what was read from it. No secrets, no tokens, no settings.
- Every file is listed with its hash in the manifest. `bundle validate` fails on a mismatch.
- Bundles are data. Nothing in a bundle is ever executed.
