import unittest

from smpldoc.adapters.aws_creds import Credentials
from smpldoc.adapters.s3_inbox import S3Error, S3Inbox, endpoint_for
from tests.contracts import MailInContract, RAW
from tests.fake_s3 import ACCESS, REGION, SECRET, FakeS3

AUTH = {
    "pass": "amazonses.com; spf=pass (spfCheck: domain of x.test designates 1.2.3.4) smtp.mailfrom=s@x.test; dkim=pass header.i=@x.test; dmarc=pass",
    "fail": "amazonses.com; spf=fail smtp.mailfrom=s@x.test; dkim=fail header.i=@x.test",
    "unknown": "amazonses.com; spf=none smtp.mailfrom=s@x.test; dkim=none",
}


def ses_object(raw, sender="s@x.test", verdict="pass", auth=None):
    """What SES writes to S3: the raw message with the headers SES adds on top."""
    return f"Return-Path: <{sender}>\r\nAuthentication-Results: {auth or AUTH[verdict]}\r\n".encode() + raw


class Static:
    def __init__(self, secret=SECRET):
        self.secret = secret

    def get(self):
        return Credentials(ACCESS, self.secret, None, None)


def inbox(s3, **kw):
    args = dict(bucket="mail", region=REGION, credentials=Static(), endpoint=s3.url, domain="in.test")
    args.update(kw)
    return S3Inbox(**args)


