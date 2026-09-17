"""Backward-compatibility shim for alfa.tools.filesystem.lsp_code_intelligence."""

import sys

import alfa.tools.filesystem.lsp_code_intelligence as _impl
from alfa.tools.filesystem.lsp_code_intelligence import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
