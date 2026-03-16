# ASEA Platform — Backend Development Plan
### AI-Powered E-Commerce Store Builder | FastAPI + PostgreSQL + Agent System

---

## Overview

The ASEA backend is a production-grade Python API that orchestrates the entire store generation pipeline. It handles user authentication, project management, AI-powered specification generation, multi-agent code generation, real-time progress streaming, Supabase integration management, GitHub publishing, and artifact delivery.

The backend does NOT generate code using Docker, complex runtimes, or sandboxes. Instead, it uses a **template-first, agent-coordinated approach** — a system of specialized AI agents that coordinate to select, configure, and assemble the correct store template for each user's requirements.

The generated store's **runtime backend is entirely on Supabase** — the ASEA backend is only responsible for the generation process, not for hosting the stores themselves.

### Supabase-First Policy (Required)

Before a generation job can start, the user must connect and verify their own Supabase project credentials. This is a hard prerequisite (Lovable-style BYO Supabase flow):

1. User creates/opens a project
2. User connects Supabase (`/integrations/supabase/test`)
3. Backend stores connection with `status=connected`
4. User starts generation
5. Generation service rejects start if Supabase is not connected

---

## Technology Stack

| Category | Technology | Purpose |
|---|---|---|
| Framework | FastAPI | Async REST API |
| Language | Python 3.12+ | Core backend language |
| Database | PostgreSQL 16 | Primary application database |
| ORM | SQLAlchemy 2.0 (async) | Database models and queries |
| Migrations | Alembic | Database schema version control |
| Cache / Broker | Redis | Task queue broker + API response caching |
| Task Queue | Celery | Background job execution for generation |
| Real-time | Socket.IO (python-socketio) | Live generation progress streaming |
| Auth | JWT (python-jose) + bcrypt | Token-based authentication |
| AI / LLM | Google Gemini API | Requirement → Specification generation |
| AI Agent Framework | LangChain / custom agent loop | Multi-agent code generation system |
| GitHub Integration | PyGitHub | Repository creation and code push |
| Email | Resend API | Transactional emails |
| File Storage | Local filesystem + S3-compatible | Generated project artifacts |
| Validation | Pydantic v2 | Request/response schemas |
| Testing | Pytest + pytest-asyncio | Unit and integration tests |
| Containerization | Docker + Docker Compose | Local development environment |
| Process Manager | Gunicorn + Uvicorn workers | Production ASGI serving |
| Monitoring | Sentry | Error tracking |
| Logging | Structlog | Structured JSON logging |

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        ASEA Backend                          │
│                                                              │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────┐  │
│  │  FastAPI    │    │   Celery     │    │  Socket.IO     │  │
│  │  REST API   │───▶│  Workers     │───▶│  Event Stream  │  │
│  └─────────────┘    └──────────────┘    └────────────────┘  │
│         │                  │                                 │
│         ▼                  ▼                                 │
│  ┌─────────────┐    ┌──────────────────────────────────┐    │
│  │ PostgreSQL  │    │       Agent Orchestrator          │    │
│  │  (App DB)   │    │                                  │    │
│  └─────────────┘    │  ┌──────────┐  ┌─────────────┐  │    │
│                     │  │  Spec    │  │  Template   │  │    │
│  ┌─────────────┐    │  │  Agent   │  │  Selector   │  │    │
│  │   Redis     │    │  └──────────┘  └─────────────┘  │    │
│  │  (Cache +   │    │  ┌──────────┐  ┌─────────────┐  │    │
│  │   Broker)   │    │  │ Module   │  │   Config    │  │    │
│  └─────────────┘    │  │  Agent   │  │   Agent     │  │    │
│                     │  └──────────┘  └─────────────┘  │    │
│  ┌─────────────┐    │  ┌──────────┐  ┌─────────────┐  │    │
│  │  Artifact   │    │  │  File    │  │  Validator  │  │    │
│  │  Storage    │    │  │  Writer  │  │   Agent     │  │    │
│  └─────────────┘    │  └──────────┘  └─────────────┘  │    │
│                     └──────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
  ┌────────────┐      ┌────────────────┐
  │ Gemini API │      │ GitHub API     │
  └────────────┘      └────────────────┘
