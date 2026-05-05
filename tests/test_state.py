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
