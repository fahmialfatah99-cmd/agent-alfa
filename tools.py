"""Backward-compatibility shim for alfa.tools.

All tools are now organized in the modular package `alfa.tools`.
"""

import sys
import alfa.tools as _impl
from alfa.tools import *  # noqa: F401, F403

sys.modules[__name__] = _impl