```

---

## Project Structure

```
asea-backend/
├── app/
│   ├── main.py                  # FastAPI app factory + router registration
│   ├── config.py                # Settings (pydantic-settings)
│   ├── database.py              # Async SQLAlchemy engine + session
│   ├── dependencies.py          # FastAPI dependency injection
│   │
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── project.py
│   │   ├── requirement.py
│   │   ├── specification.py
│   │   ├── generation_job.py
│   │   ├── artifact.py
│   │   ├── integration.py
│   │   └── notification.py
│   │
│   ├── schemas/                 # Pydantic v2 request/response models
│   │   ├── auth.py
│   │   ├── project.py
│   │   ├── requirement.py
│   │   ├── specification.py
│   │   ├── generation.py
│   │   ├── artifact.py
│   │   └── integration.py
│   │
│   ├── routers/                 # FastAPI route handlers
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── projects.py
│   │   ├── requirements.py
│   │   ├── specifications.py
│   │   ├── generation.py
│   │   ├── artifacts.py
│   │   ├── preview.py
│   │   ├── files.py
│   │   ├── integrations.py
│   │   └── notifications.py
│   │
│   ├── services/                # Business logic layer
│   │   ├── auth_service.py
│   │   ├── project_service.py
│   │   ├── requirement_service.py
│   │   ├── specification_service.py
│   │   ├── generation_service.py
│   │   ├── preview_service.py
│   │   ├── artifact_service.py
│   │   ├── github_service.py
│   │   ├── supabase_service.py
│   │   └── email_service.py
│   │
│   ├── agents/                  # Agent system (core)
│   │   ├── orchestrator.py      # Master agent coordinator
│   │   ├── spec_agent.py        # Requirement → Specification agent
│   │   ├── template_agent.py    # Template selection agent
│   │   ├── module_agent.py      # Module selection and application
│   │   ├── config_agent.py      # Configuration injection agent
│   │   ├── file_writer.py       # File assembly and writing
│   │   ├── validator_agent.py   # Output validation agent
│   │   └── base_agent.py        # Base agent class
│   │
│   ├── templates/               # Store template files
│   │   ├── base/                # Base store template (React + Supabase)
│   │   │   ├── frontend/
│   │   │   └── supabase/
│   │   └── modules/             # Feature modules
│   │       ├── auth/
│   │       ├── products/
│   │       ├── cart/
│   │       ├── checkout/
│   │       ├── orders/
│   │       ├── admin/
│   │       ├── inventory/
│   │       ├── reviews/
│   │       ├── wishlist/
│   │       ├── coupons/
│   │       ├── search/
│   │       └── analytics/
│   │
│   ├── tasks/                   # Celery task definitions
│   │   ├── celery_app.py
│   │   ├── generation_tasks.py
│   │   ├── github_tasks.py
│   │   └── email_tasks.py
│   │
│   ├── socketio/                # Socket.IO server
│   │   ├── server.py
│   │   └── events.py
│   │
│   └── utils/
│       ├── security.py          # JWT, password hashing
│       ├── storage.py           # File read/write helpers
│       ├── github.py            # GitHub client wrapper
│       ├── supabase_client.py   # Supabase management client
│       └── formatting.py        # Code formatting helpers
│
├── migrations/                  # Alembic migration files
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## Database Schema (PostgreSQL)

### `users`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | Auto-generated |
| email | VARCHAR UNIQUE | User email |
| hashed_password | VARCHAR | bcrypt hash |
| full_name | VARCHAR | Display name |
| avatar_url | VARCHAR | Profile picture |
| is_active | BOOLEAN | Account status |
| is_verified | BOOLEAN | Email verification |
| plan | ENUM | free / pro / team |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### `projects`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK → users | Owner |
| name | VARCHAR | Store name |
| slug | VARCHAR UNIQUE | URL-safe identifier |
| status | ENUM | draft / generating / ready / deployed |
| thumbnail_url | VARCHAR | Preview screenshot |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

