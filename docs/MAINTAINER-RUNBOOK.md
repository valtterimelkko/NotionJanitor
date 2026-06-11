# Maintainer Runbook

This document preserves the original maintainer-facing operational notes that used to live in the root README.

Use the public [`../README.md`](../README.md) for project overview, story, and adoption. Use this file for the original self-hosted operational workflow.

## Original summary

Notion Janitor is local Python automation for Ultimate Brain cleanup.
It replaced the earlier n8n-based Weekly Scanner + Action Taker workflows.

## Core behaviour

- **Weekly Scanner**: every Monday at 09:00, run two sub-queries against the Notes database:
  - **Pass 1 — project-linked notes**: up to `STALE_NOTE_LIMIT` (default 13) stale notes that have a Project relation, sorted oldest-first
  - **Pass 2 — orphan notes**: up to `STALE_NOTE_LIMIT` stale notes with *no* Project relation, sorted oldest-first
  - Results from both passes are summarised by Kimi and sent as Telegram review messages (up to `STALE_NOTE_LIMIT * 2 = 26` per week)
- **Action Taker**: listen for Telegram button clicks via long polling, then archive the note or append a kept marker block

### Why two sub-queries?

A single oldest-first query silently excludes orphan notes (quick captures never linked to a project) when the project-linked backlog exceeds the cap. Separate queries guarantee orphans always appear in each weekly review.

## Stack

- Python 3.12
- `python-telegram-bot`
- `requests`
- `apscheduler`
- `sqlite3`
- `systemd`

## Typical local commands

Run once in dry-run mode:

```bash
cd /root/notionjanitor
python3 main.py --dry-run --run-once
```

Run tests:

```bash
cd /root/notionjanitor
python3 -m pytest -q
```

## Local state

The app keeps a small SQLite state DB locally to track:
- pending review messages
- processed notes

This prevents duplicate sends within the same review window and records whether a note was kept or archived.

## Service shape

The original self-hosted deployment used the example unit in:

- `systemd/notion-janitor.service`

That unit expects local secrets/config in:

- `/root/notionjanitor/.env`

and runs the app as a long-lived polling service.
