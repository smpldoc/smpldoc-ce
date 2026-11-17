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
            open(path, "w").write("filetoken\n")
            env = {"SMPLDOC_RELAY_URL": BASE["SMPLDOC_RELAY_URL"], "SMPLDOC_RELAY_TOKEN_FILE": path}
            self.assertEqual(load(env).relay_token, "filetoken")

    def test_token_and_token_file_together_are_refused(self):
        with self.assertRaises(ConfigError):
            load({**BASE, "SMPLDOC_RELAY_TOKEN_FILE": "/x"})

    def test_missing_or_empty_token_file_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            empty = os.path.join(d, "e")
            open(empty, "w").write("\n")
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


if __name__ == "__main__":
    unittest.main()
