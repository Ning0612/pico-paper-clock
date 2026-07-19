"""Serial deployment primitives shared by the desktop GUI and upload CLI."""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


class DeploymentError(RuntimeError):
    """Raised when a serial deployment cannot be completed."""


class DeploymentCancelled(DeploymentError):
    """Raised when the user cancels a deployment."""


class CancellationToken:
    """Small thread-safe cancellation primitive used by worker jobs."""

    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self):
        if self.cancelled:
            raise DeploymentCancelled("Deployment cancelled by user.")


@dataclass(frozen=True)
class DeployOptions:
    """Selection and safety settings for one serial deployment."""

    source_root: Path
    include_code: bool = True
    include_config: bool = False
    include_images: bool = True
    include_webui: bool = True
    clean_mode: str = "none"
    reset_after: bool = True

    def __post_init__(self):
        if self.clean_mode not in ("none", "manifest", "recursive"):
            raise ValueError("clean_mode must be 'none', 'manifest', or 'recursive'.")
        if self.clean_mode == "recursive" and not self.include_config:
            raise ValueError("Recursive cleanup requires explicit config inclusion.")


@dataclass(frozen=True)
class DeployEntry:
    local_path: Path
    remote_path: str
    size: int
    category: str


@dataclass(frozen=True)
class DeployPlan:
    source_root: Path
    entries: tuple[DeployEntry, ...]

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.entries)


@dataclass(frozen=True)
class DeploymentProgress:
    stage: str
    completed_files: int
    total_files: int
    completed_bytes: int
    total_bytes: int
    remote_path: str = ""
    message: str = ""


ProgressCallback = Callable[[DeploymentProgress], None]
LogCallback = Callable[[str], None]


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.2f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


def _add_files(
    entries: list[DeployEntry],
    root: Path,
    directory: Path,
    suffixes: Iterable[str],
    category: str,
):
    if not directory.is_dir():
        return
    allowed = tuple(suffixes)
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or not path.name.endswith(allowed):
            continue
        relative = path.relative_to(root).as_posix()
        entries.append(DeployEntry(path, relative, path.stat().st_size, category))


def build_deploy_plan(options: DeployOptions) -> DeployPlan:
    """Build a stable manifest without touching the device."""

    project_root = Path(options.source_root).expanduser().resolve()
    source_dir = project_root / "src"
    if not source_dir.is_dir():
        raise DeploymentError(f"Project directory must contain src/: {project_root}")

    entries: list[DeployEntry] = []
    if options.include_code:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in (".py", ".json"):
                continue
            if path.name == "config.json":
                continue
            relative = path.relative_to(source_dir).as_posix()
            entries.append(DeployEntry(path, relative, path.stat().st_size, "code"))

    if options.include_config:
        config_path = source_dir / "config.json"
        if config_path.is_file():
            entries.append(DeployEntry(config_path, "config.json", config_path.stat().st_size, "config"))

    if options.include_images:
        _add_files(entries, source_dir, source_dir / "image", (".bin",), "images")

    if options.include_webui:
        _add_files(entries, source_dir, source_dir / "html", (".bin",), "webui")

    entries.sort(key=lambda entry: entry.remote_path)
    return DeployPlan(project_root, tuple(entries))


class MpremoteRunner:
    """Cancellable, non-shell mpremote command runner."""

    def __init__(self, port: str | None = None, executable: str | None = None):
        if executable:
            command = executable
        else:
            command = shutil.which("mpremote")
            if not command:
                candidate = Path(sys.executable).with_name("mpremote.exe")
                command = str(candidate) if candidate.exists() else "mpremote"
        self.base_command = [command, "connect", port] if port else [command]
        self._process: subprocess.Popen | None = None

    def run(
        self,
        arguments: Iterable[str],
        cancellation: CancellationToken | None = None,
        check: bool = True,
    ) -> str:
        if cancellation:
            cancellation.raise_if_cancelled()
        command = self.base_command + list(arguments)
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )
            process = self._process
            while True:
                if cancellation and cancellation.cancelled:
                    process.terminate()
                    process.wait(timeout=3)
                    raise DeploymentCancelled("Deployment cancelled by user.")
                try:
                    stdout, stderr = process.communicate(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except FileNotFoundError as exc:
            raise DeploymentError("mpremote was not found. Install it with: pip install mpremote") from exc
        finally:
            self._process = None

        if check and process.returncode != 0:
            raise DeploymentError(stderr.strip() or stdout.strip() or "mpremote command failed.")
        return (stdout or "").strip()


class SerialDeployer:
    """Execute a previously reviewed deployment plan."""

    def __init__(self, runner: MpremoteRunner):
        self.runner = runner

    def deploy(
        self,
        plan: DeployPlan,
        options: DeployOptions,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
    ) -> DeployPlan:
        if not plan.entries:
            raise DeploymentError("The deployment manifest is empty.")
        if options.clean_mode == "manifest":
            self._clean_manifest(plan, cancellation, log)
        elif options.clean_mode == "recursive":
            if log:
                log("Warning: recursively removing device files before deployment.")
            self.runner.run(["fs", "rm", "-r", ":"], cancellation=cancellation)

        created_dirs: set[str] = set()
        completed_bytes = 0
        total_files = len(plan.entries)
        for index, entry in enumerate(plan.entries, start=1):
            if cancellation:
                cancellation.raise_if_cancelled()
            parent = entry.remote_path.rsplit("/", 1)[0] if "/" in entry.remote_path else ""
            self._ensure_remote_dirs(parent, created_dirs, cancellation)
            self._emit(progress, DeploymentProgress(
                "upload", index - 1, total_files, completed_bytes, plan.total_size,
                entry.remote_path, f"Uploading {entry.remote_path}",
            ))
            self.runner.run(["fs", "cp", str(entry.local_path), f":{entry.remote_path}"], cancellation=cancellation)
            completed_bytes += entry.size
            self._emit(progress, DeploymentProgress(
                "upload", index, total_files, completed_bytes, plan.total_size,
                entry.remote_path, f"Uploaded {entry.remote_path}",
            ))
            if log:
                log(f"Uploaded {entry.remote_path} ({format_bytes(entry.size)})")

        if options.reset_after:
            if cancellation:
                cancellation.raise_if_cancelled()
            self.runner.run(["reset"], cancellation=cancellation)
            self._emit(progress, DeploymentProgress(
                "reset", total_files, total_files, completed_bytes, plan.total_size,
                message="Device reset requested.",
            ))
        return plan

    def _ensure_remote_dirs(self, path, created_dirs, cancellation):
        current = ""
        for part in path.split("/"):
            if not part:
                continue
            current = f"{current}/{part}" if current else part
            if current in created_dirs:
                continue
            self.runner.run(["fs", "mkdir", f":{current}"], cancellation=cancellation, check=False)
            created_dirs.add(current)

    def _clean_manifest(
        self,
        plan: DeployPlan,
        cancellation: CancellationToken | None,
        log: LogCallback | None,
    ):
        for entry in plan.entries:
            if cancellation:
                cancellation.raise_if_cancelled()
            self.runner.run(["fs", "rm", f":{entry.remote_path}"], cancellation=cancellation, check=False)
            if log:
                log(f"Removed existing {entry.remote_path}")

    @staticmethod
    def _emit(progress: ProgressCallback | None, event: DeploymentProgress):
        if progress:
            progress(event)
