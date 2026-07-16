"""Backward-compatible launcher and import alias for the headless deployer."""

import sys

from tools.pico_deploy import upload_cli as _implementation


if __name__ == "__main__":
    raise SystemExit(_implementation.main())

# Keep legacy `import upload` callers connected to the canonical module state.
sys.modules[__name__] = _implementation
