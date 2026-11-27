# Roadmap

What comes next, in the order it will be built. Each step is one pull request with tests first.
Status of every feature: [FEATURES.md](FEATURES.md).

## Chapter 1: the job pipeline (done)

Mail in (relay pull, Amazon SES to a bucket), a job per email, a sender trust gate, routing rules,
job moves, forwarding by SMTP, a hardened container. See [ARCHITECTURE.md](ARCHITECTURE.md).

## Chapter 2: the document bundle (now)

**Goal:** every document that arrives is turned into a **bundle**: a small set of files, in a
published and versioned format, that holds the original, everything read from it, where on the page
each thing was found, and a short card that says what the document is. Bundles live in storage you
own. An AI agent can read them through MCP, so nobody has to open the mail and retype it.

**Example:** a warehouse scans 100 delivery notes to its scanner, which emails them to your intake
address. Each one becomes a bundle. An agent asks "which delivery notes from last week mention a
short shipment?" and gets an answer from the cards, then reads the full text of only the matches.

### What a bundle holds

| File | What it is | Why |
|---|---|---|
| `manifest.json` | Format version, ids, where it came from, which engines read it, a hash of every file | Proves what is in the bundle and what made it |
| `original/` | The file exactly as received (PDF, TIFF, JPEG, PNG) | Nothing is lost; reprocess at any time |
| `text.json` | Every piece of text, with its page, position and confidence | The raw data, and where it sits on the page |
| `layout.json` | Pages, blocks, lines, tables and form fields, in reading order | Rebuild the document's content and layout without the original |
| `fields.json` | Field values (amount due, invoice number, ...), each pointing back to where it was read | The answer, with its evidence |
| `card.json` | A few hundred bytes: kind (invoice, contract, ...), category (financial, legal, ...), title, parties, dates, totals, page count, a short summary | Search thousands of documents without reading them all |

The full contract, including how versions change, is [BUNDLE_FORMAT.md](BUNDLE_FORMAT.md).

### Rules for this chapter

- **Storage is the source of truth.** Bundles are files in a folder or an S3-compatible bucket. The
  database only indexes them and can be rebuilt from storage at any time.
- **The original is never changed.** Everything else in a bundle can be regenerated from it.
- **Versions never lose data.** A newer format version reads every older one, and each version
  step ships with a tested upgrade and a written upgrade note.
- **Reading works offline.** The image includes a local OCR engine, so it is useful with no AI
  service at all. An AI service you choose and configure can read documents better.
- **MCP is read-only by default** and uses the same sign-in as the portal.

### Steps (one pull request each, tests first)

1. **Format v1.0 on paper:** `BUNDLE_FORMAT.md`, a JSON Schema per file, an example bundle, and a
   validator with tests. No behaviour change.
2. **Write bundles:** the runner writes a bundle for every document to the `Blob` port, and a
   `bundle validate` command checks one.
3. **Read PDFs and images:** split pages, use a PDF's own text where it has one, OCR the rest, and
   fill `text.json` and `layout.json` with positions.
4. **Cards:** classify each document and write `card.json` from its fields and text.
5. **Index:** search cards in SQLite, and a `reindex` command that rebuilds the index from storage.
6. **Upgrades:** the upgrade framework, `bundle upgrade`, and a test that every old example bundle
   upgrades to the current version with nothing lost.
7. **MCP:** read-only tools to search cards and read bundles, with a golden test of the tool list.
8. **Bucket blob:** bundles in an S3-compatible bucket, with no volume needed.
9. **First release:** signed image, SBOM, release notes.

### Not in this chapter

A web portal, sign-in, and a rebuilt UI come in a later chapter. Until then, commands and MCP are the
way in.

## Later

- Portal and OIDC sign-in.
- More mail sources (IMAP) and deploy guides (Cloudflare, Azure).
- Optional external services through the same ports, for example a durable workflow engine or an
  indexed document database instead of a slow-moving bucket. The free edition always works on its
  own without them.
