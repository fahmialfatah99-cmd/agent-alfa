#!/usr/bin/env python3
"""Backward-compatibility shim for alfa.bot."""
import sys
from alfa.bot import telegram_bot as _impl
from alfa.bot.telegram_bot import *  # noqa: F403

sys.modules["bot"] = _impl
if __name__ != "__main__":
    sys.modules[__name__] = _impl

if __name__ == "__main__":
    from alfa.bot.telegram_bot import main
    main()
