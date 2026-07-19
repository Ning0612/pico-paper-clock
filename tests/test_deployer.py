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
