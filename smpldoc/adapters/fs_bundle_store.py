"""Bundle store on a local directory: <root>/<company>/<bundle id>/<same paths as in a bucket>.

A bundle is written to a temporary folder and moved into place, so a reader sees the old bundle or
the new one, never half of either. Every name is checked before anything is written, so a hostile
company, id or path can never leave the root. Links are never followed.
"""
import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping

from smpldoc.adapters.fs_bundle import BundleReadError, read_bundle_dir
from smpldoc.domain.bundle import COMPANY, BUNDLE_ID, check_store_names

class FileBundleStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _dir(self, company, bundle_id):
        return self.root / company / bundle_id

    def put(self, company, bundle_id, files):
        check_store_names(company, bundle_id, files)
        parent = self.root / company
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = Path(tempfile.mkdtemp(prefix=".tmp-", dir=parent))
        try:
            for path, data in files.items():
                target = tmp / path
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
            final = self._dir(company, bundle_id)
            if final.exists():  # replace: move the old one aside, the new one in, then drop the old
                old = Path(tempfile.mkdtemp(prefix=".old-", dir=parent))
                os.rename(final, old / "b")
                os.rename(tmp, final)
                shutil.rmtree(old, ignore_errors=True)
            else:
                os.rename(tmp, final)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)  # only still there if something failed

    def get(self, company, bundle_id):
        if not (COMPANY.match(company or "") and BUNDLE_ID.match(bundle_id or "")):
            raise KeyError(bundle_id)
        folder = self._dir(company, bundle_id)
        if not folder.is_dir():
            raise KeyError(bundle_id)
        try:
            return read_bundle_dir(str(folder))
        except BundleReadError:
            raise KeyError(bundle_id) from None  # a link or an odd file: not a bundle we wrote

    def list_ids(self, company):
        if not COMPANY.match(company or ""):
            return []
        parent = self.root / company
        if not parent.is_dir():
            return []
        return sorted(p.name for p in parent.iterdir() if BUNDLE_ID.match(p.name) and p.is_dir() and not p.is_symlink())
