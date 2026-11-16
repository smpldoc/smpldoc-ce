"""The first extractor: reads `Name: value` lines from text documents. No network, no AI service.
PDFs and images need a real extractor adapter later (see docs/FEATURES.md)."""
import re

MAX_FIELDS, MAX_LINE = 100, 200


class PlainTextExtractor:
    def extract(self, filename, content_type, data):
        if not content_type.startswith("text/"):
            return []
        out = []
        for line in data.decode("utf-8", errors="replace").splitlines():
            name, sep, value = line.partition(":")
            name = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
            value = value.strip()
            if sep and name and value and len(line) <= MAX_LINE:
                out.append((name, value))
                if len(out) == MAX_FIELDS:
                    break
        return out
