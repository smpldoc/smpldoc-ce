"""Tests for check_repo.py. Run: python -B -m unittest discover -s scripts"""
import tempfile
import unittest
from pathlib import Path

import check_repo as cr

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"
# Built at run time so this file never contains a string that looks like a real secret.
AWS_KEY = "AK" + "IA" + "ABCDEFGHIJKLMNOP"
PRIVATE_KEY = "-----" + "BEGIN RSA PRIVATE KEY" + "-----"
GITHUB_TOKEN = "gh" + "p_" + "a" * 36


def workflow(body: str) -> str:
    return "name: x\non: push\npermissions:\n  contents: read\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps:\n" + body


class PinTests(unittest.TestCase):
    def test_full_sha_passes(self):
        self.assertEqual(cr.check_pins(workflow(f"      - uses: actions/checkout@{SHA} # v7.0.1\n"), "w.yml"), [])

    def test_floating_tag_fails(self):
        errors = cr.check_pins(workflow("      - uses: actions/checkout@v4\n"), "w.yml")
        self.assertEqual(len(errors), 1)
        self.assertIn("actions/checkout@v4", errors[0])

    def test_branch_ref_fails(self):
        self.assertEqual(len(cr.check_pins(workflow("      - uses: some/action@main\n"), "w.yml")), 1)

    def test_short_sha_fails(self):
        self.assertEqual(len(cr.check_pins(workflow("      - uses: some/action@3d3c42e\n"), "w.yml")), 1)

    def test_local_action_passes(self):
        self.assertEqual(cr.check_pins(workflow("      - uses: ./.github/actions/x\n"), "w.yml"), [])

    def test_container_needs_digest(self):
        self.assertEqual(len(cr.check_pins(workflow("      - uses: docker://alpine:3\n"), "w.yml")), 1)
        digest = "sha256:" + "a" * 64
        self.assertEqual(cr.check_pins(workflow(f"      - uses: docker://alpine@{digest}\n"), "w.yml"), [])


class WorkflowRuleTests(unittest.TestCase):
    def test_missing_top_level_permissions_fails(self):
        text = "name: x\non: push\njobs:\n  j:\n    runs-on: ubuntu-24.04\n    steps: []\n"
        self.assertEqual(len(cr.check_permissions(text, "w.yml")), 1)

    def test_top_level_permissions_passes(self):
        self.assertEqual(cr.check_permissions(workflow(""), "w.yml"), [])

    def test_pull_request_target_fails(self):
        text = "name: x\non:\n  pull_request_target:\npermissions: read-all\njobs: {}\n"
        self.assertEqual(len(cr.check_triggers(text, "w.yml")), 1)

    def test_normal_triggers_pass(self):
        self.assertEqual(cr.check_triggers(workflow(""), "w.yml"), [])

    def test_pipe_to_shell_fails(self):
        for line in ("curl -fsSL https://x.example/i.sh | sh", "wget -qO- https://x.example/i.sh | sudo bash"):
            with self.subTest(line=line):
                self.assertEqual(len(cr.check_pipe_to_shell(workflow(f"      - run: {line}\n"), "w.yml")), 1)

    def test_download_without_pipe_passes(self):
        self.assertEqual(cr.check_pipe_to_shell(workflow("      - run: curl -fsSLO https://x.example/f\n"), "w.yml"), [])


class SecretTests(unittest.TestCase):
    def test_known_secret_shapes_are_found(self):
        for secret in (AWS_KEY, PRIVATE_KEY, GITHUB_TOKEN):
            with self.subTest(secret=secret[:8]):
                self.assertEqual(len(cr.check_secrets(f"value = {secret}\n", "f.txt")), 1)

    def test_ordinary_text_passes(self):
        self.assertEqual(cr.check_secrets("The access key id is read from the platform role.\n", "f.md"), [])


class DockerfileTests(unittest.TestCase):
    def test_base_image_needs_digest(self):
        self.assertEqual(len(cr.check_dockerfile("FROM python:3.12-slim\n", "Dockerfile")), 1)

    def test_pinned_base_image_passes(self):
        text = "FROM python:3.12-slim@sha256:" + "b" * 64 + " AS run\n"
        self.assertEqual(cr.check_dockerfile(text, "Dockerfile"), [])

    def test_earlier_stage_name_is_allowed(self):
        text = "FROM python:3.12-slim@sha256:" + "b" * 64 + " AS build\nFROM build\n"
        self.assertEqual(cr.check_dockerfile(text, "Dockerfile"), [])

    def test_scratch_is_allowed(self):
        self.assertEqual(cr.check_dockerfile("FROM scratch\n", "Dockerfile"), [])


class RequiredFileTests(unittest.TestCase):
    def test_missing_files_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            errors = cr.check_required_files(Path(tmp))
            self.assertTrue(any("LICENSE" in e for e in errors))
            self.assertTrue(any("SECURITY.md" in e for e in errors))


class RepositoryTests(unittest.TestCase):
    def test_this_repository_passes(self):
        self.assertEqual(cr.run(Path(__file__).resolve().parent.parent), [])


if __name__ == "__main__":
    unittest.main()