### `requirements`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK → projects | |
| raw_text | TEXT | Original user input |
| enhanced_text | TEXT | AI-enhanced version |
| category | VARCHAR | Store category |
| preferences | JSONB | Color, language, etc. |
| created_at | TIMESTAMPTZ | |

### `specifications`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK → projects | |
| requirement_id | UUID FK → requirements | |
| store_name | VARCHAR | |
| tagline | VARCHAR | |
| modules | JSONB | List of selected modules |
| data_models | JSONB | AI-generated schema |
| pages | JSONB | List of pages |
| features | JSONB | Feature flags |
| api_structure | JSONB | Supabase table plan |
| raw_response | TEXT | Full Gemini response |
| is_confirmed | BOOLEAN | User confirmed before generation |
| created_at | TIMESTAMPTZ | |

### `generation_jobs`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK → projects | |
| specification_id | UUID FK → specifications | |
| celery_task_id | VARCHAR | Celery task reference |
| status | ENUM | pending / running / complete / failed |
| progress | INTEGER | 0–100 |
| current_step | VARCHAR | Human-readable step |
| logs | JSONB | Array of log lines |
| error_message | TEXT | On failure |
| started_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |

### `project_files`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK → projects | |
| file_path | VARCHAR | Relative path (e.g. `src/pages/Home.jsx`) |
| content | TEXT | File content |
| language | VARCHAR | jsx / sql / json / etc. |
| is_editable | BOOLEAN | Inline-edit eligible |
| last_edited_at | TIMESTAMPTZ | |

### `artifacts`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK → projects | |
| storage_path | VARCHAR | Path to zip on storage |
| file_size | BIGINT | Bytes |
| download_count | INTEGER | |
| expires_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | |

### `integrations`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| project_id | UUID FK → projects | |
| type | ENUM | supabase / github |
| encrypted_credentials | TEXT | AES-256 encrypted JSON |
| status | ENUM | pending / connected / failed |
| connected_at | TIMESTAMPTZ | |

### `github_connections`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK → users | |
| github_username | VARCHAR | |
| encrypted_access_token | TEXT | AES-256 encrypted |
| connected_at | TIMESTAMPTZ | |

### `notifications`
| Column | Type | Notes |
|---|---|---|
| id | UUID PK | |
| user_id | UUID FK → users | |
| title | VARCHAR | |
| message | TEXT | |
| type | ENUM | info / success / warning / error |
| is_read | BOOLEAN | |
| project_id | UUID FK (nullable) | Related project |
| created_at | TIMESTAMPTZ | |

---

## API Routes

### Authentication — `/api/v1/auth`

| Method | Path | Description |
|---|---|---|
| POST | `/register` | Create new user account |
| POST | `/login` | Email + password login, returns JWT |
| POST | `/logout` | Invalidate refresh token |
| POST | `/refresh` | Exchange refresh token for new access token |
| POST | `/forgot-password` | Send password reset email |
| POST | `/reset-password` | Set new password via reset token |
| GET | `/me` | Get current authenticated user |
| GET | `/github/callback` | GitHub OAuth callback |
| GET | `/google/callback` | Google OAuth callback |

### Users — `/api/v1/users`

| Method | Path | Description |
|---|---|---|
| GET | `/me` | Get profile |
| PATCH | `/me` | Update profile (name, avatar) |
| POST | `/me/change-password` | Change password |
| DELETE | `/me` | Delete account |
| GET | `/me/sessions` | List active sessions |
| DELETE | `/me/sessions/:id` | Revoke session |
| GET | `/me/notifications` | Paginated notifications |
| PATCH | `/me/notifications/:id/read` | Mark notification as read |
| PATCH | `/me/notifications/read-all` | Mark all as read |

### Projects — `/api/v1/projects`

| Method | Path | Description |
|---|---|---|
| GET | `/` | List all user projects |
| POST | `/` | Create new project |
| GET | `/:id` | Get project detail |
| PATCH | `/:id` | Update project name/settings |
| DELETE | `/:id` | Delete project |
| GET | `/:id/stats` | Project stats (downloads, etc.) |

### Requirements — `/api/v1/projects/:id/requirements`

