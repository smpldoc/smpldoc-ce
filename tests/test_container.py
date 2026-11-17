"""Static hardening checks for the image and the example compose file. CI also builds the image,
scans it, and runs it with these same settings."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = (ROOT / "Dockerfile").read_text()
COMPOSE = (ROOT / "compose.yaml").read_text()


class DockerfileTest(unittest.TestCase):
    def test_base_image_is_pinned_by_digest(self):
        self.assertRegex(DOCKERFILE, r"(?m)^FROM \S+@sha256:[0-9a-f]{64}")

    def test_runs_as_a_non_root_user(self):
        users = re.findall(r"(?m)^USER (\S+)", DOCKERFILE)
        self.assertTrue(users)
        self.assertNotIn(users[-1].split(":")[0], {"root", "0"})

    def test_has_a_healthcheck_and_no_remote_downloads(self):
        self.assertIn("HEALTHCHECK", DOCKERFILE)
        self.assertNotRegex(DOCKERFILE, r"(?mi)^ADD\s+https?://")
        self.assertNotRegex(DOCKERFILE, r"(curl|wget)[^\n]*\|")

    def test_bakes_in_no_secrets_and_no_public_only_defaults(self):
        self.assertNotRegex(DOCKERFILE, r"(?i)(TOKEN|SECRET|PASSWORD|KEY)\s*=\s*\S")

    def test_dockerignore_keeps_the_context_small(self):
        ignore = (ROOT / ".dockerignore").read_text()
        for entry in (".git", "tests", "docs", "secrets"):
            self.assertIn(entry, ignore)


class ComposeTest(unittest.TestCase):
    def test_container_is_locked_down(self):
        for needle in ("read_only: true", "no-new-privileges:true", "cap_drop:", "- ALL", "pids_limit:", "mem_limit:"):
            self.assertIn(needle, COMPOSE)
        self.assertNotIn("privileged", COMPOSE)
        self.assertNotIn("docker.sock", COMPOSE)
        self.assertNotRegex(COMPOSE, r"network_mode:\s*host")

    def test_published_port_is_loopback_only_by_default(self):
        for port in re.findall(r"(?m)^\s*-\s*\"?([^\s\"]*\d+:\d+)\"?\s*$", COMPOSE):
            self.assertTrue(port.startswith("127.0.0.1:"), port)

    def test_the_token_comes_from_a_secret_file_not_the_compose_file(self):
        self.assertIn("SMPLDOC_RELAY_TOKEN_FILE", COMPOSE)
        self.assertNotIn("SMPLDOC_RELAY_TOKEN:", COMPOSE)
        self.assertIn("secrets/", (ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
