"""MailOut adapter over SMTP, on the standard library. Works with Amazon SES's SMTP endpoint, Microsoft
365, Gmail, Postmark and any other SMTP service. TLS is required (STARTTLS or implicit TLS, certificate
and host name checked); plain text is allowed only to a server on this machine. The password is used
only after TLS is up and never appears in an error."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import make_msgid

from smpldoc.domain.deliver import valid_address
from smpldoc.domain.errors import SendError

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
SECURITY = ("starttls", "ssl", "none")


def _content_type(value):
    main, _, sub = (value or "").partition("/")
    ok = lambda s: s.replace("-", "").replace(".", "").replace("+", "").isalnum()
    return (main.lower(), sub.lower()) if main and sub and ok(main) and ok(sub) else ("application", "octet-stream")


class SmtpMailOut:
    def __init__(self, host, port, sender, *, security="starttls", username=None, password=None, timeout=30,
                 smtp_factory=None, ssl_context=None):
        if security not in SECURITY:
            raise ValueError(f"security must be one of {', '.join(SECURITY)}")
        if security == "none" and host not in LOOPBACK:
            raise ValueError("plain-text SMTP is only allowed to a server on this machine")
        if not valid_address(sender):
            raise ValueError("the sender must be a valid email address")
        if username and not password:
            raise ValueError("a username needs a password")
        self.host, self.port, self.sender, self.security = host, port, sender, security
        self.username, self.password, self.timeout = username, password, timeout
        self._factory, self._ctx = smtp_factory, ssl_context

    def _message(self, mail):
        msg = EmailMessage()
        try:
            msg["From"], msg["To"], msg["Subject"] = self.sender, mail.to, mail.subject
            msg["Message-ID"] = make_msgid(domain=self.sender.rsplit("@", 1)[1])
            msg.set_content(mail.text)
            for a in mail.attachments:
                main, sub = _content_type(a.content_type)
                msg.add_attachment(a.data, maintype=main, subtype=sub, filename=a.filename)
        except (ValueError, TypeError):
            raise SendError("the message could not be built (bad header or attachment)", permanent=True) from None
        return msg

    def send(self, mail):
        msg = self._message(mail)
        ctx = self._ctx or ssl.create_default_context()
        server = None
        try:
            if self.security == "ssl":
                server = (self._factory or smtplib.SMTP_SSL)(self.host, self.port, timeout=self.timeout, context=ctx)
                server.ehlo()
            else:
                server = (self._factory or smtplib.SMTP)(self.host, self.port, timeout=self.timeout)
                server.ehlo()
                if self.security == "starttls":
                    server.starttls(context=ctx)
                    server.ehlo()
            if self.username:
                server.login(self.username, self.password)
            server.send_message(msg)
            return msg["Message-ID"]
        except smtplib.SMTPRecipientsRefused as e:
            code = next(iter(e.recipients.values()))[0] if e.recipients else 550
            raise SendError(f"the server refused the recipient ({code})", permanent=code >= 500) from None
        except smtplib.SMTPResponseException as e:  # includes bad credentials (535) and refused data
            raise SendError(f"the server answered {e.smtp_code}", permanent=e.smtp_code >= 500) from None
        except (smtplib.SMTPException, OSError, TimeoutError) as e:
            raise SendError(f"mail server unreachable or unwilling: {type(e).__name__}") from None
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass
