"""Bundle format: check that a bundle is complete, untampered and well formed.

A bundle is handed in as a mapping of path to bytes, so the same check works for a folder, a
bucket or an archive. The contract is docs/BUNDLE_FORMAT.md; the schemas are in schemas/bundle/.
"""
import functools
import hashlib
import json
import re
from pathlib import Path
from typing import Mapping

from .schema_check import check

FORMAT = "smpldoc.bundle"
VERSION = "1.0"
CARD_MAX_BYTES = 2048
DERIVED = ("text.json", "layout.json", "fields.json", "card.json")
FOLDERS = ("pages/", "history/")
_SCHEMAS = Path(__file__).resolve().parent / "schemas" / "bundle"
_VERSION = re.compile(r"([0-9]+)\.([0-9]+)")
_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._ ()+,=@-]{0,127}")


@functools.cache
def schema(name: str) -> dict:
    return json.loads((_SCHEMAS / VERSION / f"{name}.schema.json").read_text(encoding="utf-8"))


class _Errors(list):
    def add(self, message):
        if message not in self:
            self.append(message)

    def schema(self, name, problems):
        for p in problems:
            self.add(f"{name}{p}" if p.startswith(":") else f"{name} {p}")
        return not problems


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key}")
        seen[key] = value
    return seen


def _refuse_constant(name):
    raise ValueError(f"{name} is not JSON")


def _parse(data: bytes):
    """Strict JSON: UTF-8, no duplicate keys, no NaN or Infinity."""
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_refuse_constant)
    except (UnicodeDecodeError, ValueError):
        return None


def safe_path(path: str) -> bool:
    """Relative, forward slashes, no empty, '.' or '..' segments, and plain characters only."""
    if not path or len(path) > 255:
        return False
    return all(_SAFE_SEGMENT.fullmatch(seg) and seg not in (".", "..") for seg in path.split("/"))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate(files: Mapping[str, bytes]) -> list[str]:
    errors = _Errors()
    if "manifest.json" not in files:
        return ["manifest.json: missing"]
    manifest = _parse(files["manifest.json"])
    if manifest is None:
        return ["manifest.json: not valid JSON"]

    version = manifest.get("version") if isinstance(manifest, dict) else None
    m = _VERSION.fullmatch(version) if isinstance(version, str) else None
    if m and m.group(1) != VERSION.split(".")[0]:
        return [f"manifest.json: version {version} needs a newer smpldoc (this one reads {VERSION.split('.')[0]}.x)"]
    lenient = bool(m) and int(m.group(2)) > int(VERSION.split(".")[1])
    if not errors.schema("manifest.json", check(manifest, schema("manifest"), lenient=lenient)):
        return errors

    listed, original = manifest["files"], manifest["original"]
    if not original["path"].startswith("original/"):
        errors.add("manifest.json /original/path: must be under original/")
    if not safe_path(original["path"]):
        errors.add(f"{original['path']}: unsafe path")
    for name in DERIVED:
        if name not in listed:
            errors.add(f"manifest.json: {name} is not listed")
    for name in listed:
        if not safe_path(name):
            errors.add(f"{name}: unsafe path")
        elif name == original["path"]:
            errors.add(f"manifest.json: {name} is the original and cannot be in files")
        elif name not in DERIVED and not name.startswith(FOLDERS):
            errors.add(f"manifest.json: {name} is not a bundle file name")

    for name in files:
        if name == "manifest.json":
            continue
        if not safe_path(name):
            errors.add(f"{name}: unsafe path")
        elif name not in listed and name != original["path"]:
            errors.add(f"{name}: not listed in the manifest")

    for name, digest in listed.items():
        if not safe_path(name):
            continue
        if name not in files:
            errors.add(f"{name}: missing")
        elif _sha(files[name]) != digest:
            errors.add(f"{name}: hash does not match the manifest")
    if original["path"] not in files:
        errors.add(f"{original['path']}: missing")
    else:
        data = files[original["path"]]
        if _sha(data) != original["sha256"]:
            errors.add(f"{original['path']}: hash does not match the manifest")
        if len(data) != original["size"]:
            errors.add(f"{original['path']}: size does not match the manifest")

    docs = {}
    for name in DERIVED:
        if name not in files:
            continue
        doc = _parse(files[name])
        if doc is None:
            errors.add(f"{name}: not valid JSON")
        elif errors.schema(name, check(doc, schema(name.removesuffix(".json")), lenient=lenient)):
            docs[name] = doc
    if "card.json" in files and len(files["card.json"]) > CARD_MAX_BYTES:
        errors.add(f"card.json: {len(files['card.json'])} bytes, the limit is {CARD_MAX_BYTES}")
    _cross_check(docs, errors)
    return list(errors)


def _cross_check(docs: dict, errors: _Errors) -> None:
    text, layout, fields, card = (docs.get(n) for n in DERIVED)
    words = None
    if text is not None:
        words = set()
        for i, page in enumerate(text["pages"]):
            if page["page"] != i + 1:
                errors.add(f"text.json /pages/{i}/page: expected {i + 1}")
            for j, word in enumerate(page["words"]):
                wid, (left, top, right, bottom) = word["id"], word["box"]
                if wid in words:
                    errors.add(f"text.json /pages/{i}/words: {wid} is used twice")
                words.add(wid)
                if not wid.startswith(f"p{page['page']}w"):
                    errors.add(f"text.json /pages/{i}/words/{j}: {wid} is not on page {page['page']}")
                if left > right or top > bottom:
                    errors.add(f"text.json /pages/{i}/words/{j}/box: left must not be right of right, top not below bottom")
        if card is not None and card["pages"] != len(text["pages"]):
            errors.add(f"card.json /pages: {card['pages']} but text.json has {len(text['pages'])}")
    if words is not None and layout is not None:
        for i, page in enumerate(layout["pages"]):
            for j, block in enumerate(page["blocks"]):
                used = [w for line in block["lines"] for w in line]
                used += [w for cell in block.get("cells", ()) for line in cell["lines"] for w in line]
                used += block.get("label", [])
                for wid in used:
                    if wid not in words:
                        errors.add(f"layout.json /pages/{i}/blocks/{j}: {wid} is not a word in text.json")
    if words is not None and fields is not None:
        for k, field in enumerate(fields["fields"]):
            for wid in field["evidence"]:
                if wid not in words:
                    errors.add(f"fields.json /fields/{k}/evidence: {wid} is not a word in text.json")
    if card is not None and fields is not None and card["kind"] != fields["kind"]:
        errors.add(f"card.json /kind: {card['kind']} does not match fields.json kind {fields['kind']}")
