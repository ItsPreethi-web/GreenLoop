# GreenLoop backend

FastAPI API for the existing GreenLoop dashboard. All hardware readings are generated in software by default. The waste scanner currently returns fixed sample classifications; it does not run an image model or claim to analyze uploaded photos.

## Run locally

From this directory, create a virtual environment, install the pinned dependencies, and start the API:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`. FastAPI serves the existing `greenloop.html` at `/`, and the interactive API reference is at `/docs`. Without Supabase credentials, the API uses in-memory demo state; actions and points reset when the process restarts.

## Connect Supabase

1. Run [`../supabase/schema.sql`](../supabase/schema.sql) in the Supabase SQL Editor (already applied for the connected GreenLoop project).
2. Copy `.env.example` to `.env` and set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` for the server only. Do not commit `.env`.
3. Restart the API. `/api/health` reports `storage: supabase` when the credentials are configured. The root page is served by FastAPI so the browser and API share one origin.

Never place the service role key in `greenloop.html`, browser JavaScript, or a public repository. The SQL enables row-level security without public policies; the API's service role accesses the tables server-side.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Storage and simulated-reading status |
| GET | `/api/blocks` | Campus block configuration |
| GET | `/api/state` | Adopted actions, points, recent waste logs |
| GET | `/api/dashboard?scope=all` | Current simulated totals, live load, seven-day series |
| GET | `/api/actions?scope=all` | Savings estimates and adoption status |
| POST | `/api/actions/{action_id}/adopt` | Adopt an action for `{"scope":"all"}` or one block id |
| DELETE | `/api/actions/{action_id}/adopt?scope=all` | Remove an adopted action |
| GET | `/api/leaderboard` | Per-person residential ranking and points |
| POST | `/api/waste/classify` | Fixed demo result for a sample item |
| POST | `/api/waste/log` | Save a sample waste log and award points |
| GET | `/api/method` | Emission factors and calculation rules |
| PATCH | `/api/factors` | Save grid and pumping factors to Supabase |

Supported demo sample IDs: `bottle`, `paper`, `jar`, `can`, and `peel`. Scope IDs: `ha`, `hb`, `hc`, `ap`, `sq`, and `ac`.

The current waste category estimate is sample-driven. Uploaded images are preview-only; image recognition needs a trained model and a labeled validation set before it can be represented as an AI classifier. Hardware readings are synthetic software defaults until sensor integration is added.

