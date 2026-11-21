"""Static security checks for deploy/aws/mail-intake.yaml. CI cannot deploy it, so the properties
that matter are asserted on the text: a private bucket, TLS only, SES limited to this account, and
roles that can touch only the mail folders."""
import re
import unittest
from pathlib import Path

T = (Path(__file__).resolve().parent.parent / "deploy" / "aws" / "mail-intake.yaml").read_text()


class MailIntakeTemplateTest(unittest.TestCase):
    def test_the_bucket_is_private_encrypted_and_kept_on_stack_delete(self):
        for needle in ("BlockPublicAcls: true", "BlockPublicPolicy: true", "IgnorePublicAcls: true", "RestrictPublicBuckets: true",
                       "SSEAlgorithm: AES256", "BucketOwnerEnforced", "DeletionPolicy: Retain"):
            self.assertIn(needle, T)

    def test_only_tls_is_accepted(self):
        self.assertIn("aws:SecureTransport", T)
        self.assertRegex(T, r"aws:SecureTransport:\s*false")

    def test_ses_may_write_only_for_this_account_and_rule_set(self):
        self.assertIn("ses.amazonaws.com", T)
        self.assertIn("aws:SourceAccount", T)
        self.assertIn("aws:SourceArn", T)
        self.assertRegex(T, r"Action:\s*s3:PutObject")

    def test_a_wildcard_is_only_ever_used_to_deny(self):
        statements = re.split(r"\n\s*- Sid: ", T)[1:]
        self.assertTrue(statements)
        for st in statements:
            if re.search(r"Principal:\s*['\"]?\*|Action:\s*['\"]?(?:s3:)?\*", st):
                self.assertIn("Effect: Deny", st, st.splitlines()[0])
        self.assertNotRegex(T, r"AWS:\s*['\"]?\*")

    def test_the_reader_policy_is_limited_to_the_mail_folders(self):
        for needle in ("s3:ListBucket", "s3:GetObject", "s3:DeleteObject", "s3:PutObject", "s3:prefix", "inbox/", "processed/", "quarantine/"):
            self.assertIn(needle, T)
        self.assertNotRegex(T, r"(?m)Resource:\s*['\"]?\*['\"]?\s*$")

    def test_both_a_vm_and_a_container_role_can_use_the_policy(self):
        self.assertIn("ec2.amazonaws.com", T)
        self.assertIn("ecs-tasks.amazonaws.com", T)

    def test_the_old_ses_receive_settings_are_safe_defaults(self):
        self.assertIn("ScanEnabled: true", T)
        self.assertIn("AWS::SES::ReceiptRule", T)

    def test_mail_expires_so_cost_stays_bounded(self):
        self.assertIn("ExpirationInDays", T)

    def test_outputs_give_the_settings_the_container_needs(self):
        for needle in ("SMPLDOC_MAIL_SOURCE", "SMPLDOC_S3_BUCKET", "SMPLDOC_S3_REGION", "SMPLDOC_MAIL_DOMAIN"):
            self.assertIn(needle, T)


if __name__ == "__main__":
    unittest.main()
