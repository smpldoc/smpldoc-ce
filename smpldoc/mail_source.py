"""Choose the MailIn adapter from the settings. Lives outside domain/: it knows about adapters."""
from smpldoc.adapters.aws_creds import CredentialProvider
from smpldoc.adapters.relay_pull import RelayPull
from smpldoc.adapters.s3_inbox import S3Inbox
from smpldoc.adapters.smtp_out import SmtpMailOut


def build_mail_in(config, env):
    if config.mail_source == "s3":
        return S3Inbox(config.s3_bucket, config.s3_region, CredentialProvider(env), endpoint=config.s3_endpoint,
                       prefix=config.s3_prefix, domain=config.mail_domain, authserv_id=config.s3_authserv_id,
                       max_bytes=config.max_message_bytes)
    return RelayPull(config.relay_url, config.relay_token, max_bytes=config.max_message_bytes)


def build_mail_out(config):
    """The SMTP sender, or None when no server is configured (forwarding then fails clearly, nothing is lost)."""
    if not config.smtp_host:
        return None
    return SmtpMailOut(config.smtp_host, config.smtp_port, config.mail_from, security=config.smtp_security,
                       username=config.smtp_user, password=config.smtp_password)