| Method | Path | Description |
|---|---|---|
| POST | `/` | Submit store requirements |
| GET | `/` | Get requirement for project |
| POST | `/enhance` | AI-enhance raw requirement text |
| PATCH | `/:reqId` | Update requirement |

### Specifications — `/api/v1/projects/:id/specifications`

| Method | Path | Description |
|---|---|---|
| POST | `/generate` | Trigger Gemini spec generation from requirement |
| GET | `/` | Get generated specification |
| PATCH | `/` | Update specification (user edits) |
| POST | `/confirm` | Mark specification as confirmed (ready for generation) |
| POST | `/regenerate` | Re-run spec generation |

### Generation — `/api/v1/projects/:id/generation`

| Method | Path | Description |
|---|---|---|
| POST | `/start` | Start generation Celery job |
| GET | `/status` | Get current job status and progress |
| GET | `/logs` | Get full generation log |
| POST | `/cancel` | Cancel a running generation job |
| POST | `/retry` | Retry a failed generation |

`/start` must return `400` if Supabase integration for that project is not connected.

### Files — `/api/v1/projects/:id/files`

| Method | Path | Description |
|---|---|---|
| GET | `/` | Get full file tree (metadata only) |
| GET | `/:fileId` | Get file content |
| PATCH | `/:fileId` | Update file content (inline edit) |
| GET | `/search` | Search across all project files |

### Preview — `/api/v1/projects/:id/preview`

| Method | Path | Description |
|---|---|---|
| GET | `/:page` | Render page HTML for live preview iframe |
| POST | `/refresh` | Force rebuild preview cache |

### Artifacts — `/api/v1/projects/:id/artifacts`

| Method | Path | Description |
|---|---|---|
| POST | `/build` | Package project into downloadable ZIP |
| GET | `/` | Get artifact metadata |
| GET | `/download` | Stream ZIP file download |

### Integrations — `/api/v1/projects/:id/integrations`

| Method | Path | Description |
|---|---|---|
| POST | `/supabase/connect` | Save and test Supabase credentials |
| POST | `/supabase/migrate` | Run SQL migrations on user's Supabase |
| POST | `/supabase/seed` | Run seed SQL on user's Supabase |
| DELETE | `/supabase/disconnect` | Remove Supabase connection |
| POST | `/github/push` | Push generated project to GitHub repo |
| GET | `/github/status` | Get GitHub push status |

### GitHub OAuth — `/api/v1/integrations/github`

| Method | Path | Description |
|---|---|---|
| GET | `/connect` | Initiate GitHub OAuth flow |
| GET | `/callback` | Handle OAuth callback |
| DELETE | `/disconnect` | Remove GitHub account connection |

---

## Agent System (Core)

The agent system is the intelligence layer of the backend. It replaces generic LLM calls with a **structured pipeline of specialized agents** that each have a narrow, well-defined responsibility. This reduces token usage, increases reliability, and makes the generation deterministic and auditable.

---

### Agent 1 — Specification Agent (`spec_agent.py`)

**Responsibility:** Convert raw user requirements into a structured JSON specification.

**Trigger:** Called when user submits requirements and clicks "Generate Specification".

**Input:**
```json
{
  "raw_text": "I want a fashion store selling streetwear...",
  "category": "fashion",
  "preferences": { "colors": ["#000", "#fff"], "language": "en" }
}
```

**Process:**
1. Sends requirement to Gemini API with a carefully engineered system prompt
2. Gemini returns a structured JSON specification
3. Agent validates the JSON against the `SpecificationSchema` (Pydantic)
4. If validation fails, agent retries with a corrected prompt (up to 3 retries)
5. Saves validated specification to the database

**Output:** A fully structured `Specification` object covering:
- Store name, tagline, color palette
- Module list (which functional modules to include)
- Page list (which pages to generate)
- Data model suggestions (what Supabase tables are needed)
- Feature flags (reviews enabled, wishlist enabled, etc.)
- API structure hints (what Supabase RLS policies to apply)

**Gemini Prompt Design:**
- System prompt is static and versioned (stored in `prompts/spec_prompt_v2.txt`)
- Prompt instructs Gemini to respond ONLY in JSON, no markdown fences
- Prompt includes the full list of available modules and pages as context
- Token budget is tightly controlled (max 2048 output tokens)

