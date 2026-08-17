> AGENTS.md and CLAUDE.md are byte-identical — same file for different harnesses. Edit AGENTS.md and copy to CLAUDE.md on every change.

# Agent Guide for Notion Janitor

Notion Janitor — weekly Ultimate Brain notes review via Notion + Pi Web UI + Telegram.

## Where things live

| Path | What |
|------|------|
| `config.py` | Runtime configuration (12 env vars: `NOTION_TOKEN`/`DATABASE_ID`, 6× `PI_INTERNAL_API_*`, `TELEGRAM_*`, `CUTOFF_DAYS`/`STALE_NOTE_LIMIT`/`SCHEDULE_*`/`STATE_DB_PATH`/`LOG_FILE`) |
| `logic/scanner.py` | Two-pass stale-notes scanner (linked + orphan, 13 each) → `state.clear_stale_pending(days=13)` → Pi summarise → Telegram |
| `logic/action_handler.py` | Telegram callback handler (Keep / Archive) |
| `clients/pi_summariser.py` | Pi Web UI Internal API — pinned `openai-codex/gpt-5.6-luna` + `medium` thinking, hard-fail on `PROVIDER_NOT_ALLOWED` |
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

`openai-codex/gpt-5.6-luna` (`PI_SUMMARISER_PROVIDER=openai-codex`, `PI_SUMMARISER_MODEL_ID=gpt-5.6-luna`) + `medium` thinking is the only allowed combination. `clients/pi_summariser.py` validates against the live catalogue (`/api/v1/capabilities`, `/api/v1/models?runtime=pi`) at `ensure_ready()`; `PROVIDER_NOT_ALLOWED` / `MODEL_MISMATCH` / `THINKING_LEVEL_MISMATCH` are hard failures, not fallbacks. If Pi Web UI policy blocks the provider, the scanner surfaces `PROVIDER_NOT_ALLOWED` and the scan-failure Telegram alert fires when every note fails.

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
