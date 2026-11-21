"""Choose the MailIn adapter from the settings. Lives outside domain/: it knows about adapters."""
from smpldoc.adapters.aws_creds import CredentialProvider
from smpldoc.adapters.relay_pull import RelayPull
from smpldoc.adapters.s3_inbox import S3Inbox


def build_mail_in(config, env):
    if config.mail_source == "s3":
        return S3Inbox(config.s3_bucket, config.s3_region, CredentialProvider(env), endpoint=config.s3_endpoint,
                       prefix=config.s3_prefix, domain=config.mail_domain, authserv_id=config.s3_authserv_id,
                       max_bytes=config.max_message_bytes)
    return RelayPull(config.relay_url, config.relay_token, max_bytes=config.max_message_bytes)
