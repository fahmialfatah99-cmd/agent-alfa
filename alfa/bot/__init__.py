"""ALFA Bot: Telegram AI agent and interface handlers."""
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from alfa.bot import telegram_bot
from alfa.bot.telegram_bot import *  # noqa: F401, F403
