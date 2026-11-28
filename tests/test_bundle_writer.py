"""The bundle writer turns a document it can read into a v1.0 bundle. Every bundle it writes must
pass the validator, so these tests check the output with the same code anyone can run."""
import json
import unittest

from smpldoc.domain import bundle, bundle_writer as bw

BID, JID = "019ac8f0c4000000000000000000b001", "019ac8f0c4000000000000000000a001"
TEXT = "Example Supply Co\nInvoice: 4471\nDue date: 2026-12-28\n\nThanks for your business.\n"


def build(data=TEXT, pairs=(("invoice", "4471"), ("due_date", "2026-12-28")), **kw):
    args = dict(company="acme", bundle_id=BID, job_id=JID, created_at="2026-12-01T09:30:00.123+00:00",
                sender="scanner@example.com", subject="Scan", filename="invoice.txt", content_type="text/plain",
                data=data.encode() if isinstance(data, str) else data, pairs=list(pairs))
    args.update(kw)
    return bw.build(**args)


def doc(files, name):
    return json.loads(files[name])


class WrittenBundleIsValidTest(unittest.TestCase):
    def test_a_text_document_makes_a_valid_bundle(self):
        files = build()
        self.assertEqual(bundle.validate(files), [])
        self.assertEqual(set(files), {"manifest.json", "original/invoice.txt", "text.json", "layout.json", "fields.json", "card.json"})

    def test_the_original_is_stored_exactly_as_received(self):
        raw = "Zoë: ünï\r\nsecond line\r\n".encode()
        files = build(data=raw, pairs=[])
        self.assertEqual(files["original/invoice.txt"], raw)
        self.assertEqual(bundle.validate(files), [])

    def test_the_same_input_gives_the_same_bytes(self):
        self.assertEqual(build(), build())

    def test_manifest_says_where_it_came_from_in_utc(self):
        m = doc(build(), "manifest.json")
        self.assertEqual((m["bundle_id"], m["job_id"], m["company"]), (BID, JID, "acme"))
        self.assertEqual(m["created_at"], "2026-12-01T09:30:00.123Z")
        self.assertEqual(m["source"], {"kind": "mail", "sender": "scanner@example.com", "subject": "Scan",
                                       "received_at": "2026-12-01T09:30:00.123Z"})
        self.assertEqual(m["upgraded_from"], [])
        self.assertEqual({e["step"] for e in m["engines"]}, {"layout", "fields", "card"})

    def test_times_with_an_offset_are_converted_to_utc(self):
        m = doc(build(created_at="2026-12-01T10:30:00+01:00"), "manifest.json")
        self.assertEqual(m["created_at"], "2026-12-01T09:30:00Z")