class S3InboxContractTest(MailInContract, unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        self.addCleanup(self.s3.close)
        self.mail = inbox(self.s3)
        self.n = 0

    def deliver(self, raw=RAW, sender="s@x.test", recipient="acme@in.test", verdict="pass"):
        stored = ses_object(raw, sender, verdict)
        self.n += 1
        self.s3.put(f"inbox/{recipient.split('@')[0]}/msg{self.n:04d}", stored)
        return stored


class S3InboxBehaviourTest(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        self.addCleanup(self.s3.close)
        self.mail = inbox(self.s3)

    def test_only_the_topmost_authentication_results_from_ses_counts(self):
        forged_below = ses_object(b"\r\nbody", auth=AUTH["fail"]).replace(b"\r\n\r\nbody", b"\r\nAuthentication-Results: amazonses.com; dkim=pass\r\n\r\nbody")
        self.s3.put("inbox/acme/a", forged_below)
        self.s3.put("inbox/acme/b", f"Authentication-Results: mx.evil.example; dkim=pass; spf=pass\r\nReturn-Path: <s@x.test>\r\n\r\nx".encode())
        self.s3.put("inbox/acme/c", b"Return-Path: <s@x.test>\r\nSubject: dkim=pass spf=pass\r\n\r\nAuthentication-Results: amazonses.com; dkim=pass")
        got = {m.id: m.verdict for m in self.mail.poll(10)}
        self.assertEqual(got, {"inbox/acme/a": "fail", "inbox/acme/b": "unknown", "inbox/acme/c": "unknown"})

    def test_a_different_authserv_id_can_be_configured(self):
        self.s3.put("inbox/acme/a", f"Authentication-Results: mx.mine.example; dkim=pass\r\n\r\nx".encode())
        self.assertEqual(inbox(self.s3, authserv_id="mx.mine.example").poll(1)[0].verdict, "pass")

    def test_the_sender_is_the_envelope_return_path_not_a_header_the_sender_wrote(self):
        self.s3.put("inbox/acme/a", b"Return-Path: <real@x.test>\r\nAuthentication-Results: " + AUTH["pass"].encode() + b"\r\nFrom: ceo@bank.test\r\n\r\nx")
        self.assertEqual(self.mail.poll(1)[0].sender, "real@x.test")

    def test_an_oversize_object_is_quarantined_and_never_handed_out(self):
        small = inbox(self.s3, max_bytes=500)
        self.s3.put("inbox/acme/big", ses_object(b"x" * 600))
        self.s3.put("inbox/acme/ok", ses_object(b"x" * 10))
        self.assertEqual([m.id for m in small.poll(10)], ["inbox/acme/ok"])
        self.assertIn("quarantine/acme/big", self.s3.objects)
        self.assertNotIn("inbox/acme/big", self.s3.objects)

    def test_mail_with_no_mailbox_folder_is_quarantined_unless_a_default_is_set(self):
        self.s3.put("inbox/loose.eml", ses_object(b"x"))
        self.assertEqual(self.mail.poll(10), [])
        self.assertIn("quarantine/loose.eml", self.s3.objects)
        self.s3.put("inbox/loose2.eml", ses_object(b"x"))
        got = inbox(self.s3, default_slug="acme").poll(10)
        self.assertEqual([m.recipient for m in got], ["acme@in.test"])

    def test_folder_marker_objects_are_ignored(self):
        self.s3.put("inbox/", b"")
        self.s3.put("inbox/acme/", b"")
        self.assertEqual(self.mail.poll(10), [])
        self.assertEqual(set(self.s3.objects), {"inbox/", "inbox/acme/"})

    def test_ack_moves_the_object_to_processed_and_nack_leaves_it(self):
        self.s3.put("inbox/acme/a", ses_object(b"one"))
        m = self.mail.poll(1)[0]
        self.mail.nack(m)
        self.assertIn("inbox/acme/a", self.s3.objects)
        m = self.mail.poll(1)[0]
        self.mail.ack(m)
        self.assertNotIn("inbox/acme/a", self.s3.objects)
        self.assertEqual(self.s3.objects["processed/acme/a"], ses_object(b"one"))

    def test_a_restart_hands_unacked_mail_out_again(self):
        self.s3.put("inbox/acme/a", ses_object(b"one"))
        self.assertEqual(len(self.mail.poll(1)), 1)
        self.assertEqual(len(inbox(self.s3).poll(1)), 1)  # a new process knows nothing of the old lease

    def test_an_expired_lease_is_handed_out_again(self):
        now = [1000.0]
        mail = inbox(self.s3, now=lambda: now[0], lease_seconds=60)
        self.s3.put("inbox/acme/a", ses_object(b"one"))
        self.assertEqual(len(mail.poll(1)), 1)
        self.assertEqual(mail.poll(1), [])
        now[0] += 61
        self.assertEqual(len(mail.poll(1)), 1)

    def test_awkward_keys_survive_signing(self):
        key = "inbox/acme/a b+c=d é.eml"
        self.s3.put(key, ses_object(b"hi"))
        m = self.mail.poll(1)[0]
        self.assertEqual(m.id, key)
        self.assertEqual(self.mail.fetch(m), ses_object(b"hi"))
        self.mail.ack(m)
        self.assertIn("processed/acme/a b+c=d é.eml", self.s3.objects)

    def test_every_request_is_signed_and_a_wrong_secret_is_a_clear_error(self):
        self.s3.put("inbox/acme/a", ses_object(b"x"))
        self.mail.poll(1)
        self.assertTrue(all(a.startswith("AWS4-HMAC-SHA256 ") for _, _, a in self.s3.requests))
        with self.assertRaises(S3Error) as ctx:
            inbox(self.s3, credentials=Static("wrong-secret")).poll(1)
        self.assertNotIn("wrong-secret", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_a_list_response_with_entities_is_refused(self):
        evil = '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaa">]><ListBucketResult><Contents><Key>&a;</Key><Size>1</Size></Contents></ListBucketResult>'
        s3 = FakeS3(list_body=evil)
        self.addCleanup(s3.close)
        with self.assertRaises(S3Error):
            inbox(s3).poll(1)

    def test_a_missing_bucket_is_an_error_not_an_empty_inbox(self):
        with self.assertRaises(S3Error):
            inbox(self.s3, bucket="nope").poll(1)

    def test_an_unreachable_endpoint_is_an_error(self):
        with self.assertRaises(S3Error):
            inbox(self.s3, endpoint="http://127.0.0.1:1", timeout=1).poll(1)


class S3InboxSetupTest(unittest.TestCase):
    def test_the_endpoint_must_be_https_except_on_loopback(self):
        with self.assertRaises(ValueError):
            S3Inbox("mail", "us-east-1", Static(), endpoint="http://s3.example.com")
        S3Inbox("mail", "us-east-1", Static(), endpoint="https://s3.example.com")
        S3Inbox("mail", "us-east-1", Static(), endpoint="http://127.0.0.1:9000")

    def test_the_default_endpoint_is_aws_and_dotted_buckets_use_path_style(self):
        self.assertEqual(endpoint_for("mail-bucket", "eu-west-1"), "https://mail-bucket.s3.eu-west-1.amazonaws.com")
        self.assertEqual(endpoint_for("my.mail.bucket", "eu-west-1"), "https://s3.eu-west-1.amazonaws.com/my.mail.bucket")

    def test_prefixes_must_be_plain_folders(self):
        for bad in ("/inbox/", "inbox", "../x/", "a//b/", ""):
            with self.assertRaises(ValueError, msg=bad):
                S3Inbox("mail", "us-east-1", Static(), endpoint="https://s3.example.com", prefix=bad)


if __name__ == "__main__":
    unittest.main()
