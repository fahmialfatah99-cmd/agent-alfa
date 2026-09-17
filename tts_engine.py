"""Backward-compatibility shim for alfa.media.tts_engine."""

import sys

import alfa.media.tts_engine as _impl
from alfa.media.tts_engine import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
