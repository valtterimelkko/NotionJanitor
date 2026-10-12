> AGENTS.md and CLAUDE.md are byte-identical — same file for different harnesses. Edit AGENTS.md and copy to CLAUDE.md on every change.

# Agent Guide for Notion Janitor

Notion Janitor — weekly Ultimate Brain notes review via Notion + Pi Web UI + Telegram.

## Where things live

| Path | What |
|------|------|
| `config.py` | Runtime configuration (12 env vars: `NOTION_TOKEN`/`DATABASE_ID`, 6× `PI_INTERNAL_API_*`, `TELEGRAM_*`, `CUTOFF_DAYS`/`STALE_NOTE_LIMIT`/`SCHEDULE_*`/`STATE_DB_PATH`/`LOG_FILE`) |
| `logic/scanner.py` | Two-pass stale-notes scanner (linked + orphan, 13 each) → `state.clear_stale_pending(days=13)` → Pi summarise → Telegram |
| `logic/action_handler.py` | Telegram callback handler (Keep / Archive) |
| `clients/pi_summariser.py` | Pi Web UI Internal API — pinned `zai/glm-5.3-flash` + `low` thinking, hard-fail on `PROVIDER_NOT_ALLOWED` |
| `clients/notion_client.py` | Notion API (`get_stale_notes`, `get_block_children`, etc.) |
| `clients/telegram_client.py` | Telegram bot (polling + send) |
| `state.py` | SQLite state (`pending_reviews`, `processed_notes`, `scan_runs`), `clear_stale_pending(days=13)` default, `STATE_DB_PATH=data/janitor.db` |
| `diagnose_orphans.py` | One-liner orphan diagnostic: `set -a; source .env; set +a; python3 diagnose_orphans.py` |
| `main.py` | Entrypoint: APScheduler (mon 09:00 `Etc/UTC`) + Telegram polling |
| `systemd/notion-janitor.service` | Example systemd unit (loads `/root/notionjanitor/.env`) |
| `docs/OBSERVABILITY.md` | Log sinks, `scan_runs`, failure alert, diagnostic playbook |
| `docs/MAINTAINER-RUNBOOK.md` | Operational commands preserved from private README |

## Stale-day contract

Code and docs agree on **13 days** for `clear_stale_pending` — `scanner.py` calls `clear_stale_pending(days=13)` and `state.py` defaults to `13`. Historical drift to `14` has been corrected; keep it at `13`.

## Pi model pin

`zai/glm-5.3-flash` (constants `PI_SUMMARISER_PROVIDER=zai`, `PI_SUMMARISER_MODEL_ID=glm-5.3-flash` in `clients/pi_summariser.py`) + `low` thinking is the only allowed combination (glm-5.3-flash offers only low/high/max, so `medium` is unavailable). Switched from `openai-codex/gpt-5.6-luna` on 2026-10-12 by owner decision after Pi's openai-codex login expired (every run came back `no-text`; Pi Web UI reports a provider auth error as a completed run with no text). Code changes need a `notion-janitor` service restart to take effect. `clients/pi_summariser.py` validates against the live catalogue (`/api/v1/capabilities`, `/api/v1/models?runtime=pi`) at `ensure_ready()`; `PROVIDER_NOT_ALLOWED` / `MODEL_MISMATCH` / `THINKING_LEVEL_MISMATCH` are hard failures, not fallbacks. If Pi Web UI policy blocks the provider, the scanner surfaces `PROVIDER_NOT_ALLOWED` and the scan-failure Telegram alert fires when every note fails.

## Config table

See `README.md` § Configuration for the 16-row env-var table with defaults.

## Testing

```bash
python3 -m pytest -q
.venv/bin/ruff check .
set -a; source .env; set +a; .venv/bin/python main.py --dry-run --run-once
timeout --foreground 900 .venv/bin/python main.py --run-once   # live, sends Telegram
```

## Commit & push

```bash
cd /root/notionjanitor
git add -A
git commit -m "docs: update M365/infra docs, sync AGENTS/CLAUDE"
git push origin main
```

Copy `AGENTS.md` → `CLAUDE.md` on every edit.
