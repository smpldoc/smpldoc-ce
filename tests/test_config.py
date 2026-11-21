import os
import tempfile
import unittest

from smpldoc.config import Config, ConfigError, load

BASE = {"SMPLDOC_RELAY_URL": "https://relay.example.com", "SMPLDOC_RELAY_TOKEN": "s3cret-token"}


class ConfigTest(unittest.TestCase):
    def test_defaults_are_closed(self):
        c = load(BASE)
        self.assertEqual((c.bind, c.port, c.data_dir, c.poll_seconds, c.batch), ("127.0.0.1", 8080, "/data", 30.0, 10))

    def test_token_from_file_strips_the_newline(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t")
            with open(path, "w") as f:
                f.write("filetoken\n")
            env = {"SMPLDOC_RELAY_URL": BASE["SMPLDOC_RELAY_URL"], "SMPLDOC_RELAY_TOKEN_FILE": path}
            self.assertEqual(load(env).relay_token, "filetoken")

    def test_token_and_token_file_together_are_refused(self):
        with self.assertRaises(ConfigError):
            load({**BASE, "SMPLDOC_RELAY_TOKEN_FILE": "/x"})

    def test_missing_or_empty_token_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            empty = os.path.join(d, "e")
            with open(empty, "w") as f:
                f.write("\n")
            for path in ("/nope/missing", empty):
                with self.assertRaises(ConfigError):
                    load({"SMPLDOC_RELAY_URL": BASE["SMPLDOC_RELAY_URL"], "SMPLDOC_RELAY_TOKEN_FILE": path})

    def test_relay_is_required_for_running(self):
        with self.assertRaises(ConfigError):
            load({})
        self.assertIsNone(load({}, need_relay=False).relay_url)

    def test_a_typo_in_a_setting_name_is_an_error(self):
        with self.assertRaises(ConfigError):
            load({**BASE, "SMPLDOC_BIN": "0.0.0.0"})

    def test_bad_values_are_refused(self):
        for key, bad in (("SMPLDOC_PORT", "0"), ("SMPLDOC_PORT", "x"), ("SMPLDOC_POLL_SECONDS", "0"),
                         ("SMPLDOC_POLL_SECONDS", "99999"), ("SMPLDOC_BATCH", "101"), ("SMPLDOC_BIND", "")):
            with self.assertRaises(ConfigError, msg=f"{key}={bad}"):
                load({**BASE, key: bad})

    def test_the_token_never_appears_in_errors_or_repr(self):
        self.assertNotIn("s3cret-token", repr(load(BASE)))
        try:
            load({**BASE, "SMPLDOC_PORT": "nope"})
        except ConfigError as e:
            self.assertNotIn("s3cret-token", str(e))

    def test_relay_url_is_validated_early(self):
        with self.assertRaises(ConfigError):
            load({**BASE, "SMPLDOC_RELAY_URL": "http://relay.example.com"})


S3 = {"SMPLDOC_MAIL_SOURCE": "s3", "SMPLDOC_S3_BUCKET": "my-mail", "SMPLDOC_S3_REGION": "eu-west-1"}


class MailSourceConfigTest(unittest.TestCase):
    def test_s3_needs_no_relay_and_has_safe_defaults(self):
        c = load(S3)
        self.assertEqual((c.mail_source, c.s3_bucket, c.s3_region, c.s3_prefix), ("s3", "my-mail", "eu-west-1", "inbox/"))
        self.assertEqual((c.s3_endpoint, c.s3_authserv_id, c.mail_domain, c.max_message_bytes), (None, "amazonses.com", "mail.invalid", 25_000_000))
        self.assertIsNone(c.relay_url)

    def test_the_source_is_inferred_when_only_one_is_configured(self):
        self.assertEqual(load({k: v for k, v in S3.items() if k != "SMPLDOC_MAIL_SOURCE"}).mail_source, "s3")
        self.assertEqual(load(BASE).mail_source, "relay")

    def test_two_sources_without_a_choice_is_an_error(self):
        with self.assertRaises(ConfigError):
            load({**BASE, **{k: v for k, v in S3.items() if k != "SMPLDOC_MAIL_SOURCE"}})
        self.assertEqual(load({**BASE, **S3, "SMPLDOC_MAIL_SOURCE": "relay"}).mail_source, "relay")

    def test_s3_settings_are_validated(self):
        bad = [("SMPLDOC_S3_BUCKET", "UPPER"), ("SMPLDOC_S3_BUCKET", "a"), ("SMPLDOC_S3_BUCKET", "has space"),
               ("SMPLDOC_S3_REGION", "mars"), ("SMPLDOC_S3_REGION", "../x"), ("SMPLDOC_S3_PREFIX", "/inbox/"),
               ("SMPLDOC_S3_PREFIX", "inbox"), ("SMPLDOC_S3_PREFIX", "a/../b/"), ("SMPLDOC_S3_ENDPOINT", "http://s3.example.com"),
               ("SMPLDOC_MAIL_DOMAIN", "not a domain"), ("SMPLDOC_MAX_MESSAGE_BYTES", "0"), ("SMPLDOC_MAIL_SOURCE", "ftp")]
        for key, value in bad:
            with self.assertRaises(ConfigError, msg=f"{key}={value}"):
                load({**S3, key: value})
        with self.assertRaises(ConfigError):
            load({k: v for k, v in S3.items() if k != "SMPLDOC_S3_BUCKET"})

    def test_a_local_s3_compatible_server_is_allowed_on_loopback(self):
        self.assertEqual(load({**S3, "SMPLDOC_S3_ENDPOINT": "http://127.0.0.1:9000"}).s3_endpoint, "http://127.0.0.1:9000")


SMTP = {"SMPLDOC_SMTP_HOST": "smtp.example.com", "SMPLDOC_MAIL_FROM": "smpldoc@example.com", "SMPLDOC_SMTP_USER": "u", "SMPLDOC_SMTP_PASSWORD": "pw-secret"}


class MailOutConfigTest(unittest.TestCase):
    def test_mail_out_is_off_unless_configured(self):
        c = load(BASE)
        self.assertEqual((c.smtp_host, c.mail_from), (None, None))

    def test_defaults_are_safe_tls(self):
        c = load({**BASE, **SMTP})
        self.assertEqual((c.smtp_host, c.smtp_port, c.smtp_security, c.smtp_user, c.mail_from, c.max_forward_bytes),
                         ("smtp.example.com", 587, "starttls", "u", "smpldoc@example.com", 10_000_000))
        self.assertEqual(c.smtp_password, "pw-secret")
        self.assertNotIn("pw-secret", repr(c))

    def test_the_password_can_come_from_a_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "p")
            with open(path, "w") as f:
                f.write("from-file\n")
            env = {k: v for k, v in SMTP.items() if k != "SMPLDOC_SMTP_PASSWORD"}
            self.assertEqual(load({**BASE, **env, "SMPLDOC_SMTP_PASSWORD_FILE": path}).smtp_password, "from-file")
            with self.assertRaises(ConfigError):
                load({**BASE, **SMTP, "SMPLDOC_SMTP_PASSWORD_FILE": path})

    def test_bad_mail_out_settings_are_refused(self):
        bad = [("SMPLDOC_SMTP_SECURITY", "none"), ("SMPLDOC_SMTP_SECURITY", "carrier-pigeon"), ("SMPLDOC_SMTP_PORT", "0"),
               ("SMPLDOC_MAIL_FROM", "not an address"), ("SMPLDOC_SMTP_HOST", "bad host!"), ("SMPLDOC_MAX_FORWARD_BYTES", "0")]
        for key, value in bad:
            with self.assertRaises(ConfigError, msg=f"{key}={value}"):
                load({**BASE, **SMTP, key: value})
        with self.assertRaises(ConfigError):
            load({**BASE, "SMPLDOC_SMTP_HOST": "smtp.example.com"})  # no sender address
        with self.assertRaises(ConfigError):
            load({**BASE, "SMPLDOC_SMTP_HOST": "smtp.example.com", "SMPLDOC_MAIL_FROM": "a@example.com", "SMPLDOC_SMTP_USER": "u"})  # user without a password

    def test_plain_text_is_allowed_only_for_a_local_server(self):
        env = {**BASE, "SMPLDOC_SMTP_HOST": "127.0.0.1", "SMPLDOC_MAIL_FROM": "a@example.com", "SMPLDOC_SMTP_SECURITY": "none"}
        self.assertEqual(load(env).smtp_security, "none")


if __name__ == "__main__":
    unittest.main()
