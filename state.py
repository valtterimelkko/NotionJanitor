"""Local SQLite state tracking for pending reviews and attempt counts."""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from config import STATE_DB_PATH

logger = logging.getLogger(__name__)

INIT_SQL = """
CREATE TABLE IF NOT EXISTS pending_reviews (
    note_id      TEXT PRIMARY KEY,
    note_title   TEXT NOT NULL,
    project_name TEXT,
    summary      TEXT,
    message_id   INTEGER,
    sent_at      TEXT NOT NULL,
    attempts     INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS processed_notes (
    note_id      TEXT PRIMARY KEY,
    action       TEXT NOT NULL,  -- 'archived' | 'kept'
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT NOT NULL,
    duration_s      REAL,
    scanned         INTEGER DEFAULT 0,
    scanned_linked  INTEGER DEFAULT 0,
    scanned_orphans INTEGER DEFAULT 0,
    sent            INTEGER DEFAULT 0,
    errors          INTEGER DEFAULT 0,
    cleared_stale   INTEGER DEFAULT 0,
    dry_run         INTEGER DEFAULT 0  -- 1 if the run was a --dry-run
);
"""


class StateStore:
    """Simple SQLite store to prevent duplicate sends and track history."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or STATE_DB_PATH
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(INIT_SQL)
        logger.info("State DB initialised at %s", self.db_path)

    # ------------------------------------------------------------------
    # Pending reviews
    # ------------------------------------------------------------------
    def is_pending(self, note_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM pending_reviews WHERE note_id = ?", (note_id,)
            ).fetchone()
            return row is not None

    def add_pending(
        self,
        note_id: str,
        note_title: str,
        project_name: str,
        summary: str,
        message_id: int,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO pending_reviews (note_id, note_title, project_name, summary, message_id, sent_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(note_id) DO UPDATE SET
                    attempts = attempts + 1,
                    sent_at = excluded.sent_at,
                    message_id = excluded.message_id
                """,
                (note_id, note_title, project_name, summary, message_id, datetime.now(timezone.utc).isoformat()),
            )
        logger.info("Marked note %s as pending (msg_id=%s)", note_id, message_id)

    def remove_pending(self, note_id: str) -> Optional[dict]:
        """Remove from pending and return the row (for message_id, etc.)."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM pending_reviews WHERE note_id = ?", (note_id,)
            ).fetchone()
            if row:
                conn.execute(
                    "DELETE FROM pending_reviews WHERE note_id = ?", (note_id,)
                )
                keys = [d[1] for d in conn.execute(
                    "PRAGMA table_info(pending_reviews)"
                ).fetchall()]
                return dict(zip(keys, row))
            return None

    def get_pending(self) -> list[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM pending_reviews").fetchall()
            return [dict(r) for r in rows]

    def clear_stale_pending(self, days: int = 13) -> int:
        """Remove pending reviews older than *days* (e.g. user never clicked)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM pending_reviews WHERE sent_at < ?", (cutoff,)
            )
            deleted = cur.rowcount
        if deleted:
            logger.info("Cleared %d stale pending reviews", deleted)
        return deleted

    # ------------------------------------------------------------------
    # Processed history
    # ------------------------------------------------------------------
    def record_processed(self, note_id: str, action: str) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO processed_notes (note_id, action, processed_at)
                VALUES (?, ?, ?)
                ON CONFLICT(note_id) DO UPDATE SET
                    action = excluded.action,
                    processed_at = excluded.processed_at
                """,
                (note_id, action, datetime.now(timezone.utc).isoformat()),
            )
        logger.info("Recorded note %s as %s", note_id, action)

    # ------------------------------------------------------------------
    # Scan run history (observability)
    # ------------------------------------------------------------------
    def record_scan_run(
        self,
        summary: dict,
        started_at: str,
        duration_s: float,
        dry_run: bool = False,
    ) -> None:
        """Persist the outcome of one scan cycle for trend/health analysis."""
        finished_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO scan_runs
                    (started_at, finished_at, duration_s, scanned, scanned_linked,
                     scanned_orphans, sent, errors, cleared_stale, dry_run)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    finished_at,
                    duration_s,
                    summary.get("scanned", 0),
                    summary.get("scanned_linked", 0),
                    summary.get("scanned_orphans", 0),
                    summary.get("sent", 0),
                    summary.get("errors", 0),
                    summary.get("cleared_stale", 0),
                    int(dry_run),
                ),
            )
        logger.info("Recorded scan run: %s", summary)

    def last_successful_scan(self) -> Optional[dict]:
        """Most recent non-dry run that actually sent review messages.

        Returns None if no successful run has been recorded. Used as a health
        signal: if this is stale (or None) while scans keep running, something
        upstream is rejecting every note.
        """
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT * FROM scan_runs
                WHERE sent > 0 AND dry_run = 0
                ORDER BY finished_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None
