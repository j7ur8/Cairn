"""Regression guard: no endpoint is reachable without authentication.

Cairn runs as a single-user, self-hosted tool where the only account is a
superuser, so there is no per-role authorization to police here. What does
matter is that *every* route sits behind the app-level ``_enforce_auth``
dependency, except a small, deliberate allowlist of public paths.

This test introspects the live FastAPI app (no DB required) and asserts:

  1. The set of API routes that would admit an anonymous caller equals
     exactly ``PUBLIC_PATHS`` (plus the static mount). A new business
     endpoint that forgets its auth wiring, or a new entry sneaked into the
     allowlist, fails here.
  2. FastAPI's interactive docs (/docs, /redoc, /openapi.json) stay
     disabled. These are plain Starlette routes that bypass the global
     guard, so leaving them on would leak the full API schema anonymously.

It imports the allowlist constants from ``app`` rather than re-declaring
them, so the test and the runtime share a single source of truth.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

from cairn.server.app import PUBLIC_PATH_PREFIXES, PUBLIC_PATHS, app


def _dependency_call_names(dependant) -> set[str]:
    names: set[str] = set()
    for sub in dependant.dependencies:
        name = getattr(sub.call, "__name__", None)
        if name:
            names.add(name)
        names |= _dependency_call_names(sub)
    return names


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_PATH_PREFIXES)


def test_every_api_route_is_behind_the_global_guard() -> None:
    """No API route may escape ``_enforce_auth``.

    The guard is registered once at app construction, so it normally lands
    on every route's dependency tree. A route added via a sub-app or a
    router mounted without inheriting the app-level dependency would slip
    past it — that is the regression this catches.
    """
    unguarded: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        names = _dependency_call_names(route.dependant)
        if "_enforce_auth" not in names:
            unguarded.add(f"{sorted(route.methods)} {route.path}")

    assert unguarded == set(), (
        "These API routes are not covered by the global _enforce_auth "
        f"dependency: {sorted(unguarded)}. They can be reached without "
        "authentication. Ensure their router is included on the main app "
        "(which injects _enforce_auth) rather than a bare sub-app."
    )


def test_only_allowlisted_api_routes_admit_anonymous_callers() -> None:
    """Anonymous-reachable API routes must equal the public allowlist.

    ``_enforce_auth`` raises 401 for every path except those on the public
    list, so the set of paths it lets through must be exactly the routes we
    intend to expose. A path quietly added to PUBLIC_PATHS shows up here.
    """
    anonymous = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and _is_public_path(route.path)
    }
    expected = {"/", "/auth/login", "/health", "/metrics"}
    assert anonymous == expected, (
        "The set of anonymous-reachable API routes drifted from the intended "
        f"allowlist. got={sorted(anonymous)} expected={sorted(expected)}. "
        "If a new public endpoint is intentional, update this test and "
        "document why it is safe to expose without a token."
    )


def test_public_allowlist_has_no_stray_entries() -> None:
    """The allowlist itself must not drift; each entry is a known route."""
    api_paths = {route.path for route in app.routes if isinstance(route, APIRoute)}
    # "/" is served by an APIRoute; the others are explicit endpoints.
    expected_public = {"/", "/auth/login", "/health", "/metrics"}
    assert set(PUBLIC_PATHS) == expected_public, (
        "PUBLIC_PATHS changed. If this is intentional, update this test and "
        "document why the new path is safe to expose anonymously. "
        f"got={sorted(PUBLIC_PATHS)} expected={sorted(expected_public)}"
    )
    missing = {p for p in PUBLIC_PATHS if p not in api_paths}
    assert missing == set(), f"PUBLIC_PATHS references non-existent routes: {sorted(missing)}"


def test_interactive_docs_are_disabled() -> None:
    """/docs, /redoc, /openapi.json bypass the global guard — keep them off."""
    doc_paths = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
    present = {
        route.path
        for route in app.routes
        if isinstance(route, Route) and route.path in doc_paths
    }
    assert present == set(), (
        "FastAPI interactive docs are enabled and bypass _enforce_auth, "
        f"exposing the API schema anonymously: {sorted(present)}. Keep "
        "docs_url/redoc_url/openapi_url set to None in cairn.server.app."
    )
    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None


def test_static_mount_is_the_only_public_mount() -> None:
    mounts = {route.path for route in app.routes if isinstance(route, Mount)}
    assert mounts == {"/static"}, (
        f"Unexpected mounts present: {sorted(mounts)}. Static assets are the "
        "only intentionally public mount."
    )
