$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Standard project .venv is missing. Create .venv\Scripts\python.exe and install requirements-dev.txt first."
}
Push-Location $root
try {
    & $python -m PyInstaller --noconfirm --clean --distpath dist --workpath build tools\PicoPaperClockTool.spec
} finally {
    Pop-Location
}