---

### Agent 2 — Template Selector Agent (`template_agent.py`)

**Responsibility:** Select the correct base template from the template repository based on the specification.

**Trigger:** After specification is confirmed by user.

**Input:** Confirmed `Specification` object.

**Process:**
1. Reads the specification's `category`, `modules`, and `feature_flags`
2. Scores each available template against the specification (rule-based matching, no LLM needed)
3. Selects the highest-scoring template
4. Returns the template path and a manifest of files it includes

**Template scoring rules (examples):**
- +10 points if spec category matches template primary category
- +5 points per matching module
- -5 points per required module not in template (will need to be added)
- +3 points for color palette compatibility

**Output:**
```json
{
  "template_id": "base_ecommerce_v2",
  "template_path": "templates/base/",
  "matched_modules": ["auth", "products", "cart", "checkout"],
  "missing_modules": ["wishlist", "reviews"],
  "score": 47
}
```

This agent is **fully deterministic** — no LLM calls. It is fast and cheap.

---

### Agent 3 — Module Agent (`module_agent.py`)

**Responsibility:** Select and apply the required feature modules to the base template.

**Trigger:** After template is selected.

**Input:** Template manifest + list of required modules from specification.

**Process:**
1. Iterates through the required module list from the specification
2. For each module, locates the module directory in `templates/modules/`
3. Merges module files into the project file tree:
   - New files are added directly
   - Existing files (e.g., `App.jsx`, `router.jsx`) are merged by applying module patches
4. Module patches are predefined diff-style instructions stored in `module.patch.json` per module
5. Emits a `module_applied` event per module for progress tracking

**Module structure example:**
```
templates/modules/wishlist/
├── module.patch.json          # Instructions for merging into existing files
├── src/
│   ├── pages/WishlistPage.jsx
│   ├── components/WishlistButton.jsx
│   └── hooks/useWishlist.js
└── supabase/
    └── migrations/
        └── 003_wishlist.sql
```

**Output:** Complete merged project file tree in memory (dict of path → content).

---

### Agent 4 — Configuration Agent (`config_agent.py`)

**Responsibility:** Inject specification data into template variables.

**Trigger:** After module agent completes.

**Input:** Merged file tree + Specification object.

**Process:**
1. Scans all files in the file tree for template variable placeholders:
   `{{ STORE_NAME }}`, `{{ PRIMARY_COLOR }}`, `{{ CURRENCY }}`, etc.
2. Builds a variable map from the specification:
   ```python
   vars = {
     "STORE_NAME": spec.store_name,
     "STORE_TAGLINE": spec.tagline,
     "PRIMARY_COLOR": spec.colors.primary,
     "CURRENCY": spec.preferences.currency,
     "SUPABASE_URL": "{{ USER_SUPABASE_URL }}",  # Filled later by user
   }
   ```
3. Replaces all placeholders using string substitution
4. For Supabase-specific variables (URL, keys), injects placeholder strings that the user replaces via the connect flow
5. Uses Jinja2 for conditional template logic:
   ```
   {% if feature.reviews_enabled %}
   // reviews code
   {% endif %}
   ```

**Output:** File tree with all variables resolved and Jinja2 blocks processed.

---

### Agent 5 — File Writer (`file_writer.py`)

**Responsibility:** Persist the generated file tree to the database and filesystem.

**Trigger:** After configuration agent completes.

**Input:** Fully resolved file tree (dict of path → content).

**Process:**
1. Creates a project directory on the filesystem: `storage/projects/{project_id}/`
2. Writes each file to disk
3. Inserts a `project_files` record per file in PostgreSQL
4. Tags files as `is_editable=True` for JSX/HTML files that can be inline edited
5. Injects `data-editable-id` attributes into all JSX/HTML text elements for inline editing
6. Emits file write progress events

**Output:** All files written to disk and recorded in the database.

---

### Agent 6 — Validator Agent (`validator_agent.py`)

**Responsibility:** Verify the generated project is structurally complete and correct.

**Trigger:** After file writer completes.

**Input:** Project directory path + expected file manifest.

