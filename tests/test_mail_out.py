import smtplib
import ssl
import unittest

from smpldoc.adapters.memory import MemoryMailOut
from smpldoc.adapters.smtp_out import SmtpMailOut
from smpldoc.domain.errors import SendError
from smpldoc.domain.models import Attachment, OutgoingMail
from tests.fake_smtp import FakeSmtp

MAIL = OutgoingMail("ap@example.com", "March Invoice", "Hello\n", (Attachment("inv.pdf", "application/pdf", b"%PDF-1.4\x00\xff"),))


class MailOutContract:
    def make(self):
        raise NotImplementedError

    def test_send_returns_a_message_id_and_each_is_different(self):
        out = self.make()
        a, b = out.send(MAIL), out.send(MAIL)
        self.assertTrue(a and b and a != b)


class MemoryMailOutTest(MailOutContract, unittest.TestCase):
    def make(self):
        return MemoryMailOut()

    def test_it_records_and_can_be_told_to_fail(self):
        out = MemoryMailOut()
        out.send(MAIL)
        self.assertEqual(out.sent, [MAIL])
        out.fail_times = 1
        with self.assertRaises(SendError):
            out.send(MAIL)
        out.send(MAIL)


class SmtpMailOutTest(MailOutContract, unittest.TestCase):
    def setUp(self):
        self.smtp = FakeSmtp()
        self.addCleanup(self.smtp.close)

    def make(self, **kw):
        args = dict(host="127.0.0.1", port=self.smtp.port, sender="smpldoc@example.com", security="none", timeout=5)
        args.update(kw)
        return SmtpMailOut(**args)

    def test_the_message_arrives_whole(self):
        mid = self.make().send(MAIL)
        sender, rcpts, msg = self.smtp.messages[0]
        self.assertIn("smpldoc@example.com", sender)
        self.assertIn("ap@example.com", rcpts[0])
        self.assertEqual((msg["Subject"], msg["To"], msg["From"], msg["Message-ID"]), ("March Invoice", "ap@example.com", "smpldoc@example.com", mid))
        parts = list(msg.walk())
        self.assertEqual(parts[1].get_content_type(), "text/plain")
        att = parts[2]
        self.assertEqual((att.get_filename(), att.get_content_type(), att.get_payload(decode=True)), ("inv.pdf", "application/pdf", b"%PDF-1.4\x00\xff"))

    def test_a_header_injection_attempt_is_refused_not_sent(self):
        bad = OutgoingMail("ap@example.com", "Hi\r\nBcc: evil@x.test", "t", ())
        with self.assertRaises(SendError) as ctx:
            self.make().send(bad)
        self.assertTrue(ctx.exception.permanent)
        self.assertEqual(self.smtp.messages, [])

    def test_a_refused_recipient_is_permanent_and_a_busy_server_is_not(self):
        self.smtp.rcpt_reply = "550 5.1.1 no such user"
        with self.assertRaises(SendError) as ctx:
            self.make().send(MAIL)
        self.assertTrue(ctx.exception.permanent)
        self.smtp.rcpt_reply = "451 4.3.0 try later"
        with self.assertRaises(SendError) as ctx:
            self.make().send(MAIL)
        self.assertFalse(ctx.exception.permanent)

    def test_an_unreachable_server_is_a_transient_failure(self):
        with self.assertRaises(SendError) as ctx:
            self.make(port=1, timeout=1).send(MAIL)
        self.assertFalse(ctx.exception.permanent)

    def test_plain_text_is_only_allowed_on_loopback(self):
        with self.assertRaises(ValueError):
            SmtpMailOut("smtp.example.com", 587, "a@example.com", security="none")
        with self.assertRaises(ValueError):
            SmtpMailOut("smtp.example.com", 587, "a@example.com", security="carrier-pigeon")
        with self.assertRaises(ValueError):
            SmtpMailOut("smtp.example.com", 587, "not an address", security="starttls")
        with self.assertRaises(ValueError):
            SmtpMailOut("smtp.example.com", 587, "a@example.com", security="starttls", username="u")

    def test_starttls_comes_before_the_password_and_the_certificate_is_checked(self):
        calls = []

        class Double:
            def __init__(self, host, port, timeout=None, **kw):
                calls.append(("connect", host, port))

            def ehlo(self): calls.append(("ehlo",)); return (250, b"")
            def starttls(self, context=None):
                calls.append(("starttls", context.verify_mode, context.check_hostname)); return (220, b"")
            def login(self, u, p): calls.append(("login", u, p)); return (235, b"")
            def send_message(self, m, **kw): calls.append(("send",)); return {}
            def quit(self): calls.append(("quit",))

        out = SmtpMailOut("smtp.example.com", 587, "a@example.com", security="starttls", username="u", password="s3cret", smtp_factory=Double)
        out.send(MAIL)
        names = [c[0] for c in calls]
        self.assertLess(names.index("starttls"), names.index("login"))
        self.assertLess(names.index("login"), names.index("send"))
        self.assertEqual(calls[names.index("starttls")][1:], (ssl.CERT_REQUIRED, True))

    def test_the_password_never_appears_in_an_error(self):
        class Boom:
            def __init__(self, *a, **k): pass
            def ehlo(self): return (250, b"")
            def starttls(self, context=None): return (220, b"")
            def login(self, u, p): raise smtplib.SMTPAuthenticationError(535, b"bad credentials s3cret")
            def quit(self): pass

        out = SmtpMailOut("smtp.example.com", 587, "a@example.com", security="starttls", username="u", password="s3cret", smtp_factory=Boom)
        with self.assertRaises(SendError) as ctx:
            out.send(MAIL)
        self.assertNotIn("s3cret", str(ctx.exception))
        self.assertTrue(ctx.exception.permanent)  # wrong credentials will not fix themselves


if __name__ == "__main__":
    unittest.main()
