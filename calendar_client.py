# calendar_client.py
from typing import List, Dict, Any
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from google_auth_helper import get_google_credentials


def get_calendar_service():
    creds = get_google_credentials()
    return build("calendar", "v3", credentials=creds)


def list_upcoming_events(
    max_days: int = 7,
    max_results: int = 10,
) -> List[Dict[str, Any]]:
    """
    List upcoming events from the primary calendar for the next `max_days` days.
    """
    service = get_calendar_service()

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=max_days)).isoformat()

    try:
        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
    except HttpError as e:
        raise RuntimeError(f"Calendar list failed: {e}") from e

    events = events_result.get("items", [])
    results: List[Dict[str, Any]] = []

    for e in events:
        start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
        end = e.get("end", {}).get("dateTime") or e.get("end", {}).get("date")

        results.append(
            {
                "id": e.get("id", ""),
                "summary": e.get("summary", "(no title)"),
                "start": start,
                "end": end,
                "location": e.get("location", ""),
            }
        )

    return results