**Process:**
1. **Structural check** — verifies all required files exist:
   - `package.json`
   - `src/main.jsx`
   - `src/App.jsx`
   - `supabase/migrations/*.sql`
   - `src/lib/supabase.js`
2. **Configuration check** — verifies `package.json` has required dependencies
3. **Placeholder check** — scans for any unreplaced `{{ }}` tokens (indicates config agent missed something)
4. **SQL check** — validates migration files have valid SQL syntax (using `sqlparse`)
5. **Import check** — scans JSX files for broken import paths (basic regex-based check)

If any check fails:
- Log the error with full context
- Attempt auto-fix for known issues (e.g., add missing import)
- If unfixable, mark the generation job as failed with a detailed error message
- Emit error event to Socket.IO

**Output:** Validation report. On success, triggers artifact packaging.

---

### Agent Orchestrator (`orchestrator.py`)

The orchestrator is the master controller that runs the full agent pipeline inside a Celery task.

```python
class GenerationOrchestrator:
    def __init__(self, project_id, job_id, socket_emitter):
        self.project_id = project_id
        self.job_id = job_id
        self.emit = socket_emitter

    async def run(self, specification):
        try:
            self._update(5, "Initializing generation pipeline")

            # Agent 1 — already done (spec was pre-generated and confirmed)
            spec = specification

            self._update(15, "Selecting base template")
            template = await TemplateAgent().select(spec)

            self._update(30, "Applying feature modules")
            file_tree = await ModuleAgent().apply(template, spec)

            self._update(55, "Injecting configuration")
            file_tree = await ConfigAgent().inject(file_tree, spec)

            self._update(70, "Writing project files")
            await FileWriter().write(self.project_id, file_tree)

            self._update(85, "Validating generated project")
            validation = await ValidatorAgent().validate(self.project_id)

            if not validation.passed:
                raise GenerationError(validation.errors)

            self._update(95, "Packaging artifact")
            await ArtifactService().package(self.project_id)

            self._update(100, "Generation complete")
            self.emit('generation:complete', { 'project_id': self.project_id })

        except Exception as e:
            self.emit('generation:error', { 'message': str(e) })
            raise

    def _update(self, progress, step):
        update_job_progress(self.job_id, progress, step)
        self.emit('generation:progress', { 'percent': progress, 'step': step })
        log_generation_step(self.job_id, step)
```

---

## Celery Tasks

### `generation_tasks.py`

```python
@celery_app.task(bind=True, max_retries=2, name="tasks.generate_store")
def generate_store(self, project_id: str, job_id: str):
    """
    Main generation task. Runs the full agent pipeline.
    Retries on transient errors (network, Gemini timeout).
    Does NOT retry on validation failures.
    """
    try:
        specification = get_confirmed_specification(project_id)
        orchestrator = GenerationOrchestrator(project_id, job_id, emit_to_room)
        run_async(orchestrator.run(specification))
    except TransientError as e:
        raise self.retry(exc=e, countdown=30)
    except GenerationError:
        mark_job_failed(job_id)
        raise

@celery_app.task(name="tasks.package_artifact")
def package_artifact(project_id: str):
    """Compresses the project directory into a ZIP artifact."""
    ArtifactService().package(project_id)

@celery_app.task(name="tasks.push_to_github")
def push_to_github(project_id: str, user_id: str, repo_config: dict):
    """Handles GitHub repo creation and code push."""
    GitHubService().push(project_id, user_id, repo_config)
```

---

## Socket.IO Events

The Socket.IO server runs alongside FastAPI using `python-socketio` with an ASGI mount.

### Client → Server Events

| Event | Payload | Description |
|---|---|---|
| `join_project` | `{ project_id }` | Join room to receive project events |
| `leave_project` | `{ project_id }` | Leave project room |

### Server → Client Events

| Event | Payload | Description |
|---|---|---|
| `generation:progress` | `{ percent, step }` | Progress update |
| `generation:log` | `{ line, level, timestamp }` | Log line from agent pipeline |
| `generation:complete` | `{ project_id }` | Generation finished successfully |
| `generation:error` | `{ message, step }` | Generation failed |
| `github:push:progress` | `{ step, percent }` | GitHub push progress |
| `github:push:complete` | `{ repo_url }` | GitHub push finished |
| `supabase:migrate:progress` | `{ migration, status }` | Per-migration status |
| `notification` | `{ title, message, type }` | Real-time in-app notification |

