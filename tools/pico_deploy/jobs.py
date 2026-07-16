"""Sequential background jobs for the desktop tool."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from .deployer import CancellationToken, DeploymentCancelled


JobAction = Callable[[CancellationToken, Callable[[str], None]], None]
JobUpdate = Callable[["Job"], None]


@dataclass
class Job:
    title: str
    action: JobAction
    status: str = "pending"
    error: str = ""
    logs: list[str] = field(default_factory=list)


class JobQueue:
    """Run queued jobs sequentially while keeping Tkinter responsive."""

    def __init__(self, on_update: JobUpdate | None = None):
        self.jobs: list[Job] = []
        self.on_update = on_update
        self.cancellation = CancellationToken()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def add(self, job: Job):
        if self.running:
            raise RuntimeError("Cannot add jobs while the queue is running.")
        self.jobs.append(job)
        self._notify(job)

    def start(self):
        if self.running:
            return
        pending = [job for job in self.jobs if job.status in ("pending", "failed")]
        if not pending:
            raise RuntimeError("The queue has no pending jobs.")
        self.cancellation = CancellationToken()
        self._thread = threading.Thread(target=self._run, args=(pending,), daemon=True)
        self._thread.start()

    def cancel(self):
        self.cancellation.cancel()

    def clear_finished(self):
        if self.running:
            raise RuntimeError("Cannot clear jobs while the queue is running.")
        self.jobs = [job for job in self.jobs if job.status not in ("success", "cancelled")]

    def _run(self, pending: list[Job]):
        for job in pending:
            if self.cancellation.cancelled:
                job.status = "cancelled"
                self._notify(job)
                break
            job.status = "running"
            job.error = ""
            job.logs.clear()
            self._notify(job)
            try:
                job.action(self.cancellation, lambda message: self._log(job, message))
            except DeploymentCancelled as exc:
                job.status = "cancelled"
                job.error = str(exc)
                self._notify(job)
                break
            except Exception as exc:  # worker errors must reach the UI, not kill the process
                job.status = "failed"
                job.error = str(exc)
                self._notify(job)
                break
            else:
                job.status = "success"
                self._notify(job)

    def _log(self, job: Job, message: str):
        job.logs.append(message)
        self._notify(job)

    def _notify(self, job: Job):
        if self.on_update:
            self.on_update(job)
