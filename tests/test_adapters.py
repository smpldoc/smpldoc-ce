import tempfile
import unittest
from pathlib import Path

from smpldoc.adapters.fs_blob import FileBlob
from smpldoc.adapters.fs_bundle_store import FileBundleStore
from smpldoc.adapters.memory import MemoryBlob, MemoryBundleStore, MemoryMailIn
from smpldoc.adapters.plain_text import PlainTextExtractor
from smpldoc.adapters.sqlite_store import SqliteStore
from tests.contracts import BlobContract, BundleStoreContract, ExtractorContract, MailInContract, RAW, StoreContract


class SqliteStoreTest(StoreContract, unittest.TestCase):
    def make_store(self):
        return SqliteStore(":memory:")


class SqliteStoreOnDiskTest(StoreContract, unittest.TestCase):
    def make_store(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        return SqliteStore(str(Path(self._d.name) / "smpldoc.db"))


class MemoryBlobTest(BlobContract, unittest.TestCase):
    def make_blob(self):
        return MemoryBlob()


class FileBlobTest(BlobContract, unittest.TestCase):
    def make_blob(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        return FileBlob(self._d.name)

    def test_bad_company_id_is_refused(self):
        for bad in ("../x", "a/b", "", "x" * 65):
            with self.assertRaises(ValueError, msg=bad):
                self.blob.put(bad, RAW)


class PlainTextExtractorTest(ExtractorContract, unittest.TestCase):
    def make_extractor(self):
        return PlainTextExtractor()

    def test_key_value_lines(self):
        got = self.extractor.extract("a.txt", "text/plain", b"Invoice No: 42\nTotal: 9.50\nno colon here\n: empty key\n")
        self.assertEqual(got, [("invoice_no", "42"), ("total", "9.50")])

    def test_only_text_types_are_read(self):
        self.assertEqual(self.extractor.extract("a.pdf", "application/pdf", b"Total: 1"), [])

    def test_limits(self):
        many = "".join(f"k{i}: v\n" for i in range(500)).encode()
        self.assertEqual(len(self.extractor.extract("a.txt", "text/plain", many)), 100)
        self.assertEqual(self.extractor.extract("a.txt", "text/plain", b"k: " + b"v" * 1000), [])


class MemoryMailInTest(MailInContract, unittest.TestCase):
    def setUp(self):
        self.mail = MemoryMailIn()

    def deliver(self, raw=RAW, sender="s@x.test", recipient="acme@in.test", verdict="pass"):
        self.mail.deliver(raw, sender, recipient, verdict)
        return raw


if __name__ == "__main__":
    unittest.main()


class MemoryBundleStoreTest(BundleStoreContract, unittest.TestCase):
    def make_bundles(self):
        return MemoryBundleStore()


class FileBundleStoreTest(BundleStoreContract, unittest.TestCase):
    def make_bundles(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        return FileBundleStore(self.tmp.name)

    def test_the_layout_on_disk_is_company_then_bundle_then_the_same_paths(self):
        self.bundles.put("acme", self.ID, self.FILES)
        self.assertEqual((Path(self.tmp.name) / "acme" / self.ID / "original" / "a.txt").read_bytes(), b"hello")

    def test_no_temporary_folders_are_left_behind(self):
        self.bundles.put("acme", self.ID, self.FILES)
        self.bundles.put("acme", self.ID, {"manifest.json": b"{}"})
        self.assertEqual([p.name for p in (Path(self.tmp.name) / "acme").iterdir()], [self.ID])

    def test_stray_temporary_folders_are_not_listed_as_bundles(self):
        (Path(self.tmp.name) / "acme" / ".tmp-x").mkdir(parents=True)
        self.bundles.put("acme", self.ID, self.FILES)
        self.assertEqual(self.bundles.list_ids("acme"), [self.ID])

    def test_a_link_inside_a_stored_bundle_is_refused_on_read(self):
        self.bundles.put("acme", self.ID, self.FILES)
        (Path(self.tmp.name) / "acme" / self.ID / "link").symlink_to("/etc/hostname")
        with self.assertRaises(KeyError):
            self.bundles.get("acme", self.ID)

    def test_folders_it_creates_are_private_to_the_service(self):
        root = Path(self.tmp.name) / "bundles"
        FileBundleStore(root).put("acme", self.ID, self.FILES)
        for folder in (root, root / "acme", root / "acme" / self.ID, root / "acme" / self.ID / "original"):
            self.assertEqual(folder.stat().st_mode & 0o077, 0, folder)
