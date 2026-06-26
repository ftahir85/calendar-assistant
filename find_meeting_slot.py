"""
find_meeting_slot.py

Finds available meeting slots on your Google Calendar within working hours,
and lets you book one directly.

How it works:
1. Asks you: meeting length, how many days ahead to search, working hours
2. Calls the Google Calendar "freebusy" API to get your busy blocks
3. Walks through each working day, finds gaps big enough for your meeting
4. Lets you pick one and creates the event

Run with: python find_meeting_slot.py
"""

import datetime as dt
import os

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
TIMEZONE = "Asia/Karachi"  # change if needed


# ---------------------------------------------------------------------------
# Auth (same as test_auth.py)
# ---------------------------------------------------------------------------

def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Step 1: Get busy blocks using the freebusy API
# ---------------------------------------------------------------------------

def get_busy_blocks(service, time_min: dt.datetime, time_max: dt.datetime, calendar_id="primary"):
    """
    Returns a list of (start, end) datetime tuples representing busy periods.
    """
    body = {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "timeZone": TIMEZONE,
        "items": [{"id": calendar_id}],
    }
    result = service.freebusy().query(body=body).execute()
    busy_raw = result["calendars"][calendar_id]["busy"]

    busy_blocks = []
    for b in busy_raw:
        start = dt.datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        end = dt.datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
        busy_blocks.append((start, end))
    return busy_blocks


# ---------------------------------------------------------------------------
# Step 2: Find gaps in working hours that are big enough
# ---------------------------------------------------------------------------

def find_available_slots(
    busy_blocks,
    search_start: dt.datetime,
    search_end: dt.datetime,
    meeting_minutes: int,
    work_start_hour: int = 9,
    work_end_hour: int = 18,
):
    """
    Walks day by day from search_start to search_end, and within each day's
    working hours, finds gaps between busy blocks that fit the meeting.
    """
    slots = []
    meeting_duration = dt.timedelta(minutes=meeting_minutes)

    current_day = search_start.date()
    last_day = search_end.date()

    while current_day <= last_day:
        # Skip weekends (Saturday=5, Sunday=6) — comment out if not needed
        if current_day.weekday() < 5:
            day_start = dt.datetime.combine(
                current_day, dt.time(work_start_hour, 0)
            ).replace(tzinfo=search_start.tzinfo)
            day_end = dt.datetime.combine(
                current_day, dt.time(work_end_hour, 0)
            ).replace(tzinfo=search_start.tzinfo)

            # Busy blocks that overlap this day, sorted by start time
            day_busy = sorted(
                [b for b in busy_blocks if b[0].date() <= current_day <= b[1].date()],
                key=lambda b: b[0],
            )

            cursor = day_start
            for busy_start, busy_end in day_busy:
                # clip busy block to today's working window
                busy_start = max(busy_start, day_start)
                busy_end = min(busy_end, day_end)

                if busy_start > cursor:
                    gap = busy_start - cursor
                    if gap >= meeting_duration:
                        slots.append((cursor, cursor + meeting_duration))
                cursor = max(cursor, busy_end)

            # Remaining time after the last busy block until end of working day
            if day_end - cursor >= meeting_duration:
                slots.append((cursor, cursor + meeting_duration))

        current_day += dt.timedelta(days=1)

    return slots


# ---------------------------------------------------------------------------
# Step 3: Book a chosen slot
# ---------------------------------------------------------------------------

def book_slot(service, start: dt.datetime, end: dt.datetime, summary: str, calendar_id="primary"):
    event_body = {
        "summary": summary,
        "start": {"dateTime": start.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end.isoformat(), "timeZone": TIMEZONE},
    }
    created = service.events().insert(calendarId=calendar_id, body=event_body).execute()
    return created


# ---------------------------------------------------------------------------
# Main interactive flow
# ---------------------------------------------------------------------------

def main():
    service = get_service()

    print("=== Find a meeting slot ===")
    meeting_minutes = int(input("Meeting length in minutes (e.g. 30): ") or 30)
    days_ahead = int(input("Search how many days ahead (e.g. 3): ") or 3)
    work_start = int(input("Working hours start (24h, e.g. 9): ") or 9)
    work_end = int(input("Working hours end (24h, e.g. 18): ") or 18)

    now = dt.datetime.now().astimezone()
    search_start = now
    search_end = now + dt.timedelta(days=days_ahead)

    busy_blocks = get_busy_blocks(service, search_start, search_end)
    slots = find_available_slots(
        busy_blocks, search_start, search_end, meeting_minutes, work_start, work_end
    )

    if not slots:
        print("No available slots found in that range.")
        return

    print(f"\nFound {len(slots)} available slot(s):\n")
    for i, (s, e) in enumerate(slots, start=1):
        print(f"  {i}. {s.strftime('%a %d %b, %I:%M %p')} - {e.strftime('%I:%M %p')}")

    choice = input("\nPick a slot number to book it (or press Enter to skip): ").strip()
    if not choice:
        print("No slot booked.")
        return

    idx = int(choice) - 1
    if idx < 0 or idx >= len(slots):
        print("Invalid choice.")
        return

    summary = input("Meeting title: ").strip() or "Meeting"
    start, end = slots[idx]
    created = book_slot(service, start, end, summary)
    print(f"\nBooked: '{created.get('summary')}' at {start.strftime('%a %d %b, %I:%M %p')}")
    print(f"Link: {created.get('htmlLink')}")


if __name__ == "__main__":
    main()