"""Tests for logging configuration — the log file must rotate, not grow forever."""

import logging
from logging.handlers import RotatingFileHandler

from main import setup_logging


class TestSetupLogging:
    def test_installs_rotating_file_handler(self, tmp_path):
        root = logging.getLogger()
        saved = list(root.handlers)
        try:
            log_file = tmp_path / "notion-janitor.log"
            setup_logging(log_to_file=True, log_file=str(log_file))

            rotating = [
                h for h in root.handlers if isinstance(h, RotatingFileHandler)
            ]
            assert len(rotating) == 1
            assert rotating[0].maxBytes == 5 * 1024 * 1024
            assert rotating[0].backupCount == 5
        finally:
            for h in list(root.handlers):
                h.close()
            root.handlers = saved

    def test_no_file_handler_when_disabled(self):
        root = logging.getLogger()
        saved = list(root.handlers)
        try:
            setup_logging(log_to_file=False)
            assert not any(
                isinstance(h, RotatingFileHandler) for h in root.handlers
            )
        finally:
            for h in list(root.handlers):
                h.close()
            root.handlers = saved
