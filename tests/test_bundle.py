"""Bundle format v1.0: the example bundle passes, and every way a bundle can be wrong is caught."""
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from smpldoc.domain import bundle
from smpldoc.main import main

EXAMPLES = Path(__file__).resolve().parent / "fixtures" / "bundles"
EXAMPLE = EXAMPLES / "1.0" / "invoice"


def load_dir(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(obj) -> bytes:
    return (json.dumps(obj, indent=2, ensure_ascii=False) + "\n").encode()


class Edit:
    """Change one JSON file of the example bundle and keep the manifest hashes right."""

    def __init__(self):
        self.files = load_dir(EXAMPLE)

    def json(self, name):
        return json.loads(self.files[name])

    def put(self, name, obj, rehash=True):
        self.files[name] = obj if isinstance(obj, bytes) else dump(obj)
        if rehash and name != "manifest.json":
            m = self.json("manifest.json")
            m["files"][name] = sha(self.files[name])
            self.files["manifest.json"] = dump(m)
        return self

    def manifest(self, change):
        m = self.json("manifest.json")
        change(m)
        self.files["manifest.json"] = dump(m)
        return self

    def errors(self):
        return bundle.validate(self.files)


class ExampleBundleTest(unittest.TestCase):
    def test_every_example_bundle_is_valid(self):
        examples = sorted(p.parent for p in EXAMPLES.rglob("manifest.json"))
        self.assertTrue(examples)
        for root in examples:
            self.assertEqual(bundle.validate(load_dir(root)), [], root)

    def test_the_example_holds_no_real_contact_data(self):
        for name, data in load_dir(EXAMPLE).items():
            text = data.decode("latin-1")
            self.assertNotRegex(text, r"@(?!example\.(com|org|net)\b)[A-Za-z0-9-]+\.[A-Za-z]", name)

    def test_the_reader_knows_this_version(self):
        self.assertEqual(bundle.FORMAT, "smpldoc.bundle")
        self.assertEqual(bundle.VERSION, "1.0")


class ManifestTest(unittest.TestCase):
    def test_a_missing_manifest(self):
        e = Edit()
        del e.files["manifest.json"]
        self.assertEqual(e.errors(), ["manifest.json: missing"])

    def test_json_that_does_not_parse_is_an_error_not_a_crash(self):
        e = Edit()
        e.files["manifest.json"] = b"{nope"
        self.assertEqual(e.errors(), ["manifest.json: not valid JSON"])
        e = Edit().put("card.json", b"\xff\xfe", rehash=True)
        self.assertIn("card.json: not valid JSON", e.errors())

    def test_wrong_format(self):
        e = Edit().manifest(lambda m: m.update(format="other"))
        self.assertIn("manifest.json /format: must be 'smpldoc.bundle'", e.errors())

    def test_a_newer_major_version_is_refused(self):
        e = Edit().manifest(lambda m: m.update(version="2.0"))
        self.assertEqual(e.errors(), ["manifest.json: version 2.0 needs a newer smpldoc (this one reads 1.x)"])

    def test_a_newer_minor_version_is_read_and_its_additions_ignored(self):
        e = Edit().manifest(lambda m: m.update(version="1.1", added_in_1_1="x"))
        card = e.json("card.json")
        card["new_field"] = 1
        e.put("card.json", card)
        self.assertEqual(e.errors(), [])

    def test_the_current_version_is_strict_about_unknown_fields(self):
        e = Edit().manifest(lambda m: m.update(extra="x"))
        self.assertEqual(e.errors(), ["manifest.json /extra: unknown property"])

    def test_a_derived_file_that_is_not_listed(self):
        e = Edit().manifest(lambda m: m["files"].pop("layout.json"))
        self.assertIn("manifest.json: layout.json is not listed", e.errors())


class IntegrityTest(unittest.TestCase):
    def test_a_changed_file_fails_its_hash(self):
        e = Edit()
        e.files["text.json"] = e.files["text.json"] + b" "
        self.assertEqual(e.errors(), ["text.json: hash does not match the manifest"])

    def test_a_changed_original_fails(self):
        e = Edit()
        name = e.json("manifest.json")["original"]["path"]
        e.files[name] = e.files[name] + b"x"
        self.assertEqual(sorted(e.errors()), [f"{name}: hash does not match the manifest",
                                               f"{name}: size does not match the manifest"])

    def test_a_listed_file_that_is_missing(self):
        e = Edit()
        del e.files["card.json"]
        self.assertEqual(e.errors(), ["card.json: missing"])

    def test_an_unlisted_extra_file_is_refused(self):
        e = Edit()
        e.files["notes.txt"] = b"hello"
        self.assertEqual(e.errors(), ["notes.txt: not listed in the manifest"])

    def test_unsafe_paths_are_refused(self):
        for bad in ("../escape.json", "/etc/passwd", "original/../manifest.json", "original\\x.pdf",
                    "pages//1.png", "./card.json", "original/"):
            e = Edit()
            e.files[bad] = b"x"
            e.manifest(lambda m, bad=bad: m["files"].__setitem__(bad, sha(b"x")))
            self.assertTrue(any(bad in err and "unsafe path" in err for err in e.errors()), (bad, e.errors()))

    def test_the_original_must_live_under_original(self):
        e = Edit()
        data = e.files.pop("original/invoice-4471.pdf")
        e.files["invoice-4471.pdf"] = data
        e.manifest(lambda m: m["original"].update(path="invoice-4471.pdf"))
        self.assertIn("manifest.json /original/path: must be under original/", e.errors())

    def test_the_original_cannot_also_be_a_derived_file(self):
        e = Edit()
        e.manifest(lambda m: m["files"].__setitem__("original/invoice-4471.pdf", m["original"]["sha256"]))
        self.assertIn("manifest.json: original/invoice-4471.pdf is the original and cannot be in files", e.errors())

    def test_history_and_page_files_are_allowed_when_listed(self):
        e = Edit()
        e.files["history/1.0/card.json"] = e.files["card.json"]
        e.files["pages/0001.png"] = b"\x89PNG\r\n\x1a\n"
        e.manifest(lambda m: m["files"].update({"history/1.0/card.json": sha(e.files["card.json"]),
                                                "pages/0001.png": sha(b"\x89PNG\r\n\x1a\n")}))
        self.assertEqual(e.errors(), [])

    def test_files_outside_the_known_folders_are_refused_even_when_listed(self):
        e = Edit()
        e.files["run.sh"] = b"x"
        e.manifest(lambda m: m["files"].__setitem__("run.sh", sha(b"x")))
        self.assertIn("manifest.json: run.sh is not a bundle file name", e.errors())


class ContentTest(unittest.TestCase):
    def test_evidence_must_point_at_real_words(self):
        e = Edit()
        f = e.json("fields.json")
        f["fields"][0]["evidence"] = ["p1w999"]
        e.put("fields.json", f)
        self.assertEqual(e.errors(), ["fields.json /fields/0/evidence: p1w999 is not a word in text.json"])

    def test_layout_must_point_at_real_words(self):
        e = Edit()
        layout = e.json("layout.json")
        layout["pages"][0]["blocks"][0]["lines"][0].append("p9w1")
        e.put("layout.json", layout)
        self.assertEqual(e.errors(), ["layout.json /pages/0/blocks/0: p9w1 is not a word in text.json"])

    def test_word_ids_are_unique_and_match_their_page(self):
        e = Edit()
        text = e.json("text.json")
        words = text["pages"][0]["words"]
        words.append(dict(words[0]))
        e.put("text.json", text)
        self.assertIn(f"text.json /pages/0/words: {words[0]['id']} is used twice", e.errors())
        e = Edit()
        text = e.json("text.json")
        text["pages"][0]["words"][0]["id"] = "p2w1"
        e.put("text.json", text)
        self.assertIn("text.json /pages/0/words/0: p2w1 is not on page 1", e.errors())

    def test_boxes_are_fractions_of_the_page_in_order(self):
        e = Edit()
        text = e.json("text.json")
        text["pages"][0]["words"][0]["box"] = [0.5, 0.1, 0.4, 0.2]
        e.put("text.json", text)
        self.assertIn("text.json /pages/0/words/0/box: left must not be right of right, top not below bottom",
                      e.errors())
        e = Edit()
        text = e.json("text.json")
        text["pages"][0]["words"][0]["box"] = [0.1, 0.1, 1.2, 0.2]
        e.put("text.json", text)
        self.assertIn("text.json /pages/0/words/0/box/2: above 1", e.errors())

    def test_pages_are_numbered_from_one_in_order(self):
        e = Edit()
        text = e.json("text.json")
        text["pages"][0]["page"] = 2
        e.put("text.json", text)
        self.assertIn("text.json /pages/0/page: expected 1", e.errors())

    def test_amounts_are_decimal_strings_never_floats(self):
        e = Edit()
        card = e.json("card.json")
        card["totals"]["amount_due"] = 1234.56
        e.put("card.json", card)
        self.assertIn("card.json /totals/amount_due: expected string", e.errors())

    def test_card_and_fields_agree_on_the_kind(self):
        e = Edit()
        card = e.json("card.json")
        card["kind"] = "receipt"
        e.put("card.json", card)
        self.assertEqual(e.errors(), ["card.json /kind: receipt does not match fields.json kind invoice"])

    def test_card_kind_and_category_come_from_the_lists(self):
        e = Edit()
        card = e.json("card.json")
        card["category"] = "secret"
        e.put("card.json", card)
        self.assertTrue(any(err.startswith("card.json /category: must be one of") for err in e.errors()))

    def test_the_card_stays_small(self):
        e = Edit()
        card = e.json("card.json")
        card["tags"] = [f"t{i:02d}-" + "x" * 30 for i in range(20)]
        card["parties"] = ["p" * 200] * 10
        e.put("card.json", card)
        self.assertIn(f"card.json: {len(e.files['card.json'])} bytes, the limit is {bundle.CARD_MAX_BYTES}",
                      e.errors())


class CliTest(unittest.TestCase):
    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = main(["bundle-validate", *args], env={}, out=out, err=err)
        return code, out.getvalue(), err.getvalue()

    def copy_example(self, root):
        for name, data in load_dir(EXAMPLE).items():
            path = Path(root, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def test_a_good_bundle(self):
        self.assertEqual(self.run_cli(str(EXAMPLE)), (0, "bundle ok: smpldoc.bundle 1.0, invoice\n", ""))

    def test_a_broken_bundle_lists_its_problems(self):
        with tempfile.TemporaryDirectory() as d:
            self.copy_example(d)
            Path(d, "notes.txt").write_text("x")
            code, out, err = self.run_cli(d)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("notes.txt: not listed in the manifest", err)

    def test_usage_and_missing_folders(self):
        self.assertEqual(self.run_cli()[0], 2)
        code, _, err = self.run_cli("/nonexistent/bundle")
        self.assertEqual(code, 1)
        self.assertIn("not a folder", err)

    def test_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as outside:
            self.copy_example(d)
            Path(outside, "secret").write_text("s")
            os.symlink(Path(outside, "secret"), Path(d, "pages"))
            code, _, err = self.run_cli(d)
        self.assertEqual(code, 1)
        self.assertIn("pages: a link, not a file", err)

    def test_needs_no_configuration(self):
        self.assertEqual(self.run_cli(str(EXAMPLE))[0], 0)  # env={} above: no relay, no data dir


if __name__ == "__main__":
    unittest.main()
