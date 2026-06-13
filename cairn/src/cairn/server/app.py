import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.base import BaseHTTPMiddleware

from cairn import __version__
from cairn.observability.logging import configure_logging
from cairn.observability.metrics import (
    HTTP_LATENCY,
    HTTP_REQUESTS,
    render_metrics,
)
from cairn.observability.trace import (
    get_trace_id,
    new_trace_id,
    set_trace_id,
)
from cairn.server import db
from cairn.server.domain.errors import DomainError
from cairn.server.observability import routers as observability_routers
from cairn.server.observability.retention import retention_loop
from cairn.server.repositories.leases import LeaseRepository
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
    proxies,
    replay,
    settings,
    task_types,
)
from cairn.server.runtime_config import system_config
from cairn.server.security.deps import current_user_optional
from cairn.server.security.users import bootstrap_superuser_if_configured

STATIC_DIR = Path(__file__).parent / "static"


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
    :data:`cairn.observability.trace.trace_id_var`, so a single
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
            from cairn.observability.trace import reset_trace_id
            reset_trace_id(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime = system_config()
    configure_logging(
        level=runtime.server.log_level,
        fmt=runtime.server.log_format,
        component="cairn.server",
    )
    db.configure()
    try:
        bootstrap_superuser_if_configured()
    except Exception:  # noqa: BLE001 - never let bootstrap break startup
        import logging
        logging.getLogger(__name__).exception("superuser bootstrap failed")
    # Observability retention loop. Started here (lifespan) rather
    # than from the observability router so the loop dies with the
    # FastAPI process instead of leaking past shutdown. The CLI
    # dispatch path does not run lifespan, so retention stays a
    # manual operation there.
    retention_stop = asyncio.Event()
    retention_task: asyncio.Task | None = None
    if runtime.server.retention_loop_enabled:
        retention_task = asyncio.create_task(
            retention_loop(
                retention_stop,
                interval_seconds=runtime.server.retention_interval_seconds,
            ),
            name="cairn-retention",
        )
    lease_cleanup_stop = asyncio.Event()
    lease_cleanup_task = asyncio.create_task(
        lease_cleanup_loop(lease_cleanup_stop),
        name="cairn-lease-cleanup",
    )
    try:
        yield
    finally:
        lease_cleanup_stop.set()
        try:
            await lease_cleanup_task
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception("lease cleanup task crashed")
        if retention_task is not None:
            retention_stop.set()
            try:
                await retention_task
            except Exception:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).exception("retention task crashed")


async def lease_cleanup_loop(stop: asyncio.Event, *, interval_seconds: float = 2.0) -> None:
    import logging

    log = logging.getLogger(__name__)
    while not stop.is_set():
        try:
            with db.session_scope() as conn:
                leases = LeaseRepository(conn)
                leases.expire_workers()
                leases.expire_reason_leases()
        except Exception as exc:  # noqa: BLE001
            log.warning("lease cleanup failed error=%s", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


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


# Middleware order matters: Starlette runs the *last added* middleware
# first on the way in. RequestIdMiddleware must run before everything
# else so a panic in a downstream handler still carries a trace id.
app.add_middleware(RequestIdMiddleware)


def _database_error_response(exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "status": "degraded",
            "database": "postgresql",
            "database_error": str(exc),
        },
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
        body = {
            "status": "degraded",
            "database": "postgresql",
            "database_error": str(exc),
        }
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
app.include_router(proxies.router)
app.include_router(projects.router)
app.include_router(hints.router)
app.include_router(attachments.router)
app.include_router(intents.router)
app.include_router(export.router)
app.include_router(files.router)
app.include_router(replay.router)
app.include_router(capabilities.router)
app.include_router(execution_configs.router)
app.include_router(observability_routers.router)


@app.get("/", include_in_schema=False)
def index():
    # Force the browser to always revalidate the SPA shell. Without
    # this, every frontend edit shows up only after a hard reload.
    response = FileResponse(STATIC_DIR / "index.html")
    response.headers["Cache-Control"] = "no-store"
    return response


app.mount("/static", NoStoreStaticFiles(directory=str(STATIC_DIR)), name="static")
