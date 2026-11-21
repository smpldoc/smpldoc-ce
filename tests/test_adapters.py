import tempfile
import unittest
from pathlib import Path

from smpldoc.adapters.fs_blob import FileBlob
from smpldoc.adapters.memory import MemoryBlob, MemoryMailIn
from smpldoc.adapters.plain_text import PlainTextExtractor
from smpldoc.adapters.sqlite_store import SqliteStore
from tests.contracts import BlobContract, ExtractorContract, MailInContract, RAW, StoreContract


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
