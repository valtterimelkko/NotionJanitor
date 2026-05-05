# Notion Janitor

Local Python automation for Notion Second Brain (Ultimate Brain) cleanup.
Replaces the previous n8n-based Weekly Scanner + Action Taker workflows.

## What it does

- **Weekly Scanner**: Every Monday at 09:00, finds up to 20 stale notes (not edited in 60+ days), generates an AI summary, and sends a Telegram review message with Keep/Archive buttons.
- **Action Taker**: Listens for Telegram button clicks via long-polling (no webhooks), then either archives the note or appends a "kept" timestamp block.

## Stack

- Python 3.12
- `python-telegram-bot` (polling-based, no webhook headaches)
- `requests` (Notion + Kimi APIs)
- `apscheduler` (Monday 09:00 scheduling)
- `sqlite3` (local state tracking)
- `systemd` service for auto-start
