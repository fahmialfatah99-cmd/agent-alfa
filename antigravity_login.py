"""Backward-compatibility shim for alfa.integrations.antigravity_login."""

import sys

import alfa.integrations.antigravity_login as _impl
from alfa.integrations.antigravity_login import *  # noqa: F403

sys.modules[__name__] = _impl

if __name__ == "__main__":
    if hasattr(_impl, "main"):
        _impl.main()
