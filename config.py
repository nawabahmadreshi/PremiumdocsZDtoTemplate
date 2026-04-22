from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    """Centralised configuration loaded from environment variables."""

    ZENDESK_SUBDOMAIN: str = field(default_factory=lambda: os.environ["ZENDESK_SUBDOMAIN"])
    ZENDESK_EMAIL: str = field(default_factory=lambda: os.environ["ZENDESK_EMAIL"])
    ZENDESK_API_TOKEN: str = field(default_factory=lambda: os.environ["ZENDESK_API_TOKEN"])
    ZENDESK_CATEGORY_ID: int = field(default_factory=lambda: int(os.environ["ZENDESK_CATEGORY_ID"]))
    ZENDESK_LOCALE: str = field(default_factory=lambda: os.environ.get("ZENDESK_LOCALE", "en-us"))

    STORAGE_DIR: Path = field(default_factory=lambda: Path(os.environ.get("STORAGE_DIR", "storage")))

    def get_zendesk_client(self):
        from app.zendesk_client import ZendeskClient

        return ZendeskClient(
            subdomain=self.ZENDESK_SUBDOMAIN,
            email=self.ZENDESK_EMAIL,
            api_token=self.ZENDESK_API_TOKEN,
            locale=self.ZENDESK_LOCALE,
        )
