"""Weekly Scanner logic — replaces n8n Workflow 1."""

import logging
from datetime import datetime, timezone, timedelta

from clients.kimi_client import KimiClient
from clients.notion_client import NotionClient
from clients.telegram_client import TelegramClient
from config import CUTOFF_DAYS, STALE_NOTE_LIMIT
from state import StateStore

logger = logging.getLogger(__name__)


class WeeklyScanner:
    """Finds stale notes, summarises them, and sends Telegram review messages."""

    def __init__(self, dry_run: bool = False):
        self.notion = NotionClient()
        self.kimi = KimiClient()
        self.telegram = TelegramClient()
        self.state = StateStore()
        self.dry_run = dry_run

    def _calculate_cutoff(self) -> str:
        """Return ISO8601 timestamp for *cutoff* days ago (UTC)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
        return cutoff.isoformat().replace("+00:00", "Z")

    async def run(self) -> dict:
        """Execute one full scan cycle.

        Two separate queries run each week — one for project-linked notes and
        one for orphan notes (no Project relation) — each capped at
        STALE_NOTE_LIMIT. This guarantees orphans always get reviewed and are
        never silently crowded out by the project-linked backlog.

        Returns a summary dict for logging / testing.
        """
        # Clean up very old pending reviews (user never clicked) before scanning.
        # Use a 13-day cutoff to avoid scheduling/seconds race conditions.
        cleared = self.state.clear_stale_pending(days=13)

        started_at_dt = datetime.now(timezone.utc)
        started_at = started_at_dt.isoformat()

        cutoff_iso = self._calculate_cutoff()
        logger.info("Starting weekly scan — cutoff: %s", cutoff_iso)

        # 1. Fetch stale notes — project-linked and orphans as separate queries
        linked_notes = self.notion.get_stale_notes(
            cutoff_iso, limit=STALE_NOTE_LIMIT, orphans_only=False
        )
        orphan_notes = self.notion.get_stale_notes(
            cutoff_iso, limit=STALE_NOTE_LIMIT, orphans_only=True
        )
        all_notes = linked_notes + orphan_notes

        if not all_notes:
            logger.info("No stale notes found. Nothing to do.")
            return {
                "scanned": 0,
                "scanned_linked": 0,
                "scanned_orphans": 0,
                "sent": 0,
                "errors": 0,
                "cleared_stale": cleared,
            }

        logger.info(
            "Candidates: %d linked + %d orphans = %d total",
            len(linked_notes), len(orphan_notes), len(all_notes),
        )

        sent_count = 0
        error_count = 0

        for note in all_notes:
            note_id = note["id"]

            # Skip if already pending review (prevents duplicates within the same week)
            if self.state.is_pending(note_id):
                logger.info("Skipping note %s — already pending review", note_id)
                continue

            try:
                did_send = await self._process_one_note(note)
                if did_send:
                    sent_count += 1
            except Exception as exc:
                logger.exception("Failed to process note %s: %s", note_id, exc)
                error_count += 1

        summary = {
            "scanned": len(all_notes),
            "scanned_linked": len(linked_notes),
            "scanned_orphans": len(orphan_notes),
            "sent": sent_count,
            "errors": error_count,
            "cleared_stale": cleared,
        }
        logger.info("Weekly scan complete: %s", summary)

        # Persist this run's outcome for trend/health analysis. Recorded before
        # the alert so last_successful_scan() correctly excludes this failed run.
        duration_s = (datetime.now(timezone.utc) - started_at_dt).total_seconds()
        self.state.record_scan_run(summary, started_at, duration_s, dry_run=self.dry_run)

        # Surface a total failure to the user. Without this, an upstream outage
        # (e.g. the summariser rejecting every note, as happened with the Kimi
        # temperature regression) is indistinguishable from "nothing to review"
        # — the janitor simply goes silent.
        if not self.dry_run and sent_count == 0 and error_count > 0:
            await self._alert_scan_failure(len(all_notes), error_count)

        return summary

    async def _alert_scan_failure(self, total: int, errors: int) -> None:
        """Best-effort Telegram ping when a scan sends nothing despite candidates.

        Never raises — a failure to deliver the alert must not break the scan
        or the scheduler job that called it.
        """
        try:
            last = self.state.last_successful_scan()
        except Exception:
            last = None
        if last:
            last_line = (
                f"\n\nLast successful scan: {last['finished_at']} "
                f"({last['sent']} messages sent)."
            )
        else:
            last_line = "\n\nNo successful scan has been recorded yet."

        text = (
            "⚠️ <b>Notion Janitor — scan problem</b>\n\n"
            f"Today's scan found {total} stale note(s) but sent <b>0</b> review "
            f"messages ({errors} failed to process).{last_line}\n\n"
            "This usually means an upstream API (Kimi/Notion) or a config value "
            "is rejecting requests. The scheduler itself is fine — check the "
            "service logs: journalctl -u notion-janitor"
        )
        try:
            await self.telegram.send_alert(text)
        except Exception as exc:
            logger.error("Failed to send scan-failure alert: %s", exc)

    async def _process_one_note(self, note: dict) -> bool:
        """Summarise a single note and send the Telegram review message.

        Returns True if a message was actually sent, False in dry-run mode.
        """
        note_id = note["id"]
        title_parts = (
            note.get("properties", {})
            .get("Name", {})
            .get("title", [])
        )
        title = title_parts[0].get("plain_text", "Untitled") if title_parts else "Untitled"

        # Get project name (mirrors n8n "Get Project" node)
        project = self.notion.get_project_name(note)

        # Get content blocks (mirrors n8n "Get Content" node)
        blocks = self.notion.get_block_children(note_id)
        content_text = self.notion.flatten_blocks_text(blocks)

        if self.dry_run:
            logger.info(
                "[DRY RUN] Would review: %s | Project: %s | Blocks: %d",
                title, project, len(blocks),
            )
            return False

        # Generate summary via Kimi (mirrors n8n "Message a model")
        summary = self.kimi.summarise_note(title, content_text)

        # Send Telegram review message (mirrors n8n "Send a text message")
        message_id = await self.telegram.send_review_message(
            note_id=note_id,
            title=title,
            project=project,
            summary=summary,
        )

        # Record in local state so we don't resend it this week
        self.state.add_pending(note_id, title, project, summary, message_id)
        return True
