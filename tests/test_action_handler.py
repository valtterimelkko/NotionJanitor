"""Unit tests for ActionHandler callback parsing."""

import pytest

from logic.action_handler import ActionHandler


class TestParseCallback:
    def test_keep_parsing(self):
        handler = ActionHandler(dry_run=True)
        result = handler.parse_callback(
            "keep:abc123",
            "🗑 Stale Note Review\n\nTitle: My Test Note\nProject: Serveri\n\nSummary: A note about testing",
        )
        assert result["action"] == "keep"
        assert result["note_id"] == "abc123"
        assert result["title"] == "My Test Note"

    def test_archive_parsing(self):
        handler = ActionHandler(dry_run=True)
        result = handler.parse_callback(
            "archive:xyz789",
            "🗑 Stale Note Review\n\nTitle: Another Note\nProject: n8n\n\nSummary: Some summary",
        )
        assert result["action"] == "archive"
        assert result["note_id"] == "xyz789"
        assert result["title"] == "Another Note"

    def test_fallback_title(self):
        handler = ActionHandler(dry_run=True)
        result = handler.parse_callback("keep:123", "No title here at all")
        assert result["title"] == "this note"

    def test_malformed_callback(self):
        handler = ActionHandler(dry_run=True)
        result = handler.parse_callback("garbage", "Title: Note\n")
        assert result["action"] == "garbage"
        assert result["note_id"] == ""
