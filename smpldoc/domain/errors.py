class SmpldocError(Exception):
    """Base class. Messages may hold document text, so they are never stored or logged."""


class ExtractError(SmpldocError):
    """An extractor could not read a document."""
