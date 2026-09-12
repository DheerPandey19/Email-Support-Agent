# Email Support Workflow

A LangGraph email-support agent that classifies incoming mail, drafts a reply, and **pauses for human review** on urgent or complex cases. Progress is saved in **Postgres**, so you can stop the server, restart it, and resume the same thread.

## What it does

1. Read the email  
2. Classify intent and urgency  
3. Look up docs / open a bug ticket when needed  
4. Draft a response  
5. If urgency is high/critical **or** intent is complex → **interrupt** for human approve / edit / reject  
6. Otherwise (or after approval) → send reply  

The “save game” key is `thread_id`. Postgres holds the checkpoint; the process does not.

## Project layout

| File | Role |
|------|------|
| `graph.py` | Workflow definition (`build_app`, sync helper for CLI) |
| `server.py` | FastAPI API + review UI |
| `static/index.html` | Browser form to submit / review / reload threads |
| `demo.py` | Terminal demos (sync Postgres checkpointer) |
| `docker-compose.yml` | Local Postgres 16 |

## Prerequisites

- Python 3.11+ recommended  
- [Docker](https://docs.docker.com/get-docker/) for Postgres  
- An OpenAI API key  

## Setup

1. Clone / open this folder and create a virtualenv if you like.

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

3. Create a `.env` in the project root:

```env
OPENAI_API_KEY=sk-...
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/email_workflow
```

4. Start Postgres:

```powershell
docker compose up -d
```

## Run the web review UI

**Windows** (required so psycopg async works with uvicorn):

```powershell
python server.py
```

Or:

```powershell
uvicorn server:app --reload --loop asyncio:SelectorEventLoop
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Prove durability

1. Submit an urgent email (the form is prefilled with one).  
2. When status is **interrupted**, copy the `thread_id`.  
3. Stop the server (Ctrl+C).  
4. Start it again.  
5. Paste the `thread_id` under **Load an existing thread**.  
6. Approve (or reject / edit) — the workflow continues from the saved checkpoint.

## Run the CLI demo

```powershell
python demo.py
```

Uses the sync checkpointer (`get_sync_app` in `graph.py`). Prefer `server.py` for the async HTTP path; do not call `get_sync_app` from FastAPI request handlers.

## API (brief)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/` | Review page |
| `POST` | `/emails` | Start a new thread (`email_content`, `sender_email`, optional `email_id`) |
| `GET` | `/emails/{thread_id}` | Pending interrupt or completed state |
| `POST` | `/emails/{thread_id}/review` | Resume with `{ "approved": true/false, "edited_response": "..." }` |

Responses use `"status": "interrupted" | "completed"` plus `thread_id`.

## Mental model

- **Graph** — the recipe (`graph.py`)  
- **Checkpointer** — Postgres save system  
- **`thread_id`** — which save file  
- **`interrupt`** — pause for a human  
- **`Command(resume=...)`** — human answered; continue  

