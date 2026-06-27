"""
app.py  —  Calendar Assistant
Streamlit + LangGraph app for Google Calendar management via natural language chat.
Run with:  python -m streamlit run app.py --server.fileWatcherType none
"""

import os
import json
import datetime as dt
import pytz
import streamlit as st

from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from typing import TypedDict

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

SCOPES   = ["https://www.googleapis.com/auth/calendar"]
TIMEZONE = "Asia/Karachi"
KARACHI  = pytz.timezone("Asia/Karachi")
llm      = ChatOpenAI(model="gpt-4o-mini", temperature=0)

@st.cache_resource
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

def get_busy_blocks(service, time_min, time_max):
    body = {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "timeZone": TIMEZONE,
        "items": [{"id": "primary"}],
    }
    result   = service.freebusy().query(body=body).execute()
    busy_raw = result["calendars"]["primary"]["busy"]
    blocks   = []
    for b in busy_raw:
        start = dt.datetime.fromisoformat(b["start"].replace("Z", "+00:00"))
        end   = dt.datetime.fromisoformat(b["end"].replace("Z", "+00:00"))
        blocks.append((start, end))
    return blocks

def find_slots(busy_blocks, search_start, search_end, meeting_minutes, work_start=9, work_end=18):
    slots    = []
    duration = dt.timedelta(minutes=meeting_minutes)
    day      = search_start.date()
    last_day = search_end.date()
    while day <= last_day:
        if day.weekday() < 5:
            day_s = dt.datetime.combine(day, dt.time(work_start, 0)).replace(tzinfo=search_start.tzinfo)
            day_e = dt.datetime.combine(day, dt.time(work_end,   0)).replace(tzinfo=search_start.tzinfo)
            day_busy = sorted(
                [b for b in busy_blocks if b[0].date() <= day <= b[1].date()],
                key=lambda b: b[0],
            )
            cursor = day_s
            for bs, be in day_busy:
                bs = max(bs, day_s)
                be = min(be, day_e)
                if bs > cursor and (bs - cursor) >= duration:
                    slots.append((cursor, cursor + duration))
                cursor = max(cursor, be)
            if (day_e - cursor) >= duration:
                slots.append((cursor, cursor + duration))
        day += dt.timedelta(days=1)
    return slots

