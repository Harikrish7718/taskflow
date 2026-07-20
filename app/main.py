import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import users, tasks, stats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("taskflow")

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Production-grade example API: FastAPI + PostgreSQL + Redis + JWT auth",
)

# CORS - lock this down to real frontend origins in production via env config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms:.1f}ms)")
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
    return response


@app.get("/health", tags=["ops"])
def health_check():
    """Used by load balancers / orchestrators to know the app is alive."""
    return {"status": "ok", "environment": settings.environment}


app.include_router(users.router)
app.include_router(tasks.router)
app.include_router(stats.router)
