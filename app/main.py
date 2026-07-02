"""FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .auth import LoginRequired, create_user, get_optional_user
from .config import config
from .db import User, engine, get_settings, init_db
from .routes import auth_routes, feed, media, messages, ui
from .health import get_health_report
from .scheduler import shutdown_scheduler, start_scheduler
from .templating import templates

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _bootstrap() -> None:
    database_path = config.data_dir / "morning_news.db"
    if database_path.exists():
        logger.info("Using database at %s", database_path)
    else:
        logger.info("Creating new database at %s", database_path)
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


def _current_user_or_none(request: Request) -> User | None:
    """Best-effort user lookup for error pages; never raises."""
    try:
        with Session(engine) as session:
            return get_optional_user(request, session)
    except Exception:
        return None


def _render_error_page(request: Request, status_code: int):
    if status_code == 404:
        context = {
            "error_title": "That page isn't here",
            "error_message": "The address may have changed, or the link is out of date.",
            "error_detail": "Nothing is broken — the page just doesn't exist.",
        }
    else:
        context = {
            "error_title": "Something went wrong on our side",
            "error_message": "Morning News hit an unexpected problem loading this page.",
            "error_detail": (
                "Your settings and episodes are safe. Try again in a moment — "
                "if it keeps happening, the server log will say why."
            ),
        }
    user = _current_user_or_none(request)
    context.update(
        {
            "user": user,
            "active": None,
            "error_back_href": "/" if user else "/login",
            "error_back_label": "Back to the dashboard" if user else "Go to sign in",
        }
    )
    # The health middleware normally sets these; guarantee them so the error
    # page can never itself error while rendering the shared chrome.
    if not hasattr(request.state, "health_has_issues"):
        request.state.health_has_issues = False
        request.state.health_issue_count = 0
    return templates.TemplateResponse(request, "error.html", context, status_code=status_code)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404 and not request.url.path.startswith("/api"):
        return _render_error_page(request, 404)
    if exc.status_code >= 500:
        logger.error("HTTP %s on %s: %s", exc.status_code, request.url.path, exc.detail)
        return _render_error_page(request, exc.status_code)
    # Everything else keeps FastAPI's default JSON error shape.
    headers = getattr(exc, "headers", None)
    if exc.status_code in {204, 304}:
        return Response(status_code=exc.status_code, headers=headers)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=headers)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s", request.url.path)
    return _render_error_page(request, 500)


app.include_router(auth_routes.router)
app.include_router(ui.router)
app.include_router(messages.router)
app.include_router(feed.router)
app.include_router(media.router)


@app.get("/healthz")
def healthz():
    """Liveness probe for Docker — must stay cheap; dependency checks run on a schedule."""
    return {"status": "ok"}
