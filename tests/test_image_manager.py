import importlib
import io
import sys
import tempfile
import unittest
from pathlib import Path


class ImageStoreTests(unittest.TestCase):
    def setUp(self):
        src = str(Path(__file__).resolve().parents[1] / "src")
        if src not in sys.path:
            sys.path.insert(0, src)
        self.module = importlib.import_module("image_manager")
        self.temp = tempfile.TemporaryDirectory()
        self.module.IMAGE_ROOT = self.temp.name.replace("\\", "/")
        self.module.SAFE_FREE_BYTES = 0
        self.store = self.module.ImageStore()

    def tearDown(self):
        self.temp.cleanup()

    def test_upload_validates_length_and_preserves_bytes(self):
        data = bytes((index % 251 for index in range(2048)))
        result = self.store.upload(io.BytesIO(data), "custom", "sample.bin", len(data))
        self.assertFalse(result["replaced"])
        target = Path(self.temp.name) / "custom" / "sample.bin"
        self.assertEqual(target.read_bytes(), data)
        self.assertEqual(Path(str(target) + ".hlsb").read_bytes(), b"1")

    def test_overwrite_keeps_new_file_and_removes_transaction_files(self):
        first = b"\x11" * 2048
        second = b"\x22" * 2048
        self.store.upload(io.BytesIO(first), "custom", "sample.bin", len(first))
        result = self.store.upload(io.BytesIO(second), "custom", "sample.bin", len(second), overwrite=True)
        directory = Path(self.temp.name) / "custom"
        self.assertTrue(result["replaced"])
        self.assertEqual((directory / "sample.bin").read_bytes(), second)
        self.assertFalse((directory / "sample.bin.part").exists())
        self.assertFalse((directory / "sample.bin.bak").exists())
        self.assertTrue((directory / "sample.bin.hlsb").exists())

    def test_recovery_restores_backup_when_target_is_missing(self):
        directory = Path(self.temp.name) / "custom"
        directory.mkdir(parents=True)
        backup = directory / "lost.bin.bak"
        backup.write_bytes(b"\x33" * 2048)
        self.assertEqual(self.store.recover_partial_uploads(), 1)
        self.assertTrue((directory / "lost.bin").exists())
        self.assertFalse(backup.exists())

    def test_recovery_never_promotes_hlsb_data_without_marker(self):
        directory = Path(self.temp.name) / "custom"
        directory.mkdir(parents=True)
        part = directory / "orphan.bin.part"
        part.write_bytes(b"\x05" * 2048)
        self.assertEqual(self.store.recover_partial_uploads(), 0)
        self.assertFalse((directory / "orphan.bin").exists())
        self.assertFalse(part.exists())

    def test_recovery_does_not_mark_legacy_target_before_data_swap(self):
        directory = Path(self.temp.name) / "custom"
        directory.mkdir(parents=True)
        target = directory / "legacy.bin"
        target.write_bytes(b"\x80" * 2048)
        (directory / "legacy.bin.part").write_bytes(b"\x01" * 2048)
        (directory / "legacy.bin.hlsb.part").write_bytes(b"1")
        self.store.recover_partial_uploads()
        self.assertEqual(target.read_bytes(), b"\x80" * 2048)
        self.assertFalse((directory / "legacy.bin.hlsb").exists())

    def test_rejects_path_traversal(self):
        with self.assertRaises(self.module.ImageStoreError):
            self.store.upload(io.BytesIO(b"\0" * 2048), "custom", "../bad.bin", 2048)


if __name__ == "__main__":
    unittest.main()
