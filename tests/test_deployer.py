import tempfile
import time
import unittest
from pathlib import Path

from tools.pico_deploy.deployer import (
    CancellationToken,
    DeployOptions,
    DeploymentCancelled,
    DeploymentError,
    SerialDeployer,
    build_deploy_plan,
)
from tools.pico_deploy import mpy_compiler
from tools.pico_deploy.jobs import Job, JobQueue
from tools.pico_deploy.gui import ImageJob, PicoDeployTool
from tools.pico_image_tool.conversion import ConversionOptions


class FakeRunner:
    def __init__(self):
        self.commands = []

    def run(self, arguments, cancellation=None, check=True):
        if cancellation:
            cancellation.raise_if_cancelled()
        self.commands.append((list(arguments), check))
        return ""


class DeployerTests(unittest.TestCase):
    def test_manifest_is_stable_and_excludes_config_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("main", encoding="utf-8")
            (root / "src" / "config.json").write_text("{}", encoding="utf-8")
            (root / "src" / "html").mkdir()
            (root / "src" / "html" / "settings.bin").write_bytes(b"html")
            (root / "src" / "image" / "custom").mkdir(parents=True)
            (root / "src" / "image" / "custom" / "a.bin").write_bytes(b"image")
            (root / "src" / "image" / "custom" / "a.bin.hlsb").write_bytes(b"1")

            plan = build_deploy_plan(DeployOptions(root))

            self.assertEqual(
                [entry.remote_path for entry in plan.entries],
                ["html/settings.bin", "image/custom/a.bin", "main.py"],
            )
            self.assertNotIn("config.json", [entry.remote_path for entry in plan.entries])

            config_plan = build_deploy_plan(DeployOptions(root, include_config=True))
            self.assertIn("config.json", [entry.remote_path for entry in config_plan.entries])

    def test_recursive_cleanup_requires_explicit_config_inclusion(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                DeployOptions(Path(temp), clean_mode="recursive")

    def test_deploy_creates_directories_uploads_manifest_and_resets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src" / "nested" / "deep").mkdir(parents=True)
            (root / "src" / "nested" / "deep" / "main.py").write_bytes(b"main")
            plan = build_deploy_plan(DeployOptions(root))
            runner = FakeRunner()

            SerialDeployer(runner).deploy(plan, DeployOptions(root), log=lambda _message: None)

            commands = [command for command, _check in runner.commands]
            self.assertEqual(commands[0], ["fs", "mkdir", ":nested"])
            self.assertEqual(commands[1], ["fs", "mkdir", ":nested/deep"])
            self.assertEqual(commands[2], ["fs", "cp", str(root / "src" / "nested" / "deep" / "main.py"), ":nested/deep/main.py"])
            self.assertEqual(commands[-1], ["reset"])

    def test_cancelled_deploy_does_not_run_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("main", encoding="utf-8")
            plan = build_deploy_plan(DeployOptions(root))
            token = CancellationToken()
            token.cancel()

            with self.assertRaises(DeploymentCancelled):
                SerialDeployer(FakeRunner()).deploy(plan, DeployOptions(root), cancellation=token)


class DeployerMpyTests(unittest.TestCase):
    def _fake_compile(self, calls):
        def compile_to_mpy(src_py, out_dir, relative_posix):
            calls.append(relative_posix)
            out_relative = relative_posix[:-3] + ".mpy" if relative_posix.endswith(".py") else relative_posix + ".mpy"
            out_path = out_dir / out_relative
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(b"MPY")
            return out_path
        return compile_to_mpy

    def test_compiles_python_files_except_epaper_main_and_config(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("main", encoding="utf-8")
            (root / "src" / "epaper.py").write_text("epaper", encoding="utf-8")
            (root / "src" / "wifi_manager.py").write_text("wifi", encoding="utf-8")
            (root / "src" / "config.json").write_text("{}", encoding="utf-8")

            calls = []
            original_compile = mpy_compiler.compile_to_mpy
            mpy_compiler.compile_to_mpy = self._fake_compile(calls)
            try:
                plan = build_deploy_plan(DeployOptions(root, include_config=True, compile_mpy=True))
            finally:
                mpy_compiler.compile_to_mpy = original_compile

            remote_paths = {entry.remote_path for entry in plan.entries}
            # main.py stays .py: real-device verification found main.mpy is
            # never auto-run at boot, only a manual `import main` executes it.
            self.assertIn("main.py", remote_paths)
            self.assertNotIn("main.mpy", remote_paths)
            self.assertIn("epaper.py", remote_paths)
            self.assertIn("wifi_manager.mpy", remote_paths)
            self.assertNotIn("wifi_manager.py", remote_paths)
            self.assertIn("config.json", remote_paths)
            self.assertNotIn("config.json", calls)
            self.assertNotIn("main.py", calls)
            self.assertNotIn("epaper.py", calls)
            self.assertIsNotNone(plan.staging_dir)

            epaper_entry = next(e for e in plan.entries if e.remote_path == "epaper.py")
            self.assertEqual(epaper_entry.local_path, root / "src" / "epaper.py")

            main_entry = next(e for e in plan.entries if e.remote_path == "main.py")
            self.assertEqual(main_entry.local_path, root / "src" / "main.py")

            wifi_entry = next(e for e in plan.entries if e.remote_path == "wifi_manager.mpy")
            self.assertEqual(wifi_entry.local_path, plan.staging_dir / "wifi_manager.mpy")

    def test_compile_mpy_false_has_no_staging_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("main", encoding="utf-8")

            plan = build_deploy_plan(DeployOptions(root))

            self.assertIsNone(plan.staging_dir)

    def test_compile_failure_raises_deployment_error_without_touching_device(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "src" / "wifi_manager.py").write_text("wifi", encoding="utf-8")

            def failing_compile(src_py, out_dir, relative_posix):
                raise mpy_compiler.MpyCompileError("boom")

            original_compile = mpy_compiler.compile_to_mpy
            mpy_compiler.compile_to_mpy = failing_compile
            try:
                with self.assertRaises(DeploymentError):
                    build_deploy_plan(DeployOptions(root, compile_mpy=True))
            finally:
                mpy_compiler.compile_to_mpy = original_compile


class JobQueueTests(unittest.TestCase):
    def _wait(self, queue):
        deadline = time.monotonic() + 2
        while queue.running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(queue.running)

    def test_jobs_run_in_order_and_stop_after_failure(self):
        calls = []
        queue = JobQueue()
        queue.add(Job("first", lambda _token, _log: calls.append("first")))
        queue.add(Job("failure", lambda _token, _log: (_ for _ in ()).throw(DeploymentError("boom"))))
        queue.add(Job("third", lambda _token, _log: calls.append("third")))

        queue.start()
        self._wait(queue)

        self.assertEqual(calls, ["first"])
        self.assertEqual([job.status for job in queue.jobs], ["success", "failed", "pending"])


class ImageJobValidationTests(unittest.TestCase):
    def test_remote_filename_and_event_validation(self):
        valid = ImageJob(Path("photo.png"), ConversionOptions(target="events"), "photo_1.bin", "1225")
        PicoDeployTool._validate_image_job(valid)

        invalid_name = ImageJob(Path("photo.png"), ConversionOptions(), "bad name.bin")
        with self.assertRaises(ValueError):
            PicoDeployTool._validate_image_job(invalid_name)

        invalid_event = ImageJob(Path("photo.png"), ConversionOptions(target="events"), "photo.bin", "25")
        with self.assertRaises(ValueError):
            PicoDeployTool._validate_image_job(invalid_event)


if __name__ == "__main__":
    unittest.main()
