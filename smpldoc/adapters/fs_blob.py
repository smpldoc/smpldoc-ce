"""Blob adapter on a local directory (a mounted volume). Keys are sha256 hex, company ids are
checked, so a hostile id or key can never leave the root."""
import hashlib
import os
import re
import tempfile
from pathlib import Path

_COMPANY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_KEY = re.compile(r"^[0-9a-f]{64}$")


class FileBlob:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, company_id, key):
        return self.root / company_id / key[:2] / key

    def put(self, company_id, data):
        if not _COMPANY.match(company_id):
            raise ValueError("bad company id")
        key = hashlib.sha256(data).hexdigest()
        path = self._path(company_id, key)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        return key

    def get(self, company_id, key):
        if not (_COMPANY.match(company_id or "") and _KEY.match(key or "")):
            raise KeyError(key)
        try:
            return self._path(company_id, key).read_bytes()
        except FileNotFoundError:
            raise KeyError(key) from None
