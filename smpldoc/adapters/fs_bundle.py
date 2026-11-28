"""Read a bundle folder into memory for checking. Links are refused, sizes are capped."""
import os
from pathlib import Path

MAX_FILES = 2000
MAX_BYTES = 256 * 1024 * 1024


class BundleReadError(Exception):
    pass


def read_bundle_dir(root: str, max_files: int = MAX_FILES, max_bytes: int = MAX_BYTES) -> dict[str, bytes]:
    base = Path(root)
    if base.is_symlink() or not base.is_dir():
        raise BundleReadError(f"{root}: not a folder")
    files, total = {}, 0
    for folder, dirs, names in os.walk(base, followlinks=False):
        for name in sorted(dirs + names):
            path = Path(folder, name)
            rel = path.relative_to(base).as_posix()
            if path.is_symlink():
                raise BundleReadError(f"{rel}: a link, not a file")
            if name in dirs:
                continue
            if not path.is_file():
                raise BundleReadError(f"{rel}: not a regular file")
            if len(files) >= max_files:
                raise BundleReadError(f"more than {max_files} files")
            total += path.stat().st_size
            if total > max_bytes:
                raise BundleReadError(f"more than {max_bytes} bytes")
            files[rel] = path.read_bytes()
    return files
