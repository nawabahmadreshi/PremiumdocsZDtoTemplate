from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

import sys

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

load_dotenv(get_resource_path('.env'))
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
    
    @property
    def project_root(self) -> Path:
        if getattr(sys, 'frozen', False):
            return Path(os.path.expanduser('~/Documents/Aquera Hub Data'))
        return Path(os.getcwd())
        
    @property
    def storage_dir(self) -> Path:
        return self.project_root / os.environ.get("STORAGE_DIR", "storage")

    def get_zendesk_client(self):
        from app.zendesk_client import ZendeskClient
        return ZendeskClient(
            subdomain=self.ZENDESK_SUBDOMAIN,
            email=self.ZENDESK_EMAIL,
            api_token=self.ZENDESK_API_TOKEN,
            locale=self.ZENDESK_LOCALE,
        )
