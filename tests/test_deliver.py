import unittest

from smpldoc.domain.deliver import ForwardError, build_outgoing
from smpldoc.domain.models import Attachment

JOB = dict(job_id="J1", sender="Billing <b@vendor.test>", subject="March Invoice", recipient="acme@in.test", received="2026-11-21T08:00:00")


def build(**kw):
    args = dict(JOB, label="Send to accounts", to="ap@example.com", attachments=[Attachment("inv.pdf", "application/pdf", b"%PDF")],
                values=[("total", "9.50")], body="Please pay.", max_bytes=1000, max_files=3)
    args.update(kw)
    return build_outgoing(**args)


class BuildOutgoingTest(unittest.TestCase):
    def test_the_message_names_the_job_files_values_and_original_text(self):
        m = build()
        self.assertEqual((m.to, m.subject), ("ap@example.com", "March Invoice"))
        for needle in ("Send to accounts", "Job ID: J1", "From: Billing <b@vendor.test>", "inv.pdf", "total: 9.50", "Please pay."):
            self.assertIn(needle, m.text)
        self.assertEqual(m.attachments[0].data, b"%PDF")

    def test_no_subject_gets_a_placeholder(self):
        self.assertEqual(build(subject="  ").subject, "(no subject)")

    def test_control_characters_cannot_inject_headers_or_escape_codes(self):
        m = build(subject="Hi\r\nBcc: evil@x.test", sender="a@b.test\r\nX: y", label="L\r\nM")
        self.assertNotIn("\n", m.subject)
        self.assertNotIn("\r", m.subject)
        self.assertNotIn("\r\nBcc", m.text)

    def test_the_body_and_value_lists_are_capped(self):
        m = build(body="y" * 50_000, values=[(f"k{i}", "v") for i in range(500)])
        self.assertLess(len(m.text), 30_000)

    def test_too_many_bytes_or_files_is_a_permanent_error(self):
        with self.assertRaises(ForwardError):
            build(attachments=[Attachment("a", "x/y", b"x" * 1001)])
        with self.assertRaises(ForwardError):
            build(attachments=[Attachment(f"a{i}", "x/y", b"x") for i in range(4)])

    def test_a_bad_destination_is_refused(self):
        for bad in ("", "no-at-sign", "a@b", "a b@c.test", "a@b.test\r\nBcc: x@y.test", "<a@b.test>"):
            with self.assertRaises(ForwardError, msg=bad):
                build(to=bad)


if __name__ == "__main__":
    unittest.main()
