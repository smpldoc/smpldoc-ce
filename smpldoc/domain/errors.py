class SmpldocError(Exception):
    """Base class. Messages may hold document text, so they are never stored or logged."""


class ExtractError(SmpldocError):
    """An extractor could not read a document."""


class RuleError(SmpldocError):
    """A routing rule is not acceptable. The message says why and is safe to show."""


class RuleTimeout(SmpldocError):
    """Evaluating the rules took too long and was cut off."""


class ForwardError(SmpldocError):
    """A job cannot be forwarded as asked (too large, bad address). Retrying will not help."""

    permanent = True


class SendError(SmpldocError):
    """A mail-out adapter could not send. `permanent` means retrying will not help."""

    def __init__(self, message="", permanent=False):
        super().__init__(message)
        self.permanent = permanent
