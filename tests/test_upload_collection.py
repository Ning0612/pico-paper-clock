import tempfile
import unittest
from pathlib import Path

import upload
from tools.pico_image_tool.conversion import save_bin


class UploadCollectionTests(unittest.TestCase):
    def test_serial_deploy_collects_only_ppc1_bin_image(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "src"
            image = source / "image" / "custom" / "sample.bin"
            save_bin(image, b"\x05")
            original_source = upload.SOURCE_DIR
            original_images = upload.UPLOAD_IMAGES
            original_no_config = upload.NO_CONFIG
            try:
                upload.SOURCE_DIR = str(source)
                upload.UPLOAD_IMAGES = True
                upload.NO_CONFIG = False
                relative = {item[1] for item in upload.collect_files()}
            finally:
                upload.SOURCE_DIR = original_source
                upload.UPLOAD_IMAGES = original_images
                upload.NO_CONFIG = original_no_config
            self.assertIn("image/custom/sample.bin", relative)
            self.assertNotIn("image/custom/sample.bin.hlsb", relative)


if __name__ == "__main__":
    unittest.main()
