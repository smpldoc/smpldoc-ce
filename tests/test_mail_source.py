import unittest

from smpldoc.adapters.relay_pull import RelayPull
from smpldoc.adapters.s3_inbox import S3Inbox
from smpldoc.config import load
from smpldoc.mail_source import build_mail_in


class BuildMailInTest(unittest.TestCase):
    def test_relay(self):
        c = load({"SMPLDOC_RELAY_URL": "https://relay.example.com", "SMPLDOC_RELAY_TOKEN": "t"})
        self.assertIsInstance(build_mail_in(c, {}), RelayPull)

    def test_s3_uses_the_environment_for_credentials(self):
        c = load({"SMPLDOC_MAIL_SOURCE": "s3", "SMPLDOC_S3_BUCKET": "my-mail", "SMPLDOC_S3_REGION": "eu-west-1"})
        mail = build_mail_in(c, {"AWS_ACCESS_KEY_ID": "A", "AWS_SECRET_ACCESS_KEY": "s"})
        self.assertIsInstance(mail, S3Inbox)
        self.assertEqual(mail.credentials.get().access_key, "A")


if __name__ == "__main__":
    unittest.main()
