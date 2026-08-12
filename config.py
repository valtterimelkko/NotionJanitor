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


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw is not None and raw != "" else default


def _path_env(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


# Notion
NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_API_BASE = "https://api.notion.com/v1"

# Pi Web UI Internal API summarisation
# The model and thinking level are deliberately fixed in the client and checked
# against the live catalogue so this process cannot silently switch provider.
PI_INTERNAL_API_SOCKET_PATH = _path_env(
    "PI_INTERNAL_API_SOCKET_PATH", "~/.pi-web-ui/internal-api.sock"
)
PI_INTERNAL_API_TOKEN_PATH = _path_env(
    "PI_INTERNAL_API_TOKEN_PATH", "~/.pi-web-ui/internal-api-token"
)
PI_SUMMARISER_CWD = _path_env(
    "PI_SUMMARISER_CWD", str(BASE_DIR / ".runtime" / "summariser")
)
PI_INTERNAL_API_REQUEST_TIMEOUT_SECONDS = _float_env(
    "PI_INTERNAL_API_REQUEST_TIMEOUT_SECONDS", 30.0
)
PI_INTERNAL_API_MAX_WAIT_SECONDS = _float_env(
    "PI_INTERNAL_API_MAX_WAIT_SECONDS", 300.0
)
PI_INTERNAL_API_POLL_INTERVAL_SECONDS = _float_env(
    "PI_INTERNAL_API_POLL_INTERVAL_SECONDS", 1.0
)
PI_SUMMARISER_MAX_CONTENT_CHARS = _int_env(
    "PI_SUMMARISER_MAX_CONTENT_CHARS", 120_000
)

# Telegram
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _int_env("TELEGRAM_CHAT_ID", 0)

# Scanner behaviour
CUTOFF_DAYS = _int_env("CUTOFF_DAYS", 60)
# Per-type limit: applied separately to project-linked notes and orphan notes.
# Total weekly messages = STALE_NOTE_LIMIT * 2.
STALE_NOTE_LIMIT = _int_env("STALE_NOTE_LIMIT", 13)
SCHEDULE_DAY = os.environ.get("SCHEDULE_DAY", "mon")  # APScheduler day name
SCHEDULE_HOUR = _int_env("SCHEDULE_HOUR", 9)
SCHEDULE_MINUTE = _int_env("SCHEDULE_MINUTE", 0)

# State DB
STATE_DB_PATH = Path(os.environ.get("STATE_DB_PATH", str(DATA_DIR / "janitor.db")))

# Logging
LOG_FILE = Path(os.environ.get("LOG_FILE", "/var/log/notion-janitor.log"))