---

## Supabase Integration Service

When a user connects their Supabase project, the backend:

1. **Validates credentials** by making a test call to `POST {supabase_url}/rest/v1/rpc/` with the service role key
2. **Runs migrations** by executing each SQL file in `supabase/migrations/` in order using the Supabase Management API or direct PostgreSQL connection via the service role
3. **Injects user credentials** into the project's `.env` file and the `src/lib/supabase.js` file
4. **Optionally seeds** demo data by executing `supabase/seed.sql`
5. **Updates the integration record** in the database with encrypted credentials

Credentials (Supabase URL and keys) are encrypted at rest using AES-256 with a server-side secret before being stored in the `integrations` table.

---

## GitHub Integration Service

### OAuth Flow

1. User clicks "Connect GitHub"
2. Backend redirects user to GitHub OAuth authorization URL with `repo` and `read:user` scopes
3. User authorizes on GitHub
4. GitHub redirects to `/api/v1/integrations/github/callback?code=xxx`
5. Backend exchanges code for access token using GitHub API
6. Access token is encrypted and stored in `github_connections`
7. Frontend is redirected to the deploy page with `?github=connected`

### Push Flow

1. User submits repo config (name, visibility, org, branch, commit message)
2. `push_to_github` Celery task is queued
3. Task uses `PyGitHub` to:
   - Create the repository
   - Create a Git tree from the project files
   - Create an initial commit
   - Push to the default branch
4. Progress events emitted via Socket.IO per step
5. On completion, repo URL is saved to the integration record and returned to the frontend

---

## Preview Service

The preview service renders the generated store's pages as HTML for the frontend's live preview iframe.

**Approach:** Since the store is a React app, the backend cannot run it server-side without a Node.js runtime. Instead:

1. During generation, the File Writer also generates **static HTML snapshots** of each page using a pre-built HTML shell that includes the Tailwind CDN and the page's component rendered as static HTML (via a lightweight Python HTML generator that reads the JSX template variables).
2. These HTML snapshots are stored alongside the project files.
3. The preview endpoint serves these HTML snapshots with injected `data-editable-id` attributes.
4. When a user makes an inline edit, the backend updates both the JSX source file AND regenerates the HTML snapshot for that page.

This approach is fast, requires no Node.js process, and gives an accurate visual representation.

---

## Security Architecture

### Authentication

- **Access tokens:** JWT, signed with HS256, expire in 15 minutes
- **Refresh tokens:** Opaque tokens stored as `httpOnly` cookies, expire in 30 days
- **Password hashing:** bcrypt with work factor 12
- **OAuth state parameter:** CSRF protection on all OAuth flows

### Authorization

- All routes use `Depends(get_current_user)` dependency
- Project ownership verified on every project route: `project.user_id == current_user.id`
- Admin-only routes protected with `Depends(require_admin)` (for internal tooling)

### Data Security

- Supabase credentials and GitHub access tokens encrypted at rest with AES-256 using `cryptography` library
- Encryption key stored as environment variable, never in the database
- All API keys masked in logs

### Rate Limiting

- `slowapi` middleware for rate limiting:
  - Auth endpoints: 10 requests / minute per IP
  - Spec generation: 5 requests / minute per user
  - Generation start: 2 requests / minute per user
  - All other endpoints: 100 requests / minute per user

### Input Validation

- All request bodies validated by Pydantic v2 schemas
- File path inputs sanitized to prevent directory traversal
- Requirement text length capped at 5,000 characters

---

## Caching Strategy (Redis)

| Cache Key | TTL | Contents |
|---|---|---|
| `user:{id}:profile` | 5 min | User profile |
| `project:{id}:detail` | 2 min | Project + status |
| `project:{id}:file_tree` | 10 min | File tree metadata |
| `project:{id}:preview:{page}` | 5 min | Rendered HTML snapshot |
| `job:{id}:status` | 30 s | Generation job status |
| `spec:{id}` | 30 min | Specification object |

