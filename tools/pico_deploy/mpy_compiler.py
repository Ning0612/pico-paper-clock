"""Optional .py -> .mpy bytecode precompilation used by upload_cli.py's --mpy flag.

Kept separate from deployer.py so the plain-.py deploy path (and its tests)
never need mpy-cross installed. Only imported when DeployOptions.compile_mpy
is True.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

EXCLUDE_FROM_COMPILE = frozenset({
    "epaper.py",  # 原廠驅動，保留可讀原始碼方便排查硬體問題
    "main.py",    # 實機驗證：main.mpy 不會被開機流程自動執行，只有手動 import 才會跑；
                  # 必須保留 .py 讓 MicroPython 開機自動載入
})


class MpyCompileError(RuntimeError):
    """Raised when mpy-cross fails to compile a source file."""


def should_compile(path: Path) -> bool:
    return path.suffix.lower() == ".py" and path.name not in EXCLUDE_FROM_COMPILE


def compile_to_mpy(src_py: Path, out_dir: Path, relative_posix: str) -> Path:
    """Compile src_py to .mpy under out_dir, mirroring relative_posix's directory layout.

    relative_posix is the source file's manifest-relative path (e.g. "main.py").
    Returns the path to the produced .mpy file. Raises MpyCompileError on failure.
    """
    try:
        import mpy_cross
    except ImportError as exc:
        raise MpyCompileError(
            "mpy_cross package not installed. Install it with: pip install mpy-cross==1.24.1.post3"
        ) from exc

    out_relative = relative_posix[:-3] + ".mpy" if relative_posix.endswith(".py") else relative_posix + ".mpy"
    out_path = out_dir / out_relative
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        process = mpy_cross.run(
            str(src_py), "-o", str(out_path),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        _stdout, stderr = process.communicate()
    except FileNotFoundError as exc:
        raise MpyCompileError(
            "mpy-cross executable not found. Install it with: pip install mpy-cross==1.24.1.post3"
        ) from exc

    if process.returncode != 0:
        message = stderr.decode("utf-8", errors="replace").strip() if isinstance(stderr, bytes) else str(stderr).strip()
        raise MpyCompileError(f"mpy-cross failed to compile {src_py}: {message or 'unknown error'}")

    return out_path
