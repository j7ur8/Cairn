import json
import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware

from cairn import __version__
from cairn.server import db
from cairn.server.background import BackgroundTasks
from cairn.server.domain.errors import DomainError
from cairn.server.observability import routers as observability_routers
from cairn.server.routers import (
    ai_profiles,
    attachments,
    auth,
    capabilities,
    execution_configs,
    export,
    files,
    hints,
    intents,
    projects,
    project_proxy,
    prompt_groups,
    replay,
    servers,
    settings,
    task_types,
)
from cairn.server.routers import system_config as system_config_router
from cairn.server.runtime_config import system_config
from cairn.server.security.deps import current_user_optional
from cairn.server.security.users import bootstrap_superuser_if_configured
from cairn.shared.observability.logging import configure_logging
from cairn.shared.observability.metrics import (
    HTTP_LATENCY,
    HTTP_REQUESTS,
    render_metrics,
)
from cairn.shared.observability.trace import (
    get_trace_id,
    new_trace_id,
    set_trace_id,
)

STATIC_DIR = Path(__file__).parent / "static"
PARTIALS_DIR = Path(__file__).parent / "partials"
LOG = logging.getLogger(__name__)

# The SPA shell is authored as verbatim HTML fragments under partials/ and
# concatenated here in document order. The fragments are not individually
# well-formed and are never served by URL; only this join produces the page.
# This tuple is the document order; partials/ is the source of truth.
INDEX_PARTIALS = (
    "_doc_open.html",
    "shell_nav.html",
    "shell_content_open.html",
    "view_list.html",
    "view_graph.html",
    "view_settings.html",
    "shell_main_close.html",
    "view_new_project.html",
    "shell_close.html",
    "modals/_replay_config.html",
    "modals/_intent.html",
    "modals/_conclude.html",
    "modals/_complete.html",
    "modals/_hint.html",
    "modals/_reopen.html",
    "modals/_rename.html",
    "modals/_local_prefs.html",
    "modals/_export_yaml.html",
    "modals/_delete.html",
    "login.html",
    "toast.html",
    "_doc_close.html",
)

_INCLUDE_RE = re.compile(r'\{\{\s*include\s+"([^"]+)"(?:\s+(.+?))?\s*\}\}')


def _parse_include_params(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    params: dict[str, str] = {}
    for chunk in raw.split(";"):
        item = chunk.strip()
        if not item:
            continue
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"invalid include parameter: {item}")
        params[key.strip()] = value.strip()
    return params


def _render_partial(name: str) -> str:
    text = (PARTIALS_DIR / name).read_text(encoding="utf-8")

    def replace(match: re.Match[str]) -> str:
        include_name = match.group(1)
        params = _parse_include_params(match.group(2))
        content = _render_partial(include_name)
        for key, value in params.items():
            content = content.replace(f"[[{key}]]", value)
        return content

    return _INCLUDE_RE.sub(replace, text)


def assemble_index() -> str:
    """Concatenate the SPA shell fragments into the full index document."""
    return "".join(_render_partial(name) for name in INDEX_PARTIALS)


class NoStoreStaticFiles(StaticFiles):
    """StaticFiles variant that disables browser caching.

    Cairn ships a no-build SPA where vendor assets under /static are
    edited in place. Keeping these assets cached can make the browser
    serve a stale UI after a deployment, so every static response is
    forced to revalidate.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Bind a trace id to every request, emit ``X-Request-Id`` back.

    Honors an inbound ``X-Request-Id`` if the upstream proxy / load
    balancer already minted one; otherwise a fresh id is generated.
    The trace id rides every log line and every outbound call via
    :data:`cairn.shared.observability.trace.trace_id_var`, so a single
    request can be followed from the HTTP edge through the
    dispatcher loop without manual correlation.
    """

    async def dispatch(self, request, call_next):
        inbound = request.headers.get("x-request-id")
        token = set_trace_id(inbound or new_trace_id())
        request.state.trace_id = get_trace_id()
        start = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-Id"] = get_trace_id() or ""
            # Latency histogram is labeled by the templated path so
            # high-cardinality ids do not blow up the time series.
            template = request.scope.get("route").path if request.scope.get("route") else request.url.path
            HTTP_REQUESTS.labels(
                method=request.method,
                path=template,
                status=str(status_code),
            ).inc()
            HTTP_LATENCY.labels(method=request.method, path=template).observe(
                time.monotonic() - start
            )
            return response
        finally:
            from cairn.shared.observability.trace import reset_trace_id
            reset_trace_id(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = system_config()
    configure_logging(
        level=runtime.server.log_level,
        fmt=runtime.server.log_format,
        component="cairn.server",
    )
    # Assemble the SPA shell from partials once at startup; the route serves
    # this cached string. Frozen here so per-request handling stays allocation
    # free and the fragment reads never hit the hot path.
    app.state.index_html = assemble_index()
    db.configure()
    try:
        bootstrap_superuser_if_configured()
    except Exception:  # noqa: BLE001 - never let bootstrap break startup
        import logging
        logging.getLogger(__name__).exception("superuser bootstrap failed")
    background_tasks = BackgroundTasks(runtime)
    background_tasks.start()
    try:
        yield
    finally:
        await background_tasks.stop()


# Paths intentionally reachable without a bearer token. Keep this set
# minimal: every entry is a deliberate decision to expose an endpoint to
# anonymous callers. ``tests/test_route_auth_guard.py`` imports these two
# constants and asserts every other route is behind the global guard, so a
# new unauthenticated endpoint cannot slip in unnoticed.
#
#   /            SPA shell; the JS handles the login redirect
#   /auth/login  issues the first token (chicken-and-egg, cannot require one)
#   /health      liveness / readiness probe
#   /metrics     Prometheus scrape; operational metrics, intentionally anonymous
#
# NOTE: other /auth/* endpoints (/auth/me, /auth/refresh, /auth/users) are
# NOT public. They carry their own current_user / current_active_superuser
# dependency and now also pass through this global guard — there is no blanket
# "/auth" prefix skip, so a future auth-router endpoint is protected by default.
PUBLIC_PATHS = frozenset(
    {
        "/",
        "/auth/login",
        "/health",
        "/metrics",
    }
)
PUBLIC_PATH_PREFIXES = ("/static",)


async def _enforce_auth(request: Request, _user=Depends(current_user_optional)):
    path = request.url.path
    if path in PUBLIC_PATHS:
        return None
    if any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES):
        return None
    if _user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not _user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="user is inactive",
        )
    return None


