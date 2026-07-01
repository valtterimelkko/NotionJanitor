"""Unit tests for StateStore."""

import tempfile
from pathlib import Path

from state import StateStore


class TestStateStore:
    def test_add_and_remove_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            store = StateStore(db_path=db)

            assert not store.is_pending("note-1")

            store.add_pending("note-1", "Title A", "Proj X", "Summary", 100)
            assert store.is_pending("note-1")

            row = store.remove_pending("note-1")
            assert row is not None
            assert row["note_title"] == "Title A"
            assert not store.is_pending("note-1")

    def test_attempts_increment(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            store = StateStore(db_path=db)

            store.add_pending("note-1", "T", "P", "S", 1)
            store.add_pending("note-1", "T", "P", "S", 2)

            row = store.remove_pending("note-1")
            assert row["attempts"] == 2

    def test_record_processed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "test.db"
            store = StateStore(db_path=db)

            store.record_processed("note-1", "archived")
            store.record_processed("note-1", "kept")  # update

            with store._conn() as conn:
                row = conn.execute(
                    "SELECT action FROM processed_notes WHERE note_id = ?", ("note-1",)
                ).fetchone()
                assert row[0] == "kept"


class TestScanRuns:
    """Per-run history and the last-successful-scan health signal."""

    def _summary(self, **over):
        base = {
            "scanned": 10,
            "scanned_linked": 6,
            "scanned_orphans": 4,
            "sent": 5,
            "errors": 0,
            "cleared_stale": 0,
        }
        base.update(over)
        return base

    def test_no_runs_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(db_path=Path(tmp) / "t.db")
            assert store.last_successful_scan() is None

    def test_excludes_failed_and_dry_runs_returns_latest_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(db_path=Path(tmp) / "t.db")

            # A total-failure run (sent 0) is not a success.
            store.record_scan_run(self._summary(sent=0, errors=5), "2026-06-22T09:00:00Z", 30.0)
            assert store.last_successful_scan() is None

            # A dry-run is never a real success either.
            store.record_scan_run(self._summary(sent=0), "2026-06-22T09:01:00Z", 1.0, dry_run=True)
            assert store.last_successful_scan() is None

            # First real success.
            store.record_scan_run(self._summary(sent=5), "2026-06-29T09:00:00Z", 40.0)
            last = store.last_successful_scan()
            assert last is not None and last["sent"] == 5

            # A later success supersedes it.
            store.record_scan_run(self._summary(sent=3), "2026-07-06T09:00:00Z", 35.0)
            last = store.last_successful_scan()
            assert last is not None and last["sent"] == 3