class TextAndPositionsTest(unittest.TestCase):
    def test_every_word_has_a_box_inside_the_page_in_reading_order(self):
        text = doc(build(), "text.json")
        words = [w for p in text["pages"] for w in p["words"]]
        self.assertEqual([w["text"] for w in words][:3], ["Example", "Supply", "Co"])
        for w in words:
            left, top, right, bottom = w["box"]
            self.assertTrue(0 <= left < right <= 1 and 0 <= top < bottom <= 1, w)
            self.assertEqual(w["confidence"], 1.0)
        tops = [w["box"][1] for w in words]
        self.assertEqual(tops, sorted(tops))
        self.assertEqual(text["pages"][0]["source"], "text")

    def test_word_ids_are_per_page_and_unique(self):
        files = build("\n".join(f"line {i}" for i in range(130)), pairs=[])
        text = doc(files, "text.json")
        self.assertEqual(len(text["pages"]), 3)
        self.assertEqual([p["page"] for p in text["pages"]], [1, 2, 3])
        ids = [w["id"] for p in text["pages"] for w in p["words"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(text["pages"][1]["words"][0]["id"].startswith("p2w"))
        self.assertEqual(doc(files, "card.json")["pages"], 3)
        self.assertEqual(bundle.validate(files), [])

    def test_a_very_long_line_stays_inside_the_page(self):
        files = build("word " * 400, pairs=[])
        self.assertTrue(all(w["box"][2] <= 1 for w in doc(files, "text.json")["pages"][0]["words"]))
        self.assertEqual(bundle.validate(files), [])

    def test_a_token_longer_than_the_limit_is_split_not_dropped(self):
        files = build("x" * 2500, pairs=[])
        words = doc(files, "text.json")["pages"][0]["words"]
        self.assertEqual([len(w["text"]) for w in words], [1000, 1000, 500])
        self.assertEqual(bundle.validate(files), [])

    def test_line_endings_tabs_and_blank_lines_are_handled(self):
        files = build("a\tb\r\n\r\n\r\nc\r\n", pairs=[])
        self.assertEqual([w["text"] for w in doc(files, "text.json")["pages"][0]["words"]], ["a", "b", "c"])
        self.assertEqual(bundle.validate(files), [])


class LayoutTest(unittest.TestCase):
    def test_blank_lines_separate_paragraph_blocks(self):
        layout = doc(build(), "layout.json")
        blocks = layout["pages"][0]["blocks"]
        self.assertEqual([b["id"] for b in blocks], ["p1b1", "p1b2"])
        self.assertEqual([b["type"] for b in blocks], ["paragraph", "paragraph"])
        self.assertEqual(len(blocks[0]["lines"]), 3)
        self.assertEqual(len(blocks[1]["lines"]), 1)

    def test_a_blocks_box_covers_its_words(self):
        files = build()
        words = {w["id"]: w["box"] for w in doc(files, "text.json")["pages"][0]["words"]}
        for block in doc(files, "layout.json")["pages"][0]["blocks"]:
            ids = [i for line in block["lines"] for i in line]
            self.assertEqual(block["box"][0], min(words[i][0] for i in ids))
            self.assertEqual(block["box"][3], max(words[i][3] for i in ids))


class FieldsAndCardTest(unittest.TestCase):
    def test_a_field_points_at_the_words_it_was_read_from(self):
        files = build()
        words = {w["id"]: w["text"] for w in doc(files, "text.json")["pages"][0]["words"]}
        fields = {f["name"]: f for f in doc(files, "fields.json")["fields"]}
        self.assertEqual([words[i] for i in fields["invoice"]["evidence"]], ["4471"])
        self.assertEqual([words[i] for i in fields["due_date"]["evidence"]], ["2026-12-28"])
        self.assertEqual((fields["invoice"]["confidence"], fields["invoice"]["engine"]), (1.0, "plain-text"))

    def test_two_fields_with_the_same_value_use_different_lines(self):
        files = build("a: 5\nb: 5\n", pairs=[("a", "5"), ("b", "5")])
        ev = [f["evidence"] for f in doc(files, "fields.json")["fields"]]
        self.assertEqual(len({tuple(e) for e in ev}), 2)

    def test_a_value_that_cannot_be_found_is_kept_with_no_evidence(self):
        files = build(pairs=[("note", "nowhere in the text")])
        f = doc(files, "fields.json")["fields"][0]
        self.assertEqual((f["value"], f["evidence"], f["confidence"]), ("nowhere in the text", [], 0.5))
        self.assertEqual(bundle.validate(files), [])

    def test_field_names_are_made_to_fit_the_format(self):
        files = build("2nd total: 9\n", pairs=[("2nd_total", "9"), ("n" * 90, "x")])
        names = [f["name"] for f in doc(files, "fields.json")["fields"]]
        self.assertEqual(names[0], "f_2nd_total")
        self.assertEqual(len(names[1]), 64)
        self.assertEqual(bundle.validate(files), [])

    def test_the_card_is_an_honest_unknown_until_cards_are_built(self):
        files = build()
        card = doc(files, "card.json")
        self.assertEqual((card["kind"], card["category"], card["language"]), ("document", "other", "und"))
        self.assertEqual(doc(files, "fields.json")["kind"], "document")
        self.assertEqual(card["title"], "Scan")
        self.assertLessEqual(len(files["card.json"]), bundle.CARD_MAX_BYTES)

    def test_title_falls_back_to_the_file_name_then_a_default_and_is_clean(self):
        self.assertEqual(doc(build(subject=""), "card.json")["title"], "invoice")
        self.assertEqual(doc(build(subject="", filename=""), "card.json")["title"], "Untitled document")
        self.assertEqual(doc(build(subject="a\x00b\nc"), "card.json")["title"], "a b c")
        self.assertEqual(len(doc(build(subject="s" * 900), "card.json")["title"]), 200)

    def test_sender_and_subject_are_capped_to_the_manifest_limits(self):
        m = doc(build(sender="s" * 400, subject="t" * 2000), "manifest.json")
        self.assertEqual((len(m["source"]["sender"]), len(m["source"]["subject"])), (320, 998))


class OriginalNameTest(unittest.TestCase):
    def test_a_hostile_file_name_cannot_escape_the_original_folder(self):
        for name in ("../../etc/passwd", "..\\..\\boot.ini", "/abs/path.txt", ".hidden", "a\x00b.txt", "é ü.txt", "x" * 400 + ".txt", "", "...", " "):
            files = build(filename=name, pairs=[])
            originals = [p for p in files if p.startswith("original/")]
            self.assertEqual(len(originals), 1, name)
            self.assertTrue(bundle.safe_path(originals[0]), (name, originals))
            self.assertEqual(bundle.validate(files), [], name)

    def test_the_extension_survives(self):
        self.assertIn("original/scan-1.txt", build(filename="scan-1.txt"))
        self.assertTrue(next(p for p in build(filename="x" * 400 + ".txt") if p.startswith("original/")).endswith(".txt"))


class SkipReasonTest(unittest.TestCase):
    def test_only_plain_text_with_words_is_readable_today(self):
        self.assertEqual(bw.skip_reason("text/plain", b"hello"), "")
        self.assertEqual(bw.skip_reason("text/plain; charset=utf-8", b"hello"), "")
        self.assertEqual(bw.skip_reason("TEXT/PLAIN", b"hello"), "")
        self.assertEqual(bw.skip_reason("application/pdf", b"%PDF-1.4"), "not-readable-yet")
        self.assertEqual(bw.skip_reason("image/png", b"\x89PNG"), "not-readable-yet")
        self.assertEqual(bw.skip_reason("text/csv", b"a,b"), "not-readable-yet")
        self.assertEqual(bw.skip_reason("text/plain", b""), "empty")
        self.assertEqual(bw.skip_reason("text/plain", b" \n\t\r\n "), "empty")
        self.assertEqual(bw.skip_reason("text/plain", b"x" * (bw.MAX_TEXT_BYTES + 1)), "too-large")

    def test_build_returns_nothing_for_what_it_cannot_read(self):
        self.assertIsNone(build(content_type="application/pdf", data=b"%PDF"))
        self.assertIsNone(build(data=b""))


if __name__ == "__main__":
    unittest.main()
