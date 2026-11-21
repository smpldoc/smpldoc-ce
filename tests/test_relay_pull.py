import unittest

from smpldoc.adapters.relay_pull import RelayAuthError, RelayError, RelayPull
from tests.contracts import MailInContract, RAW
from tests.fake_relay import FakeRelay


class RelayPullContractTest(MailInContract, unittest.TestCase):
    def setUp(self):
        self.relay = FakeRelay()
        self.addCleanup(self.relay.close)
        self.mail = RelayPull(self.relay.url, "tok")

    def deliver(self, raw=RAW, sender="s@x.test", recipient="acme@in.test", verdict="pass"):
        self.relay.deliver(raw, sender, recipient, verdict)
        return raw

    def test_token_is_sent_as_bearer_on_every_call(self):
        self.deliver()
        m = self.mail.poll(1)[0]
        self.mail.fetch(m)
        self.mail.ack(m)
        self.assertTrue(self.relay.seen)
        self.assertEqual({h for _, _, h in self.relay.seen}, {"Bearer tok"})


class RelayPullSafetyTest(unittest.TestCase):
    def test_plain_http_is_refused_except_loopback(self):
        with self.assertRaises(ValueError):
            RelayPull("http://relay.example.com", "tok")
        with self.assertRaises(ValueError):
            RelayPull("ftp://relay.example.com", "tok")
        RelayPull("https://relay.example.com", "tok")
        RelayPull("http://127.0.0.1:9", "tok")
        RelayPull("http://localhost:9", "tok")

    def test_a_token_is_required(self):
        with self.assertRaises(ValueError):
            RelayPull("https://relay.example.com", "")

    def test_wrong_token_is_an_auth_error(self):
        relay = FakeRelay(token="right")
        self.addCleanup(relay.close)
        with self.assertRaises(RelayAuthError):
            RelayPull(relay.url, "wrong").poll(1)

    def test_redirects_are_never_followed(self):
        target = FakeRelay()
        relay = FakeRelay(redirect_to=target.url + "/v1/messages")
        self.addCleanup(target.close)
        self.addCleanup(relay.close)
        with self.assertRaises(RelayError):
            RelayPull(relay.url, "tok").poll(1)
        self.assertEqual(target.seen, [], "the token must not follow a redirect")

    def test_oversized_message_is_refused(self):
        relay = FakeRelay(raw_pad=2_000_000)
        self.addCleanup(relay.close)
        relay.deliver(RAW, "s@x.test", "acme@in.test", "pass")
        mail = RelayPull(relay.url, "tok", max_bytes=1_000_000)
        with self.assertRaises(RelayError):
            mail.fetch(mail.poll(1)[0])

    def test_unreachable_relay_is_a_relay_error(self):
        with self.assertRaises(RelayError):
            RelayPull("http://127.0.0.1:1", "tok", timeout=1).poll(1)


if __name__ == "__main__":
    unittest.main()
