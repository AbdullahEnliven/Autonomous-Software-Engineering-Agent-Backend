# ASEA Backend

FastAPI backend for the ASEA AI Store Builder platform.

---

## Tech Stack

- **Python 3.12** · **FastAPI** · **SQLAlchemy (async)** · **PostgreSQL**
- **Socket.IO** for real-time events
- **Alembic** for database migrations
- **Groq** LLM for AI code generation
- **Vercel CLI** for store preview deployments

---

## First-Time Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment

Copy the example and fill in your values:

```bash
cp .env.example.deployment .env
```

Required variables:

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL async URL — `postgresql+asyncpg://user:pass@host/db` |
| `SECRET_KEY` | Random string for JWT signing |
| `GROQ_API_KEYS` | Comma-separated Groq API keys |
| `VERCEL_TOKEN` | Vercel personal access token |
| `VERCEL_SCOPE` | Vercel team/user slug |
| `FRONTEND_URL` | Frontend origin for CORS (e.g. `http://localhost:5173`) |

### 3. Run database migrations

```bash
uv run alembic upgrade head
```

### 4. Start the development server

```bash
uv run uvicorn app.main:app --reload
```

API runs at **http://localhost:8000**  
Docs at **http://localhost:8000/docs**

---

## Project Structure

```
backend/
├── app/
│   ├── agents/        # AI code-generation agents
│   ├── models/        # SQLAlchemy ORM models
│   ├── routers/       # FastAPI route handlers
│   ├── schemas/       # Pydantic request/response schemas
│   ├── services/      # Business logic (preview, auth, projects…)
│   ├── socketio/      # Real-time Socket.IO server
│   ├── tasks/         # Background task runners
│   ├── utils/         # Security, helpers
│   ├── config.py      # Settings (loaded from .env)
│   ├── database.py    # Async DB session setup
│   └── main.py        # App entry point
├── migrations/        # Alembic migration scripts
├── template/          # Base store template files
├── alembic.ini
├── pyproject.toml
└── requirements.txt
```

---

## Deployment (Railway)

1. Set all env vars in the Railway dashboard.
2. Railway uses the `Dockerfile` at repo root — no extra config needed.
3. Vercel CLI must be available in the container for preview deployments.