def list_upcoming(service, days=1, max_results=10):
    today_start = dt.datetime.now(dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    now    = today_start.isoformat()
    future = (today_start + dt.timedelta(days=days)).isoformat()
    result = service.events().list(
        calendarId="primary", timeMin=now, timeMax=future,
        maxResults=max_results, singleEvents=True, orderBy="startTime"
    ).execute()
    return result.get("items", [])

def create_event(service, summary, start_dt, end_dt):
    body = {
        "summary": summary,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
        "end":   {"dateTime": end_dt.isoformat(),   "timeZone": TIMEZONE},
    }
    return service.events().insert(calendarId="primary", body=body).execute()

def delete_event_by_search(service, query):
    today_start = dt.datetime.now(dt.timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    result = service.events().list(
        calendarId="primary", q=query, timeMin=today_start,
        maxResults=5, singleEvents=True, orderBy="startTime"
    ).execute()
    items = result.get("items", [])
    if not items:
        return None, "No matching event found."
    event = items[0]
    service.events().delete(calendarId="primary", eventId=event["id"]).execute()
    return event.get("summary"), "Deleted successfully."

def render_day_schedule(service, target_date):
    """
    Renders a visual 9am-6pm schedule bar for a given date.
    Green = free, Red = busy. Weekend = grey with message.
    """
    WORK_START = 9
    WORK_END   = 18
    TOTAL_MINS = (WORK_END - WORK_START) * 60  # 540 minutes

    if target_date.weekday() >= 5:
        day_name = "Saturday" if target_date.weekday() == 5 else "Sunday"
        st.markdown(f"""
        <div style="background:#1a2035;border-radius:8px;padding:12px;margin-bottom:8px;text-align:center;">
            <div style="color:#8892a4;font-size:0.8rem;">📅 {target_date.strftime('%a %d %b')}</div>
            <div style="color:#e8c46a;font-size:0.78rem;margin-top:6px;">🏖️ Weekend — No slots available</div>
        </div>
        """, unsafe_allow_html=True)
        return

    day_start_utc = KARACHI.localize(
        dt.datetime.combine(target_date, dt.time(WORK_START, 0))
    ).astimezone(dt.timezone.utc)
    day_end_utc = KARACHI.localize(
        dt.datetime.combine(target_date, dt.time(WORK_END, 0))
    ).astimezone(dt.timezone.utc)

    try:
        busy = get_busy_blocks(service, day_start_utc, day_end_utc)
    except Exception:
        busy = []

    # Build segments: list of (start_pct, width_pct, is_busy, label)
    segments = []
    work_s   = KARACHI.localize(dt.datetime.combine(target_date, dt.time(WORK_START, 0)))
    work_e   = KARACHI.localize(dt.datetime.combine(target_date, dt.time(WORK_END,   0)))
    cursor   = work_s

    busy_local = []
    for bs, be in busy:
        bs_local = bs.astimezone(KARACHI)
        be_local = be.astimezone(KARACHI)
        bs_local = max(bs_local, work_s)
        be_local = min(be_local, work_e)
        if be_local > bs_local:
            busy_local.append((bs_local, be_local))
    busy_local.sort(key=lambda x: x[0])

    for bs, be in busy_local:
        if bs > cursor:
            gap_mins  = (bs - cursor).seconds // 60
            gap_pct   = gap_mins / TOTAL_MINS * 100
            segments.append((gap_pct, "free",
                             f"{cursor.strftime('%I:%M %p')}–{bs.strftime('%I:%M %p')}"))
        busy_mins = (be - bs).seconds // 60
        busy_pct  = busy_mins / TOTAL_MINS * 100
        segments.append((busy_pct, "busy",
                         f"{bs.strftime('%I:%M %p')}–{be.strftime('%I:%M %p')}"))
        cursor = be

    if cursor < work_e:
        rem_mins = (work_e - cursor).seconds // 60
        rem_pct  = rem_mins / TOTAL_MINS * 100
        segments.append((rem_pct, "free",
                         f"{cursor.strftime('%I:%M %p')}–{work_e.strftime('%I:%M %p')}"))

    # Build HTML bar
    bar_html = '<div style="display:flex;width:100%;height:18px;border-radius:4px;overflow:hidden;margin:6px 0;">'
    for pct, kind, _ in segments:
        color = "#2d6a4f" if kind == "free" else "#c1121f"
        bar_html += f'<div style="width:{pct:.1f}%;background:{color};"></div>'
    bar_html += "</div>"

    # Time labels
    labels_html = '<div style="display:flex;justify-content:space-between;font-size:0.65rem;color:#8892a4;">'
    for h in range(WORK_START, WORK_END + 1, 3):
        labels_html += f'<span>{h:02d}:00</span>'
    labels_html += "</div>"

    # Legend items
    legend_parts = []
    for pct, kind, label in segments:
        if pct > 3:
            icon  = "🟢" if kind == "free" else "🔴"
            legend_parts.append(f'<span style="font-size:0.7rem;color:#8892a4;">{icon} {label}</span>')
    legend_html = '<div style="display:flex;flex-wrap:wrap;gap:4px;margin-top:4px;">' + \
                  "".join(legend_parts) + "</div>"

    now_karachi = dt.datetime.now(KARACHI)
    is_today    = target_date == now_karachi.date()
    date_label  = f"📅 Today — {target_date.strftime('%a %d %b')}" if is_today else f"📅 {target_date.strftime('%a %d %b')}"

    st.markdown(f"""
    <div style="background:#1a2035;border-radius:8px;padding:10px 12px;margin-bottom:8px;">
        <div style="color:#7eb8f7;font-size:0.8rem;font-weight:600;">{date_label}</div>
        {bar_html}
        {labels_html}
        {legend_html}
    </div>
    """, unsafe_allow_html=True)


class CalState(TypedDict, total=False):
    user_message : str
    intent       : str
    extracted    : dict
    slots        : list
    answer       : str
    service      : object

ROUTE_PROMPT = """Classify the user's calendar request into one of these intents:
- find_slots  : user wants to find a free time slot / check availability
- book        : user wants to create / schedule a specific meeting
- view        : user wants to see upcoming events / what's on their calendar
- delete      : user wants to cancel / delete an event
- unclear     : none of the above / too vague

Reply with ONLY the single intent word, nothing else.

User message: {msg}"""

def route_intent(state: CalState) -> CalState:
    resp   = llm.invoke(ROUTE_PROMPT.format(msg=state["user_message"]))
    intent = resp.content.strip().lower()
    if intent not in ["find_slots", "book", "view", "delete"]:
        intent = "unclear"
    return {**state, "intent": intent}

def intent_branch(state: CalState) -> str:
    return state["intent"]

EXTRACT_PROMPT = """Extract parameters from this calendar request as JSON.
Today is {today}. Timezone: Asia/Karachi.

Return ONLY valid JSON, no markdown, matching ONE of these shapes:

find_slots:
{{"action":"find_slots","meeting_minutes":30,"days_ahead":3,"work_start":9,"work_end":18}}

book:
{{"action":"book","summary":"Meeting title","start_datetime":"YYYY-MM-DDTHH:MM:SS","end_datetime":"YYYY-MM-DDTHH:MM:SS"}}

view:
{{"action":"view","days_ahead":1}}

delete:
{{"action":"delete","query":"event title to search for"}}

User message: {msg}"""

def calendar_node(state: CalState) -> CalState:
    service = state["service"]
    today   = dt.datetime.now(KARACHI).strftime("%Y-%m-%d %H:%M")
    raw     = llm.invoke(EXTRACT_PROMPT.format(today=today, msg=state["user_message"]))
    try:
        params = json.loads(raw.content.strip())
    except json.JSONDecodeError:
        return {**state, "answer": "Sorry, I couldn't understand that. Try rephrasing."}

    action = params.get("action")

    if action == "find_slots":
        mins       = int(params.get("meeting_minutes", 30))
        days       = max(1, int(params.get("days_ahead", 3)))
        work_start = int(params.get("work_start", 9))
        work_end   = int(params.get("work_end", 18))

        now = dt.datetime.now(KARACHI)

        # Weekend check
        if now.weekday() >= 5 and days <= 1:
            day_name       = "Saturday" if now.weekday() == 5 else "Sunday"
            days_to_monday = 7 - now.weekday()
            monday         = (now + dt.timedelta(days=days_to_monday)).strftime("%a %d %b")
            return {**state, "slots": [], "answer": (
                f"📅 Today is **{day_name}** — no meeting slots on weekends.\n\n"
                f"Next available slots: **Monday {monday}**.\n\n"
                f"Try: *'Find me a free slot this week'* or *'Find me a free slot on Monday'*"
            )}

        # If past 6pm, start from tomorrow
        if now.hour >= 18:
            tomorrow = (now + dt.timedelta(days=1)).date()
            now = KARACHI.localize(dt.datetime.combine(tomorrow, dt.time(0, 0)))

        # If weekend, extend to reach Monday
        if now.weekday() >= 5:
            days = max(days, 3)

        end = max(
            now + dt.timedelta(days=days),
            now + dt.timedelta(hours=24)
        )

        try:
            busy = get_busy_blocks(service, now, end)
        except Exception:
            busy = []

        slots = find_slots(busy, now, end, mins, work_start, work_end)

        now_check = dt.datetime.now(KARACHI)
        slots = [s for s in slots if s[0] > now_check + dt.timedelta(minutes=5)]

        if not slots:
            return {**state, "slots": [], "answer": f"No free {mins}-min slots found. Try asking for slots this week."}

        lines  = [f"{i+1}. {s.strftime('%a %d %b, %I:%M %p')} – {e.strftime('%I:%M %p')}" for i, (s, e) in enumerate(slots)]
        answer = f"Found **{len(slots)}** available slot(s):\n\n" + "\n\n".join(lines)
        answer += "\n\n👉 Use the **Book a slot** panel on the left to pick one."
        return {**state, "slots": slots, "answer": answer}

    elif action == "book":
        try:
            start = dt.datetime.fromisoformat(params["start_datetime"]).astimezone()
            end   = dt.datetime.fromisoformat(params["end_datetime"]).astimezone()
            event = create_event(service, params.get("summary", "Meeting"), start, end)
            answer = f"✅ Booked **{event.get('summary')}** on {start.strftime('%a %d %b at %I:%M %p')}."
        except Exception as ex:
            answer = f"Couldn't book: {ex}"
        return {**state, "answer": answer}

    elif action == "view":
        days   = max(1, int(params.get("days_ahead", 1)))
        events = list_upcoming(service, days=days)
        if not events:
            return {**state, "answer": f"No events found today or in the next {days} day(s)."}
        lines = []
        for e in events:
            raw_start = e["start"].get("dateTime", e["start"].get("date"))
            try:
                dt_obj    = dt.datetime.fromisoformat(raw_start.replace("Z", "+00:00")).astimezone(KARACHI)
                raw_start = dt_obj.strftime("%a %d %b, %I:%M %p")
            except Exception:
                pass
            lines.append(f"• **{e.get('summary', '(no title)')}** — {raw_start}")
        return {**state, "answer": "📅 Upcoming events:\n\n" + "\n\n".join(lines)}

    elif action == "delete":
        title, msg = delete_event_by_search(service, params.get("query", ""))
        answer = f"🗑️ Deleted **{title}**." if title else f"Couldn't find '{params.get('query')}'. Check the exact name in the sidebar."
        return {**state, "answer": answer}

    return {**state, "answer": "Not sure what to do. Try: find a slot, book, view, or delete."}

def unclear_node(state: CalState) -> CalState:
    return {**state, "answer": (
        "I didn't catch that. Here's what I can do:\n\n"
        "- **Find slots** — 'Find me a free 30-min slot this week'\n"
        "- **Book** — 'Schedule a meeting called Standup tomorrow at 10am'\n"
        "- **View** — 'What's on my calendar today?'\n"
        "- **Delete** — 'Cancel my Standup meeting'"
    )}

@st.cache_resource
def build_graph():
    graph = StateGraph(CalState)
    graph.add_node("route_intent",  route_intent)
    graph.add_node("calendar_node", calendar_node)
    graph.add_node("unclear_node",  unclear_node)
    graph.set_entry_point("route_intent")
    graph.add_conditional_edges(
        "route_intent", intent_branch,
        {"find_slots": "calendar_node", "book": "calendar_node",
         "view": "calendar_node", "delete": "calendar_node", "unclear": "unclear_node"},
    )
    graph.add_edge("calendar_node", END)
    graph.add_edge("unclear_node",  END)
    return graph.compile()

# ── UI ──────────────────────────────────────
st.set_page_config(page_title="Calendar Assistant", page_icon="📅", layout="wide")
st.markdown("""<style>
.stApp{background:#0f1117;color:#e8eaf0}
[data-testid="stSidebar"]{background:#161b27;border-right:1px solid #2a2f3f}
[data-testid="stChatMessage"]{background:#1a2035;border-radius:12px;margin-bottom:8px}
.stButton>button{background:#1e3a5f;color:#7eb8f7;border:1px solid #2e5080;border-radius:8px;width:100%;margin-bottom:6px;font-size:.85rem}
.stButton>button:hover{background:#264d7a}
.event-card{background:#1a2540;border-left:3px solid #4a8fd4;border-radius:6px;padding:8px 12px;margin-bottom:8px;font-size:.82rem}
.event-title{font-weight:600;color:#7eb8f7}
.event-time{color:#8892a4;font-size:.75rem;margin-top:2px}
h1,h2,h3{color:#7eb8f7!important}
</style>""", unsafe_allow_html=True)

if "messages"    not in st.session_state: st.session_state.messages    = []
if "found_slots" not in st.session_state: st.session_state.found_slots = []

try:
    service = get_service()
    graph   = build_graph()
    auth_ok = True
except Exception as e:
    auth_ok  = False
    auth_err = str(e)

with st.sidebar:
    st.markdown("## 📅 Calendar Assistant")
    st.markdown("---")
    if auth_ok:
        st.markdown("### Quick Actions")
        if st.button("📋 View today's events"):
            st.session_state.messages.append({"role": "user", "content": "What's on my calendar today?"})
            st.rerun()
        if st.button("🔍 Find a free slot today"):
            st.session_state.messages.append({"role": "user", "content": "Find me a free 30-minute slot today"})
            st.rerun()
        if st.button("📅 This week's events"):
            st.session_state.messages.append({"role": "user", "content": "Show me all events this week"})
            st.rerun()
        st.markdown("---")
        st.markdown("### Book a Slot")
        if st.session_state.found_slots:
            opts       = [f"{s.strftime('%a %d %b, %I:%M %p')} – {e.strftime('%I:%M %p')}" for s, e in st.session_state.found_slots]
            chosen_idx = st.selectbox("Pick a slot", range(len(opts)), format_func=lambda i: opts[i])
            title      = st.text_input("Meeting title", value="Meeting")
            if st.button("✅ Book this slot"):
                s, e = st.session_state.found_slots[chosen_idx]
                msg  = f"Book a meeting called '{title}' from {s.isoformat()} to {e.isoformat()}"
                st.session_state.messages.append({"role": "user", "content": msg})
                st.session_state.found_slots = []
                st.rerun()
        else:
            st.caption("Ask me to find available slots first.")
        st.markdown("---")

        # ── Visual availability panel ──────────
        st.markdown("### 📊 Availability (9am–6pm)")
        today_karachi = dt.datetime.now(KARACHI).date()
        for i in range(3):
            render_day_schedule(service, today_karachi + dt.timedelta(days=i))

        st.markdown("""
        <div style="display:flex;gap:12px;margin-top:4px;font-size:0.72rem;color:#8892a4;">
            <span>🟢 Free</span><span>🔴 Busy</span><span>🏖️ Weekend</span>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### Upcoming (3 days)")
        try:
            for ev in list_upcoming(service, days=3, max_results=6):
                raw = ev["start"].get("dateTime", ev["start"].get("date"))
                try:
                    raw = dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(KARACHI).strftime("%a %d %b, %I:%M %p")
                except Exception: pass
                st.markdown(f'<div class="event-card"><div class="event-title">{ev.get("summary","(no title)")}</div><div class="event-time">{raw}</div></div>', unsafe_allow_html=True)
        except Exception:
            st.caption("Couldn't load events.")

st.markdown("## 💬 Chat with your Calendar")
if not auth_ok:
    st.error(f"Auth error: {auth_err}")
    st.stop()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

user_input = st.chat_input("e.g. 'Find me a free slot tomorrow' or 'What's on my calendar today?'")

pending_input = None
if user_input:
    pending_input = user_input
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
elif (st.session_state.messages and
      st.session_state.messages[-1]["role"] == "user"):
    pending_input = st.session_state.messages[-1]["content"]

if pending_input:
    with st.chat_message("assistant"):
        with st.spinner("Checking your calendar..."):
            result = graph.invoke({"user_message": pending_input, "service": service})
            answer = result.get("answer", "Something went wrong.")
            slots  = result.get("slots", [])
            if slots:
                st.session_state.found_slots = slots
            st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
    st.rerun()