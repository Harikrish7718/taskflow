# TaskFlow API

A production-grade example backend: **FastAPI + PostgreSQL + Redis + Kafka + JWT auth**,
containerized with Docker, migrated with Alembic, tested with pytest, and
shipped via GitHub Actions CI/CD to a real free-forever server.

This README has two jobs:
1. Explain every concept and every file, assuming you're learning this for the first time
2. Walk you through the exact steps that take you from this repo to a live, publicly reachable, production-configured system — if you follow Part 3 in order, you end up with a real deployed app, not a toy.

---

## Part 1 — Concepts You Asked About

### What is ASGI?

**ASGI = Asynchronous Server Gateway Interface.** It's a *specification* (a contract), not a piece of software you install. It defines how a Python web framework and a web server talk to each other, so any ASGI-compliant server (Uvicorn, Hypercorn, Daphne) can run any ASGI-compliant framework (FastAPI, Starlette, Django-async).

Why it exists: the older standard, **WSGI**, was designed before Python had `async`/`await`. WSGI can only handle one request per worker at a time — the worker is *blocked* until that request finishes. ASGI lets a single worker juggle many requests concurrently using `async def`, which matters enormously for I/O-bound work (waiting on a database, an external API, a WebSocket) because the worker can start handling request B while it's waiting on request A's database call to return.

```python
# This function can run concurrently with other requests while it's "waiting"
@app.get("/tasks")
async def list_tasks():
    result = await db.fetch_all("SELECT * FROM tasks")  # worker is freed during this wait
    return result
```

Note: in this repo we actually use **synchronous** route handlers (`def`, not `async def`) because SQLAlchemy's classic session API is synchronous. FastAPI handles this gracefully — it runs sync routes in a thread pool so they don't block the event loop. This is a completely normal, common production pattern. You'd reach for `async def` + an async DB driver (like `asyncpg`) if you needed to squeeze out more concurrent throughput per server, which most apps don't need on day one.

### What is Uvicorn?

**Uvicorn is an ASGI server** — the actual program that listens on a port, speaks raw HTTP, and hands each request to your FastAPI app according to the ASGI spec. FastAPI is just Python code; it can't listen on a network port by itself. Uvicorn is the thing that makes `http://localhost:8000` actually respond.

```bash
uvicorn app.main:app --reload
#        ^module:variable   ^dev-only autoreload flag
```

In production we don't run Uvicorn directly — we run it *under* **Gunicorn**, a battle-tested process manager. Gunicorn's job is to start N worker processes (each running its own Uvicorn instance), restart any worker that crashes, and load-balance requests across them. One Uvicorn process = one CPU core's worth of concurrency; Gunicorn is what lets you use all the cores on the machine.

```
Gunicorn (process manager)
+-- Uvicorn worker 1 (own process, own event loop)
+-- Uvicorn worker 2
+-- Uvicorn worker 3
+-- Uvicorn worker 4
```

This is exactly what `Dockerfile`'s final `CMD` does:
```
gunicorn app.main:app --workers 4 --worker-class uvicorn.workers.UvicornWorker ...
```

### What is Alembic?

**Alembic is a database migration tool** for SQLAlchemy. A "migration" is a small versioned script that describes *one change* to your database schema — "add this table," "add this column," "rename that index." Think of it as git for your database structure.

Why not just call `Base.metadata.create_all()` (which creates tables from your models) in production? Because that only handles the very first creation. The moment you need to add a column to a table that already has real user data in it, `create_all()` does nothing — it only creates tables that don't exist yet. You need something that can say "here's exactly how to transform version 3 of the schema into version 4, and here's how to undo it." That's Alembic.

```bash
# You changed app/models.py - now generate the matching migration
alembic revision --autogenerate -m "add priority field to tasks"

# This creates a file like alembic/versions/0002_add_priority.py containing:
def upgrade():
    op.add_column('tasks', sa.Column('priority', sa.Integer, server_default='0'))
def downgrade():
    op.drop_column('tasks', 'priority')

# Apply it
alembic upgrade head
```

Every environment (your laptop, CI, production) runs the exact same ordered sequence of migration files, so the schema is always in a known, reproducible state — never hand-edited via a database GUI.

### What is Kafka (and why does this repo use Redpanda instead)?

**Kafka is an event streaming platform.** The core idea: instead of Service A directly calling Service B ("hey, a task was created, please do something"), Service A just publishes a fact — **"a task was created"** — to a durable, ordered log called a **topic**. Any number of other services can independently subscribe to that topic and react, at their own pace, without Service A knowing or caring who's listening.

```
                    +--------------+
   API publishes    |              |   Consumer 1 (stats)
   "task.created" ->|  Kafka topic |-> Consumer 2 (email) [not built here, but could be added
                    | tasks-events |-> Consumer 3 (search index)   without touching the API]
                    +--------------+
```

