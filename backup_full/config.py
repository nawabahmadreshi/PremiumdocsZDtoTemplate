from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Technical Consultant roster ───────────────────────────────────────────────
# Sourced from resource-tracker-tcs. Keep lowercase; comparison is case-insensitive.
TC_EMAILS: set[str] = {
    "amrutha.kotian@aquera.com",
    "deeban.babu@aquera.com",
    "jitendra.patil@aquera.com",
    "jorgel.felixr@aquera.com",
    "lorenzo.ganda@aquera.com",
    "madhan.kumar@aquera.com",
    "midhun.raj@aquera.com",
    "navin.kumar@aquera.com",
    "pavan.kumar@aquera.com",
    "poojitha.munirathnam@aquera.com",
    "puja.roy@aquera.com",
    "rajat.talekar@aquera.com",
    "rakesh.kodigal@aquera.com",
    "rohan.kumar@aquera.com",
    "sai.bynagari@aquera.com",
    "sanjan.athyady@aquera.com",
    "saurav.kumar@aquera.com",
    "saurav.singh@aquera.com",
    "shivasharan.kumbar@aquera.com",
    "sreekanth.reddy@aquera.com",
    "sumanth.kumar@aquera.com",
    "syam.kumar@aquera.com",
}

# ── Customer Success (CS) Roster (15 Members) ────────────────────────────────
CS_EMAILS = {
    "krishna.boregowda@aquera.com", "abhilash.chandrashekar@aquera.com", 
    "manoj.kumar@aquera.com", "saravanan.gnanaprakasam@aquera.com", 
    "jeston.agera@aquera.com", "yashraj.sinha@aquera.com", 
    "adhikari.leelasri@aquera.com", "rohit.nimbure@aquera.com", 
    "palghat.gokula@aquera.com", "nithish.ravindranath@aquera.com", 
    "teja.reddy@aquera.com", "sreevathsa.raghavendra@aquera.com", 
    "arush.verma@aquera.com", "budharaju.praneetha@aquera.com",
    "vijaypavan.gonu@aquera.com"
}
# ─────────────────────────────────────────────────────────────────────────────

# ── Technical Consultants (TC) Roster (Active Filter) ────────────────────────
TC_EMAILS_FILTER = {
    "nawab.ahmad@aquera.com", "shashwat.singh@aquera.com", "pavan.kumar@aquera.com"
}

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
