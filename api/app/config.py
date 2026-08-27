from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Header, HTTPException


INTERNAL_SERVICE_TOKEN = os.getenv("INTERNAL_SERVICE_TOKEN", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "change-me")
WORKSPACE_DIR = Path(os.getenv("WORKSPACE_DIR", "/workspace")).resolve()
SANDBOX_URL = os.getenv("SANDBOX_URL", "http://sandbox:5001").rstrip("/")
BROWSER_URL = os.getenv("BROWSER_URL", "http://browser:5002").rstrip("/")


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if not INTERNAL_SERVICE_TOKEN or not secrets.compare_digest(x_internal_token or "", INTERNAL_SERVICE_TOKEN):
        raise HTTPException(status_code=403, detail="Internal token required")


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    # Local first-run UX: the documented default does not block the setup panel.
    # Any custom ADMIN_TOKEN restores mandatory header authentication.
    if ADMIN_TOKEN in {"", "change-me"}:
        return
    if not secrets.compare_digest(x_admin_token or "", ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Admin token required")
