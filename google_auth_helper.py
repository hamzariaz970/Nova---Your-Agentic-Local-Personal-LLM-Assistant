# google_auth_helper.py
import os
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import STORAGE_DIR  # <--- reuse your storage dir

# Scopes for Gmail read-only + Calendar read-only
SCOPES: List[str] = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

# Put both files inside STORAGE_DIR
CLIENT_SECRET_FILE = os.path.join(STORAGE_DIR, "google_oauth_client.json")
TOKEN_FILE = os.path.join(STORAGE_DIR, "google_token.json")


def get_google_credentials() -> Credentials:
    """
    Get valid Google credentials for Gmail + Calendar.

    - On first run, opens a browser window for login/consent.
    - Stores refresh token in google_token.json for reuse.
    """
    creds: Credentials | None = None

    # 1) Try cached token
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    # 2) Refresh or run OAuth flow
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET_FILE):
                raise RuntimeError(
                    f"Google OAuth client JSON not found at {CLIENT_SECRET_FILE}.\n"
                    "Download the Desktop app client JSON from Google Cloud Console "
                    "and save it there as google_oauth_client.json."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                CLIENT_SECRET_FILE,
                SCOPES,
            )
            creds = flow.run_local_server(
                port=0,        # random free port
                prompt="consent",
                access_type="offline",
            )

        # 3) Cache the token for next time
        with open(TOKEN_FILE, "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return creds
