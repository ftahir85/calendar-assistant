# 📅 Calendar Assistant

A conversational AI assistant that connects to your Google Calendar. Find free slots, book meetings, view your schedule, and delete events — all through natural language chat.

Built with **Streamlit** + **LangGraph** + **Google Calendar API** + **GPT-4o-mini**.

---

## 🖼️ App Layout

```
┌─────────────────┬──────────────────────────────┐
│   LEFT SIDEBAR  │        MAIN CHAT AREA         │
│                 │                               │
│  Quick Actions  │  Type your request here       │
│  Book a Slot    │  and the assistant replies    │
│  Upcoming       │                               │
│  Events         │                               │
└─────────────────┴──────────────────────────────┘
```

---

## 📁 Project Structure

```
calender/
├── app.py               ← Main Streamlit app
├── credentials.json     ← Google OAuth credentials (never share/commit)
├── token.json           ← Auto-generated after first login (never share/commit)
├── .env                 ← Your OpenAI API key (never share/commit)
├── .gitignore           ← Protects credentials from being pushed to GitHub
└── README.md            ← This file
```

---

## ⚙️ Setup (First Time Only)

### 1. Google Cloud Setup
1. Go to [console.cloud.google.com](https://console.cloud.google.com/)
2. Create a project
3. Enable the **Google Calendar API**
4. Go to **APIs & Services → OAuth consent screen → Audience**
5. Add your Gmail as a **test user**
6. Go to **Credentials → Create Credentials → OAuth client ID → Desktop app**
7. Download the JSON file, rename it to `credentials.json`, place it in this folder

### 2. Install Dependencies
```powershell
pip install streamlit langgraph langchain-openai google-api-python-client google-auth-httplib2 google-auth-oauthlib python-dotenv
```

### 3. Add Your OpenAI Key
Create a `.env` file in the project folder:
```
OPENAI_API_KEY=your_openai_key_here
```

### 4. Protect Your Secrets
Make sure `.gitignore` contains:
```
credentials.json
token.json
.env
```

---

## 🚀 Running the App

```powershell
cd C:\Users\user\Desktop\calender
python -m streamlit run app.py --server.fileWatcherType none
```

The browser opens automatically at `http://localhost:8501`.

> The first time you run it, a browser popup will ask you to log into Google and click **Allow**. This only happens once — after that, login is saved in `token.json`.

---

## 💬 How to Use

### Quick Action Buttons (Sidebar)
| Button | What it does |
|--------|-------------|
| 📋 View today's events | Shows all events today |
| 🔍 Find a free slot today | Finds open 30-min gaps today |
| 📅 This week's events | Lists everything this week |

---

### Chat Commands

#### 👀 View Events
```
What's on my calendar today?
Show me all events this week
What do I have tomorrow?
```

#### 🔍 Find Free Slots
```
Find me a free 30-minute slot today
Find a free 1-hour slot this week
Find me a free slot tomorrow between 9am and 5pm
```

#### ✅ Book a Meeting

**Option A — From found slots (recommended):**
1. Ask: `Find me a free 30-minute slot this week`
2. Slots appear in chat + **Book a Slot** panel opens in sidebar
3. Pick a slot from the dropdown
4. Enter a meeting title
5. Click **✅ Book this slot**

**Option B — Direct booking:**
```
Schedule a meeting called Team Sync tomorrow at 10am
Book a 1-hour meeting called Project Review on Friday at 2pm
```

#### 🗑️ Delete an Event
```
Delete Meeting title
Cancel first official meet up
```
> ⚠️ Use the exact event name shown in the sidebar — not the day or time.

---

## ✅ Tips

| Do this | Not this |
|---------|----------|
| `delete Meeting title` | `delete slot on sunday` |
| `book a meeting at 3pm tomorrow` | `book something later` |
| `what's on my calendar today` | `what do I have` |

- Check the **Upcoming (3 days)** panel in the sidebar to see exact event names before deleting
- The app takes **5–10 seconds** to reply — this is normal, just wait
- The **Book a Slot** dropdown disappears after booking or refreshing — ask for slots again if needed

---

## ❓ Troubleshooting

| Problem | Fix |
|---------|-----|
| App is very slow | Make sure you're using `--server.fileWatcherType none` |
| "No events found" | Try asking for a wider range: `show me this week's events` |
| "Couldn't find event" on delete | Check exact event name in the sidebar and use that |
| Button clicked but no reply | Wait 5–10 seconds, the app is processing |
| Browser popup on startup | Log in with your Gmail and click Allow — happens once only |
| `credentials.json` error | Make sure the file is in the same folder as `app.py` |

---

## 🔒 Security Notes

- **Never push `credentials.json`, `token.json`, or `.env` to GitHub**
- These files give access to your Google Calendar and OpenAI account
- They are already listed in `.gitignore` to protect you
- If accidentally pushed, immediately rotate your credentials:
  - Google: Cloud Console → Credentials → Reset Secret
  - OpenAI: [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → Delete & recreate

---

## 🧠 How It Works (Under the Hood)

```
Your message
     │
     ▼
[LangGraph: route_intent]
     │ GPT-4o-mini classifies intent
     │
  ┌──┴─────────────────────────────┐
  │                                │
  ▼                                ▼
[calendar_node]              [unclear_node]
  │ Extracts params                │ Shows help message
  │ via GPT-4o-mini                │
  │                                │
  ├─ find_slots → freebusy API     │
  ├─ book       → events.insert    │
  ├─ view       → events.list      │
  └─ delete     → events.delete    │
  │                                │
  └────────────────┬───────────────┘
                   ▼
            Reply in chat
```

Every message makes:
1. **LLM call 1** — classify intent (find_slots / book / view / delete)
2. **LLM call 2** — extract parameters (date, time, title, duration)
3. **Google Calendar API call** — perform the actual action

---

## 🔮 Future Ideas
- [ ] Add RAG (document Q&A) alongside calendar features
- [ ] Support multiple calendars / other people's availability
- [ ] Add recurring event support
- [ ] Deploy to AWS EC2 for remote access

---

*Built with ❤️ using Streamlit, LangGraph, and Google Calendar API*
