import unittest
from pathlib import Path

from tools.pico_deploy.mpy_compiler import should_compile


class MpyCompilerTests(unittest.TestCase):
    def test_should_compile_excludes_epaper_main_and_non_python_files(self):
        # epaper.py: vendor driver, kept readable for hardware debugging.
        self.assertFalse(should_compile(Path("src/epaper.py")))
        # main.py: confirmed on real hardware that main.mpy is not auto-run at
        # boot (only a manual `import main` executes it) - must stay .py.
        self.assertFalse(should_compile(Path("src/main.py")))
        self.assertFalse(should_compile(Path("src/config.json")))
        self.assertTrue(should_compile(Path("src/wifi_manager.py")))


if __name__ == "__main__":
    unittest.main()
