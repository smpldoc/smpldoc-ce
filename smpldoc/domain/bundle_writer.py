"""Write a bundle (docs/BUNDLE_FORMAT.md) for a document smpldoc can read today: plain text.

Pure functions: bytes in, a mapping of path to bytes out. Nothing here touches storage or imports an
adapter. PDFs and images are not readable yet (roadmap step 3), so `skip_reason` says so and the
caller records that no bundle was written. Everything is deterministic: the same inputs give the same
bytes, so writing a bundle again after a crash or a reprocess is harmless.

Plain text has no page geometry, so words are placed on a fixed grid (60 lines of up to 100
characters per page, fractions of the page). The boxes say where a word is in reading order, not where
ink was found.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Optional, Sequence

from .bundle import FORMAT, VERSION

MAX_TEXT_BYTES = 256 * 1024  # larger text is skipped, not cut: a bundle must hold everything read
LINES_PER_PAGE, COLUMNS = 60, 100
MARGIN, SPAN = 0.05, 0.9
PAGE_WIDTH_PT, PAGE_HEIGHT_PT = 612, 792
MAX_WORD, MAX_FIELDS, MAX_VALUE = 1000, 500, 4096
UNLOCATED_CONFIDENCE = 0.5  # a value with no matching line: kept, but nothing points at the page for it

_TOKEN = re.compile(r"\S+")
_NAME_OK = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]+")
_FILE_BAD = re.compile(r"[^A-Za-z0-9._ ()+,=@-]")
_ENGINES = [{"step": "layout", "name": "text-grid", "version": "1"},
            {"step": "fields", "name": "plain-text", "version": "1"},
            {"step": "card", "name": "basic", "version": "1"}]


def skip_reason(content_type: str, data: bytes) -> str:
    """"" if a bundle can be written for this document now, else a short code for the step event."""
    if content_type.split(";")[0].strip().lower() != "text/plain":
        return "not-readable-yet"
    if len(data) > MAX_TEXT_BYTES:
        return "too-large"
    if not data.strip():
        return "empty"
    return ""


def build(*, company: str, bundle_id: str, job_id: str, created_at: str, sender: str, subject: str,
          filename: str, content_type: str, data: bytes, pairs: Sequence[tuple[str, str]],
          source_kind: str = "mail") -> Optional[dict[str, bytes]]:
    """The files of one bundle, or None if the document cannot be read yet."""
    if skip_reason(content_type, data):
        return None
    when = _utc(created_at)
    lines = _grid(data.decode("utf-8", errors="replace"))
    text, layout, located = _text_and_layout(lines)
    fields = {"kind": "document", "fields": _fields(pairs, lines, located)}
    pages = len(text["pages"])
    card = {"kind": "document", "category": "other", "title": _title(subject, filename), "parties": [], "dates": {},
            "totals": {}, "pages": pages, "language": "und", "summary": "", "tags": []}
    derived = {"text.json": _json(text), "layout.json": _json(layout), "fields.json": _json(fields), "card.json": _json(card)}
    original = "original/" + _safe_name(filename)
    manifest = {
        "format": FORMAT, "version": VERSION, "bundle_id": bundle_id, "company": company, "job_id": job_id,
        "created_at": when,
        "source": {"kind": source_kind, "sender": sender[:320], "subject": _CONTROL.sub(" ", subject)[:998], "received_at": when},
        "original": {"path": original, "content_type": "text/plain", "size": len(data), "sha256": _sha(data)},
        "engines": _ENGINES,
        "files": {name: _sha(body) for name, body in derived.items()},
        "upgraded_from": [],
    }
    return {"manifest.json": _json(manifest), original: bytes(data), **derived}


# ---- text -> grid --------------------------------------------------------------------------
def _grid(text: str) -> list[list[tuple[str, int, int]]]:
    """One entry per line: its tokens with their column start and end. Blank lines are kept."""
    out = []
    for line in text.splitlines():
        row = []
        for m in _TOKEN.finditer(line):
            token, start = m.group(), m.start()
            for i in range(0, len(token), MAX_WORD):
                piece = token[i:i + MAX_WORD]
                row.append((piece, start + i, start + i + len(piece)))
        out.append((line, row))
    return out


def _text_and_layout(lines):
    """text.json, layout.json and, for each source line, the ids of its words (to locate fields)."""
    pages, layout_pages, located = [], [], {}
    row_h = SPAN / LINES_PER_PAGE
    for p, start in enumerate(range(0, len(lines), LINES_PER_PAGE), 1):
        words, blocks, current = [], [], []
        for r, (line, row) in enumerate(lines[start:start + LINES_PER_PAGE]):
            cw = SPAN / max(COLUMNS, len(line))
            top = MARGIN + r * row_h
            ids = []
            for token, c0, c1 in row:
                wid = f"p{p}w{len(words) + 1}"
                words.append({"id": wid, "text": token, "box": [_r(MARGIN + c0 * cw), _r(top), _r(MARGIN + c1 * cw), _r(top + row_h * 0.8)],
                              "confidence": 1.0})
                ids.append((wid, c0))
            located[start + r] = ids
            if ids:
                current.append([w for w, _ in ids])
            elif current:
                blocks.append(_block(p, len(blocks) + 1, current, words))
                current = []
        if current:
            blocks.append(_block(p, len(blocks) + 1, current, words))
        pages.append({"page": p, "width_pt": PAGE_WIDTH_PT, "height_pt": PAGE_HEIGHT_PT, "rotation": 0, "source": "text", "words": words})
        layout_pages.append({"page": p, "blocks": blocks})
    return {"pages": pages}, {"pages": layout_pages}, located


def _block(page, n, line_ids, words):
    by_id = {w["id"]: w["box"] for w in words}
    boxes = [by_id[i] for line in line_ids for i in line]
    box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
    return {"id": f"p{page}b{n}", "type": "paragraph", "box": box, "lines": list(line_ids)}


def _r(x: float) -> float:
    return round(x, 4)


# ---- fields ----------------------------------------------------------------------------------
def _fields(pairs, lines, located):
    """Each `Name: value` pair, with the words of the value on the first unused line that holds it."""
    used, out = set(), []
    for name, value in pairs[:MAX_FIELDS]:
        if len(value) > MAX_VALUE:
            continue
        evidence = _locate(value, lines, located, used)
        out.append({"name": _field_name(name), "value": value, "confidence": 1.0 if evidence else UNLOCATED_CONFIDENCE,
                    "evidence": evidence, "engine": "plain-text"})
    return out


def _locate(value, lines, located, used):
    for i, (line, _row) in enumerate(lines):
        if i in used:
            continue
        head, sep, tail = line.partition(":")
        if sep and tail.strip() == value:
            used.add(i)
            colon = len(head)
            return [wid for wid, col in located[i] if col > colon]
    return []


def _field_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_") or "field"
    if not n[0].isalpha():
        n = "f_" + n
    return n[:64]


# ---- small helpers -----------------------------------------------------------------------------
def _title(subject: str, filename: str) -> str:
    title = _CONTROL.sub(" ", subject).strip()
    if not title:
        stem = _safe_name(filename).rsplit(".", 1)[0] if filename.strip() else ""
        title = stem if stem and stem != "document" else "Untitled document"
    return title[:200]


def _safe_name(filename: str) -> str:
    """A file name that is safe in a folder and in a bucket: one plain segment, with its extension."""
    base = _CONTROL.sub("", filename or "").replace("\\", "/").split("/")[-1]
    base = _FILE_BAD.sub("_", base).lstrip("._ -+,=@()")
    stem, dot, ext = base.rpartition(".")
    if not dot:
        stem, ext = base, ""
    stem = stem.rstrip(" .")
    ext = ext[:16]
    stem = stem[:max(1, 120 - len(ext) - 1)]
    if not stem:
        return "document" + ("." + ext if ext else ".txt")
    return stem + ("." + ext if ext else "")


def _utc(stamp: str) -> str:
    """ISO 8601 in UTC ending in Z, as the manifest requires. Raises ValueError for anything else."""
    t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("a time with no zone")
    t = t.astimezone(timezone.utc)
    base = t.strftime("%Y-%m-%dT%H:%M:%S")
    return base + (f".{t.microsecond:06d}".rstrip("0") if t.microsecond else "") + "Z"


def _json(obj) -> bytes:
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
