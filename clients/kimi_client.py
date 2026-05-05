"""Kimi API client — exact replica of the n8n 'Message a model' HTTP Request node."""

import json
import logging

import requests

from config import KIMI_API_KEY, KIMI_API_URL, KIMI_MAX_TOKENS, KIMI_MODEL, KIMI_TEMPERATURE

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a helpful assistant managing a Notion database. "
    "Provide a 1-sentence summary of what the note is about."
)


class KimiClient:
    """Replicates the n8n HTTP Request node that calls api.kimi.com."""

    def __init__(self):
        self.session = requests.Session()
        # Exact headers from the n8n node
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": "KimiCLI/1.0",
            "Authorization": f"Bearer {KIMI_API_KEY}",
        })

    def summarise_note(self, title: str, content: str) -> str:
        """Send the note to Kimi and return the 1-sentence summary."""
        user_prompt = (
            f"NOTE TITLE: {title}\n\n"
            f"CONTENT BLOCKS:\n{content}\n\n"
            "Provide a 1-sentence summary. "
            "If content is empty or unreadable, say 'No content found'."
        )

        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "model": KIMI_MODEL,
            "temperature": KIMI_TEMPERATURE,
            "max_tokens": KIMI_MAX_TOKENS,
        }

        logger.debug("Kimi request payload: %s", json.dumps(payload)[:500])
        resp = self.session.post(KIMI_API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        try:
            summary = data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            logger.error("Unexpected Kimi response structure: %s", data)
            raise RuntimeError(f"Failed to parse Kimi response: {exc}") from exc

        logger.info("Kimi summary: %s", summary)
        return summary
