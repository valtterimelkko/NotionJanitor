# Notion Janitor

Notion Janitor is a self-hosted weekly cleanup assistant for **Thomas Frank's [Ultimate Brain](https://thomasjfrank.com/brain/)** workspace in Notion.

If you are already using Ultimate Brain to organise your projects, notes, and knowledge, Notion Janitor adds a lightweight review loop that helps keep the Notes database clean over time instead of letting old notes accumulate forever.

## Why this exists

I found Notion — and Ultimate Brain specifically — genuinely powerful as a second-brain system. It gives much richer organisation than lightweight note capture tools, and it works especially well when combined with AI workflows.

But there was still a recurring problem: without a consistent cleanup system, notes pile up.

Before this, I had years of experience with note capture systems where archiving stayed manual and rarely happened. The result was predictable: thousands of old notes, a cluttered workspace, and a second brain that gradually became less useful because it was never gently maintained.

Notion Janitor exists to solve that problem with a small, steady rhythm instead of a giant manual cleanup session.

## What it does

Every Monday morning, Notion Janitor:

- looks for notes that have not been edited recently — in **two separate passes**: one for notes linked to a project, one for orphan notes with no project
- applies a per-pass cap so the weekly review stays manageable
- generates a short AI summary for each candidate note
- sends the review items to a dedicated Telegram chat
- lets you decide note by note whether to **Keep** or **Archive**

The idea is not to automate your judgement away. The idea is to make good housekeeping easy enough that it actually happens.

## Designed specifically for Ultimate Brain

This tool is built for the structure and logic of Ultimate Brain.

Important detail:
- it does **not** use Notion's generic page-archive behaviour as its main cleanup mechanism
- instead, it updates the **`Archived` checkbox/property** used by the Ultimate Brain system itself

That means the workflow stays aligned with how Ultimate Brain expects notes to be organised.

If you use Ultimate Brain together with AI tooling, you may also want the companion repo:
- [`claude-code-integr-ultimate-brain`](https://github.com/valtterimelkko/claude-code-integr-ultimate-brain)

That repo focuses on AI access and editing workflows for Ultimate Brain, while Notion Janitor focuses on long-term cleanliness and review discipline. They can be used independently, but they also work well together as a package.

## How the review loop works

Current default behaviour:

- notes become candidates after **60 days** without edits
- the scanner runs **two sub-queries per week**: one for project-linked notes, one for orphan notes (no Project relation)
- each sub-query is capped at **13 notes**, giving up to **26 review messages per week** in total
- notes are reviewed via **Telegram buttons** in a dedicated chat
- the service is **self-hosted** and uses Telegram only as the review surface

### Why two sub-queries?

A single oldest-first query with a cap of 20 silently hides orphan notes whenever there are 20+ stale project-linked notes. In practice, project-linked notes tend to accumulate a larger backlog, so orphans — quick-capture notes that were never attached to a project — would never surface at all.

Running separate queries guarantees that orphan notes always get a slot in every weekly review, regardless of how large the project-linked backlog grows.

### If you choose Archive

Notion Janitor marks the note using Ultimate Brain's own `Archived` property.

### If you choose Keep

Notion Janitor appends a small “kept via Telegram review” block to the note.

That matters because it updates the note's `last_edited_time`, which means the same note will not immediately reappear in the next weekly review cycle. In practice, this creates a gentle snooze/reset behaviour while still leaving a visible record that the note was intentionally kept.

## Why this started in n8n and moved to code

This workflow originally existed as n8n automation.

That version proved the concept, but over time I wanted something more inspectable, easier to maintain in version control, and less constrained by workflow-builder limitations. So the system was rewritten as a small Python application while keeping the same core weekly scanner + action handler model.

## Architecture at a glance

```text
APScheduler weekly cron
  -> query Ultimate Brain Notes database in Notion (two passes)
       pass 1: project-linked notes  (oldest 13, sorted oldest-first)
       pass 2: orphan notes          (oldest 13, no Project relation)
  -> summarise each note with Kimi
  -> send Telegram review message with Keep / Archive buttons

Telegram callback polling
  -> receive button click
  -> archive note OR append kept marker block
  -> update local SQLite state
```

## Repository structure

```text
clients/     Notion, Telegram, and Kimi API clients
logic/       Weekly scanner and action handler
tests/       Unit tests for scanner, state, and callbacks
systemd/     Example service file
config.py    Runtime configuration
main.py      Scheduler + Telegram polling entrypoint
state.py     Local SQLite state tracking
```

## Quick start

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Configure environment:

```bash
cp .env.example .env
# fill in your real values
# for a local shell run: set -a; source .env; set +a
```

Run once for testing:

```bash
python3 main.py --dry-run --run-once
```

Run tests:

```bash
python3 -m pytest -q
```

## Documentation map

- [`docs/MAINTAINER-RUNBOOK.md`](docs/MAINTAINER-RUNBOOK.md) — maintainer-oriented operational notes preserved from the original private README
- [`systemd/notion-janitor.service`](systemd/notion-janitor.service) — example service unit (loads `/root/notionjanitor/.env` in the original self-hosted setup)

## Notes for public users

This project was built for a real self-hosted Ultimate Brain workflow. Some implementation details therefore assume that specific workspace model. That is intentional: this is a focused automation for people already using Ultimate Brain, not a generic Notion-cleanup product for every workspace shape.

## License

MIT
