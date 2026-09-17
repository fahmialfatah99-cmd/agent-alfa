"""Backward-compatibility shim for alfa.tools.filesystem.universal_file_extractor."""

import sys

import alfa.tools.filesystem.universal_file_extractor as _impl
from alfa.tools.filesystem.universal_file_extractor import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
