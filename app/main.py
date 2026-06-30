"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .auth import LoginRequired, create_user
from .config import config
from .db import User, engine, get_settings, init_db
from .routes import auth_routes, feed, media, messages, ui
from .health import get_health_report, run_liveness_checks
from .scheduler import shutdown_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _bootstrap() -> None:
    init_db()
    with Session(engine) as session:
        get_settings(session)  # ensure the singleton settings row exists
        has_users = session.exec(select(User)).first() is not None
        if not has_users and config.bootstrap_username and config.bootstrap_password:
            create_user(session, config.bootstrap_username, config.bootstrap_password)
            logger.info("Created bootstrap user %r", config.bootstrap_username)
        elif not has_users:
            logger.warning(
                "No users exist. Set BOOTSTRAP_USERNAME and BOOTSTRAP_PASSWORD to create the first user."
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bootstrap()
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


app = FastAPI(title="Morning News Podcast Generator", lifespan=lifespan)

# Trust X-Forwarded-* from reverse proxies so request.base_url reflects the public URL.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.add_middleware(
    SessionMiddleware,
    secret_key=config.session_secret,
    same_site="lax",
    max_age=60 * 60 * 24 * 30,
)


@app.middleware("http")
async def attach_health_summary(request: Request, call_next):
    path = request.url.path
    if path.startswith("/static") or path == "/healthz":
        request.state.health_has_issues = False
        request.state.health_issue_count = 0
        return await call_next(request)

    report = get_health_report()
    request.state.health_has_issues = report.has_issues
    request.state.health_issue_count = report.issue_count
    return await call_next(request)

_STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


app.include_router(auth_routes.router)
app.include_router(ui.router)
app.include_router(messages.router)
app.include_router(feed.router)
app.include_router(media.router)


@app.get("/healthz")
def healthz():
    report = run_liveness_checks()
    payload = report.to_dict()
    if report.has_issues:
        return JSONResponse({"status": "degraded", **payload}, status_code=503)
    return {"status": "ok", **payload}
