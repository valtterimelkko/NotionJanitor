"""Central configuration for Notion Janitor."""

import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Notion
NOTION_TOKEN = os.environ.get(
    "NOTION_TOKEN",
    "ntn_your_notion_integration_token_here",
)
NOTION_DATABASE_ID = "your_notes_database_id_here"
NOTION_API_BASE = "https://api.notion.com/v1"

# Kimi API (exact replica of n8n HTTP Request node)
KIMI_API_URL = "https://api.kimi.com/coding/v1/chat/completions"
KIMI_API_KEY = os.environ.get(
    "KIMI_API_KEY",
    "sk-kimi-your_kimi_api_key_here",
)
KIMI_MODEL = "kimi-k2.5-thinking"
KIMI_TEMPERATURE = 0.7
KIMI_MAX_TOKENS = 500

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get(
    "TELEGRAM_BOT_TOKEN",
    "your_telegram_bot_token_here",
)
TELEGRAM_CHAT_ID = 123456789

# Scanner behaviour
CUTOFF_DAYS = 60
STALE_NOTE_LIMIT = 20
SCHEDULE_DAY = "mon"  # APScheduler day name
SCHEDULE_HOUR = 9
SCHEDULE_MINUTE = 0

# State DB
STATE_DB_PATH = DATA_DIR / "janitor.db"

# Logging
LOG_FILE = Path("/var/log/notion-janitor.log")
