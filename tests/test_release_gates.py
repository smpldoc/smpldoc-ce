"""The image job in CI is part of the release gate. These static checks keep its steps from being
quietly removed. The steps themselves run in CI against the real image."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "deploy.yml").read_text()
CONTAINER_JOB = WORKFLOW[WORKFLOW.index("\n  container:"):]


class ImageJobTest(unittest.TestCase):
    def test_the_image_is_scanned_by_a_pinned_scanner(self):
        self.assertRegex(CONTAINER_JOB, r"trivy@sha256:[0-9a-f]{64}")
        self.assertIn("--severity HIGH,CRITICAL", CONTAINER_JOB)
        self.assertIn("--exit-code 1", CONTAINER_JOB)

    def test_spin_down_then_up_on_the_same_volume_keeps_the_data(self):
        # Start, write, stop, start again on the same volume, and read it back.
        starts = [m.start() for m in re.finditer(r"docker run -d --name smpldoc\b|start_smpldoc\b", CONTAINER_JOB)]
        self.assertGreaterEqual(len(starts), 2, "the container must be started twice on the same volume")
        self.assertRegex(CONTAINER_JOB, r"docker (stop|rm -f?) smpldoc")
        self.assertRegex(CONTAINER_JOB, r"python -m smpldoc jobs ci")  # exits 0 only if the company survived

    def test_a_software_bill_of_materials_is_made_and_kept(self):
        self.assertIn("--format cyclonedx", CONTAINER_JOB)
        self.assertRegex(CONTAINER_JOB, r"actions/upload-artifact@[0-9a-f]{40}")
        self.assertIn("sbom", CONTAINER_JOB.lower())

    def test_the_job_never_publishes_or_uses_secrets(self):
        # Publishing is a separate step on a version tag (feature container-release), not this job.
        self.assertNotRegex(CONTAINER_JOB, r"docker push|packages:\s*write|secrets\.")


if __name__ == "__main__":
    unittest.main()
