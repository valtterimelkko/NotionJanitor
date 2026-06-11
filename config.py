"""Central configuration for Notion Janitor."""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw is not None and raw != "" else default


# Notion
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_API_BASE = "https://api.notion.com/v1"

# Kimi API
KIMI_API_URL = "https://api.kimi.com/coding/v1/chat/completions"
KIMI_API_KEY = os.environ.get("KIMI_API_KEY", "")
KIMI_MODEL = os.environ.get("KIMI_MODEL", "kimi-k2.5-thinking")
KIMI_TEMPERATURE = float(os.environ.get("KIMI_TEMPERATURE", "0.7"))
KIMI_MAX_TOKENS = _int_env("KIMI_MAX_TOKENS", 500)

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _int_env("TELEGRAM_CHAT_ID", 0)

# Scanner behaviour
CUTOFF_DAYS = _int_env("CUTOFF_DAYS", 60)
STALE_NOTE_LIMIT = _int_env("STALE_NOTE_LIMIT", 20)
SCHEDULE_DAY = os.environ.get("SCHEDULE_DAY", "mon")  # APScheduler day name
SCHEDULE_HOUR = _int_env("SCHEDULE_HOUR", 9)
SCHEDULE_MINUTE = _int_env("SCHEDULE_MINUTE", 0)

# State DB
STATE_DB_PATH = Path(os.environ.get("STATE_DB_PATH", str(DATA_DIR / "janitor.db")))

# Logging
LOG_FILE = Path(os.environ.get("LOG_FILE", "/var/log/notion-janitor.log"))