This is fundamentally different from a normal function call:

| Direct call (e.g. Redis cache) | Kafka event |
|---|---|
| Caller waits for the callee | Caller (the API) doesn't wait at all |
| Caller must know exactly who to call | Publisher doesn't know who (if anyone) is listening |
| If the callee is down, the caller usually fails too | Events sit durably in the topic; a consumer that was down catches up when it comes back |
| One-to-one | One-to-many (many independent consumers) |

**In this repo:** `POST /tasks`, `PATCH /tasks/{id}`, and `DELETE /tasks/{id}` each publish an event (`task.created` / `task.updated` / `task.deleted`) to a topic called `tasks-events`. A completely separate process, `app/consumer.py`, subscribes to that topic and maintains live counters in Redis (total tasks created, tasks by status). The `GET /stats` endpoint just reads those counters. **This is the actual proof the pipeline works** — those numbers are populated by an independent process, not computed synchronously by the API.

**Why Redpanda instead of Apache Kafka itself?** Apache Kafka historically required also running Zookeeper (a separate coordination service) — two moving parts, meaningfully more memory, more startup complexity. Redpanda is a single binary that speaks the exact same Kafka wire protocol (any Kafka client library, including the one this repo uses, works against it completely unmodified), but needs a fraction of the resources — which matters a lot on a free-tier server. If you specifically need Apache Kafka itself (e.g. for a feature Redpanda doesn't support), you can swap the image in `docker-compose.yml` for `apache/kafka:latest` and nothing in the application code needs to change, because the application only ever talks the Kafka protocol, never anything Redpanda-specific.

---

## Part 2 — What Every File in This Repo Does

```
taskflow/
+-- app/
|   +-- main.py            # Creates the FastAPI app, wires in middleware + routers, /health endpoint
|   +-- config.py          # All settings (DB URL, Redis URL, Kafka broker, JWT secret) read from env vars
|   +-- database.py        # SQLAlchemy engine + session factory + get_db() dependency
|   +-- models.py          # ORM classes: User, Task - these define the actual DB table structure
|   +-- schemas.py         # Pydantic classes - define what JSON in/out of the API looks like (validation)
|   +-- cache.py           # Redis cache-aside helpers: cache_get/cache_set/cache_delete, fail-open
|   +-- kafka_client.py    # Kafka producer wrapper: publish_event(), fail-open, lazy-connects
|   +-- consumer.py        # STANDALONE process (not part of the API) - consumes tasks-events, updates Redis stats
|   +-- auth.py            # get_current_user() dependency - decodes the JWT from the Authorization header
|   +-- core/security.py   # Password hashing (bcrypt) and JWT encode/decode - the actual crypto
|   +-- routers/
|       +-- users.py       # POST /auth/signup, POST /auth/login, GET /users/me
|       +-- tasks.py       # Full CRUD on /tasks - this is where caching AND Kafka publishing both happen
|       +-- stats.py       # GET /stats - proves the Kafka pipeline is alive by reading consumer-derived data
|
+-- alembic/
|   +-- env.py              # Tells Alembic how to find your models and DB URL
|   +-- versions/0001_initial.py   # The one migration so far: creates users + tasks tables
|
+-- tests/
|   +-- conftest.py        # Test fixtures: in-memory SQLite DB, fake Redis, fake Kafka producer
|   +-- test_users.py      # 6 tests: signup, login, auth enforcement
|   +-- test_tasks.py      # 8 tests: CRUD, caching behavior, per-user isolation
|   +-- test_kafka.py      # 4 tests: events actually get published on create/update/delete, /stats shape
|   +-- test_kafka_integration.py  # 1 test against a REAL broker - only runs in CI, skipped locally by default
|
+-- Dockerfile              # Multi-stage build: build deps in one stage, slim runtime in the next
+-- docker-compose.yml      # Local dev: api + consumer + postgres + redis + redpanda, all wired together
+-- docker-compose.prod.yml # Production override: pulls the CI-built image instead of building on the server
+-- .env.example            # Template for the real .env file (never commit the real one)
+-- requirements.txt        # Production dependencies
+-- requirements-dev.txt    # + pytest, ruff, fakeredis (dev/test only)
+-- .github/workflows/
    +-- ci.yml              # Runs on every push/PR: lint, real Postgres+Redis+Redpanda, full test suite, Docker build check
    +-- cd.yml              # Runs after CI passes on main: build+push image to GHCR, SSH-deploy to your server
```

### The request lifecycle through this codebase, concretely

`POST /tasks` with a JWT and `{"title": "Ship it"}`:

1. `app/main.py`'s logging middleware starts a timer
2. `app/auth.py`'s `get_current_user` dependency runs first (FastAPI dependency injection): decodes the JWT via `core/security.py`, loads the `User` row
3. `app/schemas.py`'s `TaskCreate` Pydantic model validates the JSON body
4. `app/routers/tasks.py`'s `create_task` runs: inserts a `Task` row via `app/database.py`'s session
5. `cache_delete()` (from `app/cache.py`) invalidates that user's cached task list in Redis
6. `_publish_task_event()` schedules a Kafka publish as a **background task** — the HTTP response is returned to the client *before* this runs
7. Separately, in its own process, `app/consumer.py` eventually receives that event and increments Redis counters
8. The response is serialized against `TaskOut` and sent back
9. The logging middleware logs the method, path, status, and duration

---

## Part 3 — Deploying to Production

### First, an honest platform comparison (verified July 2026)

Free-tier terms change constantly, so here's what's actually true right now, not marketing copy:

| Platform | Free tier reality | Verdict for this stack |
|---|---|---|
| **Fly.io** | Free tier was removed in 2024. New accounts get a ~2-hour or 7-day trial, then require a credit card and billing. | Not actually free anymore -- skip it unless you're okay paying (roughly $8-20/mo for this stack) |
| **Render** | Free web services exist (no card required) but spin down after 15 min idle (30-60s cold start), and free Postgres **expires after 30 days**. No free tier for an always-on background worker like our consumer. | Fine for demoing the API alone; not viable for the always-on consumer + Kafka broker this stack needs |
| **Railway** | No real free tier anymore -- a small monthly credit that's consumed by any real usage | Not free for always-on services |
| **Oracle Cloud "Always Free"** | Genuinely permanent, no expiry: as of mid-2026, new free-tier accounts get **2 Arm CPUs + 12 GB RAM** (existing accounts may retain the older 4 CPU / 24 GB allowance). Requires a credit card for identity verification only -- you are not charged unless you explicitly upgrade. | **The only option here that's actually free forever and can run an always-on multi-container stack (Postgres + Redis + Kafka + API + consumer) simultaneously.** This is what the deployment guide uses. |

**Bottom line:** this stack has a persistent database, a persistent cache, a persistent message broker, and a persistent background consumer -- that's a "real server" workload, not a serverless one. There is currently no platform that hosts that combination for free without either sleeping (breaks the consumer) or expiring (breaks the database). A small free-forever VM is the honest answer for this stack in 2026.

*(If you want the API alone without Kafka, without a card: deploy just the `api` service to Render's free tier with a permanent free Postgres from Neon and free Redis from Upstash. Live in ~10 minutes, but no working Kafka pipeline -- Upstash discontinued its Kafka product in 2025.)*

### The full walkthrough lives in a separate file

**See [DEPLOYMENT.md](./DEPLOYMENT.md)** for the complete, click-by-click, command-by-command guide -- it was getting too long to keep inline here. It covers, in order:

1. Creating the Oracle Cloud account and VM (every field, every click)
2. Opening both firewall layers correctly (the #1 source of "why can't I reach my server" problems)
3. Installing Docker and doing a first manual deploy, with a health check for every individual service
4. Pushing to GitHub and setting up a dedicated deploy-only SSH key (not your personal one)
5. Wiring up the three GitHub Actions secrets that make CD work
6. Watching your first automated CI -> CD run end to end
7. Proving the whole pipeline works with real curl commands against your live server
8. Optional HTTPS setup with a real domain
9. A troubleshooting section for the specific errors people actually hit at each step
10. Ongoing operations: redeploying, rolling back, checking logs, backing up the database

If you're following it for the first time, budget 45-90 minutes, mostly spent waiting on Oracle's account approval -- every push after that first setup deploys itself with zero manual steps.

---

## What "done" looks like

If you've followed Part 3 in order, you now have:
- A public URL serving a real FastAPI app, backed by real PostgreSQL and Redis
- A real Kafka-protocol broker with a live producer (the API) and consumer (`app/consumer.py`) proving the event pipeline works, visible via `/stats`
- Every push to `main` automatically lints, tests against real infrastructure, builds a Docker image, and redeploys your live server -- with zero manual steps after the initial setup
- Zero recurring cost, using infrastructure that doesn't expire or sleep

## Local Quick Reference

```bash
docker compose up --build                # start everything locally (api, consumer, db, redis, redpanda)
docker compose logs -f consumer          # watch Kafka events being consumed in real time
docker compose exec redpanda rpk topic consume tasks-events   # inspect raw events on the topic
alembic revision --autogenerate -m "msg" # new migration after changing models.py
pytest tests/ -v                          # 18 tests, ~9s, no real infra needed
TASKFLOW_KAFKA_INTEGRATION=1 pytest tests/test_kafka_integration.py  # needs `docker compose up -d redpanda` first
ruff check app tests                      # lint
```