app = FastAPI(
    title="Cairn",
    description="Fact-graph based collaborative exploration protocol",
    version=__version__,
    lifespan=lifespan,
    dependencies=[Depends(_enforce_auth)],
    # FastAPI serves /docs, /redoc and /openapi.json as plain Starlette
    # routes that bypass the app-level ``_enforce_auth`` dependency, so
    # leaving them on exposes the full API schema to anonymous callers.
    # Gating them behind a bearer token does not work (Swagger UI fetches
    # the schema from the browser without the token), and the hand-written
    # SPA does not consume OpenAPI, so the interactive docs are disabled.
    # Re-enable behind a localhost bind / reverse proxy if needed in dev.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(DomainError)
async def _domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline security response headers to every response.

    These headers are safe over both HTTP and HTTPS; none of them
    depends on TLS being available. Strict-Transport-Security is
    omitted intentionally — it should be injected by a terminating
    reverse proxy (nginx / Traefik / Cloudflare) rather than by the
    backend when HTTPS is in play.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


# Middleware order matters: Starlette runs the *last added* middleware
# first on the way in. RequestIdMiddleware must run before everything
# else so a panic in a downstream handler still carries a trace id.
app.add_middleware(RequestIdMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


def _database_error_payload() -> dict[str, str]:
    return {
        "status": "degraded",
        "database": "postgresql",
        "error": "database_unavailable",
        "request_id": get_trace_id() or "",
    }


def _database_error_response(exc: Exception) -> JSONResponse:
    LOG.exception("database unavailable trace_id=%s", get_trace_id(), exc_info=exc)
    return JSONResponse(
        status_code=503,
        content=_database_error_payload(),
    )


@app.exception_handler(db.DatabaseUnavailable)
async def database_unavailable_handler(_request: Request, exc: db.DatabaseUnavailable) -> JSONResponse:
    return _database_error_response(exc)


@app.exception_handler(SQLAlchemyError)
async def sqlalchemy_error_handler(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
    return _database_error_response(exc)


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@app.get("/health", include_in_schema=False)
def health() -> Response:
    try:
        status_payload = db.postgres_status()
    except Exception as exc:  # noqa: BLE001
        LOG.exception("health database check failed trace_id=%s", get_trace_id(), exc_info=exc)
        body = _database_error_payload()
        return Response(
            content=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
            status_code=503,
            media_type="application/json",
        )
    body = {"status": "ok", "version": __version__, **status_payload}
    return Response(
        content=json.dumps(body, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
    )

app.include_router(auth.router)
app.include_router(settings.router)
app.include_router(task_types.router)
app.include_router(ai_profiles.router)
app.include_router(servers.router)
app.include_router(projects.router)
app.include_router(project_proxy.router)
app.include_router(prompt_groups.router)
app.include_router(hints.router)
app.include_router(attachments.router)
app.include_router(intents.router)
app.include_router(export.router)
app.include_router(files.router)
app.include_router(replay.router)
app.include_router(capabilities.router)
app.include_router(execution_configs.router)
app.include_router(observability_routers.router)
app.include_router(system_config_router.router)


@app.get("/", include_in_schema=False)
def index(request: Request):
    # Force the browser to always revalidate the SPA shell. Without
    # this, every frontend edit shows up only after a hard reload.
    # DEBUG path falls back to a live reassemble so partial edits show
    # up without a server restart.
    html = getattr(request.app.state, "index_html", None)
    if html is None:
        html = assemble_index()
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


app.mount("/static", NoStoreStaticFiles(directory=str(STATIC_DIR)), name="static")
