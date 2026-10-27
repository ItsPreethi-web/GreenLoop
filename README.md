# GreenLoop

Campus sustainability dashboard for simulated electricity, solar, water, and waste data. A FastAPI backend serves the existing single-file frontend and persists actions, points, waste logs, and editable emission factors in Supabase.

## Run locally

From `backend/`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.lock
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`; API documentation is at `/docs`.

## Supabase setup

The SQL schema and seed data are in [`supabase/schema.sql`](supabase/schema.sql). Copy [`backend/.env.example`](backend/.env.example) to `backend/.env`, then configure `SUPABASE_URL` and the server-only `SUPABASE_SERVICE_ROLE_KEY`. Never commit `.env` or put a server key in browser code. The root `.gitignore` excludes the local secret file.

See [`backend/README.md`](backend/README.md) for the API routes and setup details.

## Current scope

Hardware readings are software-generated defaults. Waste category estimates use preset sample results; uploaded photos are preview-only and are not analyzed by a trained image model.
