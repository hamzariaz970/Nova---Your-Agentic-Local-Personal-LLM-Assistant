# test_google_api.py
from gmail_client import list_recent_messages, search_messages
from calendar_client import list_upcoming_events

if __name__ == "__main__":
    print("Testing Gmail…")
    msgs = list_recent_messages(max_results=3)
    for m in msgs:
        print(f"- {m['date']} | {m['from']} | {m['subject']}")

    print("\nTesting Gmail search…")
    res = search_messages("subject:receipt", max_results=3)
    for m in res:
        print(f"- {m['date']} | {m['from']} | {m['subject']}")

    print("\nTesting Calendar…")
    events = list_upcoming_events(max_days=3, max_results=5)
    for e in events:
        print(f"- {e['start']} | {e['summary']} @ {e['location']}")