Cache is invalidated on write operations via explicit `cache.delete(key)` calls in service methods.

---

## Error Handling

- All routes wrapped in consistent exception handlers
- Custom exception classes: `GenerationError`, `IntegrationError`, `ValidationError`, `NotFoundError`
- Global FastAPI exception handler returns consistent error response format:
  ```json
  {
    "error": "generation_failed",
    "message": "Validator agent found missing required file: src/main.jsx",
    "code": 422,
    "details": { "missing_files": ["src/main.jsx"] }
  }
  ```
- All unhandled exceptions captured by Sentry
- Failed Celery tasks automatically create a notification for the user

---

## Environment Variables

```env
# App
APP_ENV=production
SECRET_KEY=your-secret-key-here
ENCRYPTION_KEY=your-aes-256-key-here

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/asea

# Redis
REDIS_URL=redis://localhost:6379/0

# Gemini
GEMINI_API_KEY=your-gemini-key

# GitHub OAuth
GITHUB_CLIENT_ID=your-github-client-id
GITHUB_CLIENT_SECRET=your-github-client-secret
GITHUB_REDIRECT_URI=https://api.asea.app/api/v1/integrations/github/callback

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Email
RESEND_API_KEY=your-resend-key
EMAIL_FROM=noreply@asea.app

# Storage
STORAGE_PATH=/var/asea/projects
ARTIFACT_PATH=/var/asea/artifacts

# Monitoring
SENTRY_DSN=your-sentry-dsn

# Frontend
FRONTEND_URL=https://asea.app
CORS_ORIGINS=["https://asea.app", "http://localhost:5173"]
```

---

## Deployment Architecture (Production)

```
┌──────────────────────────────────────────────────┐
│                  Load Balancer                   │
│              (Nginx / AWS ALB)                   │
└──────────────────┬───────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
┌───────▼────────┐   ┌────────▼───────┐
│ FastAPI + ASGI │   │  Socket.IO     │
│ (Gunicorn x4)  │   │  Server (x2)   │
└───────┬────────┘   └────────┬───────┘
        │                     │
        └──────────┬──────────┘
                   │
     ┌─────────────┼─────────────┐
     │             │             │
┌────▼────┐  ┌────▼────┐  ┌────▼────┐
│ Postgres │  │  Redis  │  │ Celery  │
│ (RDS)   │  │(ElastiC.)│  │ Workers │
└─────────┘  └─────────┘  └────┬────┘
                                │
                    ┌───────────▼──────────┐
                    │  File Storage (S3 /  │
                    │  DigitalOcean Spaces) │
                    └──────────────────────┘
```

- **FastAPI:** 4+ Gunicorn workers with Uvicorn worker class
- **Celery:** 4+ worker processes, dedicated queue for generation vs email tasks
- **Redis:** Cluster mode for high availability
- **PostgreSQL:** Managed instance (AWS RDS or Supabase itself for the ASEA platform DB)
- **File Storage:** S3-compatible for artifact ZIPs (large files not suited for PostgreSQL)

---

## Development Order (Backend)

1. Project scaffold (FastAPI + SQLAlchemy + Alembic + Docker Compose)
2. Database models and initial migration
3. Authentication system (register, login, JWT, refresh tokens)
4. User and project CRUD routes
5. Supabase integration service (connect, status, validate credentials)
6. Requirement submission and storage
7. Gemini API integration (Specification Agent)
8. Specification review and confirmation routes
9. Template repository structure and base template
10. Module Agent + Config Agent
11. File Writer and project file storage
12. Validator Agent
13. Agent Orchestrator
14. Celery task integration
15. Socket.IO server and real-time progress events
16. Preview service (HTML snapshot generation)
17. Inline file edit endpoint
18. Artifact packaging (ZIP generation and download)
19. Supabase migration + seed execution pipeline
20. GitHub OAuth and push service
21. Notification system
22. Rate limiting, caching, security hardening
23. Monitoring (Sentry, structured logging)
24. Testing (Pytest unit + integration tests)
25. CI/CD pipeline and production deployment
