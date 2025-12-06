# gmail_client.py
from typing import List, Dict, Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_auth_helper import get_google_credentials


def get_gmail_service():
    creds = get_google_credentials()
    return build("gmail", "v1", credentials=creds)


def list_recent_messages(max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Return a list of recent messages (id, subject, from, date, snippet).
    """
    service = get_gmail_service()
    try:
        resp = service.users().messages().list(
            userId="me",
            maxResults=max_results,
            labelIds=["INBOX"],
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail list failed: {e}") from e

    msgs_meta = resp.get("messages", [])
    results: List[Dict[str, Any]] = []

    if not msgs_meta:
        return results

    for m in msgs_meta:
        full = service.users().messages().get(
            userId="me",
            id=m["id"],
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()

        headers = {
            h["name"].lower(): h["value"]
            for h in full.get("payload", {}).get("headers", [])
        }
        snippet = full.get("snippet", "")

        results.append(
            {
                "id": m["id"],
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "snippet": snippet,
            }
        )

    return results


def search_messages(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    Search Gmail with a Gmail search query string.
    """
    service = get_gmail_service()
    try:
        resp = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Gmail search failed: {e}") from e

    msgs_meta = resp.get("messages", [])
    results: List[Dict[str, Any]] = []

    if not msgs_meta:
        return results

    for m in msgs_meta:
        full = service.users().messages().get(
            userId="me",
            id=m["id"],
            format="metadata",
            metadataHeaders=["Subject", "From", "Date"],
        ).execute()

        headers = {
            h["name"].lower(): h["value"]
            for h in full.get("payload", {}).get("headers", [])
        }
        snippet = full.get("snippet", "")

        results.append(
            {
                "id": m["id"],
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "date": headers.get("date", ""),
                "snippet": snippet,
            }
        )

    return results
