"""Tests for the project-level proxy pool (server CRUD, dispatcher resolver,
and observability redaction).

Covers:
- ``ProxyConfig`` / ``ProxyCreate`` schema validation
- ``proxy_config_to_env`` for socks5 / http / https with and without auth
- ``BUILTIN_PATTERNS`` redaction of HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / SOCKS5_PROXY
- ``DispatcherLoop._resolve_project_proxy`` populates the cache and tolerates
  ``LookupError`` / ``RequestException``
- ``DispatcherLoop._resolve_proxy_env`` returns ``None`` for the
  startup-healthcheck project id
- ``ContainerManager`` accepts the ``proxy_resolver`` callable and merges its
  result into the worker container ``environment=``
- Server: ``POST /proxies`` writes a row, ``DELETE /proxies/{id}`` cascades
  to ``projects.proxy_id`` (``ON DELETE SET NULL``)
"""
from __future__ import annotations

import sys
import unittest
from cairn.dispatcher.scheduler.project_cache import ProjectCaches
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_proxy(**overrides: Any):
    """Factory for a fully-populated :class:`ProxyConfig`."""
    from cairn.server.models_pkg.proxies import ProxyConfig

    ts = _ts()
    base = dict(
        id="proxy_abc",
        name="corp-socks",
        type="socks5",
        host="10.0.0.1",
        port=1080,
        has_auth=True,
        username="alice",
        password="hunter2",
        created_at=ts,
        updated_at=ts,
    )
    base.update(overrides)
    return ProxyConfig(**base)


class ProxyConfigSchemaTests(unittest.TestCase):
    """``ProxyConfig`` / ``ProxyCreate`` / ``ProxyUpdate`` schema basics."""

    def test_create_requires_name(self) -> None:
        from cairn.server.models_pkg.proxies import ProxyCreate

        with self.assertRaises(Exception):
            ProxyCreate(type="socks5", host="h", port=1080)

    def test_create_port_must_be_in_range(self) -> None:
        from cairn.server.models_pkg.proxies import ProxyCreate

        with self.assertRaises(Exception):
            ProxyCreate(name="x", type="socks5", host="h", port=0)
        with self.assertRaises(Exception):
            ProxyCreate(name="x", type="socks5", host="h", port=70000)

    def test_create_type_must_be_known(self) -> None:
        from cairn.server.models_pkg.proxies import ProxyCreate

        with self.assertRaises(Exception):
            ProxyCreate(name="x", type="ftp", host="h", port=21)

    def test_summary_strips_credentials(self) -> None:
        from cairn.server.models_pkg.proxies import ProxySummary

        ts = _ts()
        s = ProxySummary(
            id="p1", name="n", type="socks5", host="h", port=1,
            has_auth=True, created_at=ts, updated_at=ts,
        )
        # Summary must not expose username/password fields at all
        with self.assertRaises(ValueError):
            s.username = "x"  # type: ignore[attr-defined]
        self.assertTrue(s.has_auth)


class ProxyConfigToEnvTests(unittest.TestCase):
    """``proxy_config_to_env`` translates a :class:`ProxyConfig` into env vars."""

    def setUp(self) -> None:
        from cairn.dispatcher.scheduler.proxy_env import proxy_config_to_env
        self.proxy_config_to_env = proxy_config_to_env

    def test_socks5_with_auth(self) -> None:
        env = self.proxy_config_to_env(_make_proxy(type="socks5", host="1.2.3.4", port=1080, username="u", password="p"))
        self.assertEqual(env["ALL_PROXY"], "socks5://u:p@1.2.3.4:1080")
        self.assertNotIn("HTTP_PROXY", env)
        self.assertNotIn("HTTPS_PROXY", env)
        self.assertIn("cairn-server", env["NO_PROXY"])

    def test_socks5_without_auth(self) -> None:
        env = self.proxy_config_to_env(_make_proxy(type="socks5", host="1.2.3.4", port=1080, username=None, password=None, has_auth=False))
        self.assertEqual(env["ALL_PROXY"], "socks5://1.2.3.4:1080")
        self.assertNotIn("user@", env["ALL_PROXY"])

    def test_http_with_auth_uses_user_pass(self) -> None:
        env = self.proxy_config_to_env(_make_proxy(type="http", host="h", port=80, username="u", password="p"))
        self.assertEqual(env["HTTP_PROXY"], "http://u:p@h:80")
        self.assertEqual(env["HTTPS_PROXY"], "http://u:p@h:80")

    def test_https_proxy_env_uses_http_scheme(self) -> None:
        env = self.proxy_config_to_env(_make_proxy(type="https", host="h", port=443, username=None, password=None, has_auth=False))
        self.assertEqual(env["HTTP_PROXY"], "http://h:443")
        self.assertEqual(env["HTTPS_PROXY"], "http://h:443")

    def test_username_only_keeps_at_sign(self) -> None:
        env = self.proxy_config_to_env(_make_proxy(type="http", host="h", port=80, username="u", password=None, has_auth=True))
        self.assertEqual(env["HTTP_PROXY"], "http://u@h:80")


class ProxyRedactionTests(unittest.TestCase):
    """BUILTIN_PATTERNS cover HTTP_PROXY / HTTPS_PROXY / ALL_PROXY / SOCKS5_PROXY."""

    def _redact(self, source_module: str, line: str) -> str:
        import importlib
        mod = importlib.import_module(source_module)
        return mod.redact_content(line, [])[0]

    def test_http_proxy_redacted(self) -> None:
        line = "got env HTTP_PROXY=http://alice:hunter2@proxy.corp:3128"
        out = self._redact("cairn.dispatcher.observability.redaction", line)
        self.assertNotIn("hunter2", out)
        self.assertIn("HTTP_PROXY=[REDACTED]", out)

    def test_https_proxy_redacted(self) -> None:
        line = "env HTTPS_PROXY=https://u:p@h:443"
        out = self._redact("cairn.server.observability.redaction", line)
        self.assertNotIn("u:p", out)
        self.assertIn("HTTPS_PROXY=[REDACTED]", out)

    def test_socks5_proxy_redacted(self) -> None:
        line = "SOCKS5_PROXY=socks5://u:p@1.2.3.4:1080"
        out = self._redact("cairn.dispatcher.observability.redaction", line)
        self.assertNotIn("u:p", out)

    def test_all_proxy_redacted(self) -> None:
        line = "ALL_PROXY=socks5://u:p@1.2.3.4:1080"
        out = self._redact("cairn.server.observability.redaction", line)
        self.assertNotIn("u:p", out)


class ResolverCacheTests(unittest.TestCase):
    """``DispatcherLoop._resolve_project_proxy`` populates cache and tolerates errors."""

    def _make_project(self, project_id: str = "p1", proxy=None):
        from cairn.server.models_pkg.projects import ProjectDetail, ProjectMeta

        project = ProjectMeta(
            id=project_id, title="t", origin="o", goal="g",
            status="active", created_at=_ts(), updated_at=_ts(),
        )
        return ProjectDetail(project=project, facts=[], intents=[], hints=[], proxy=proxy)

    def _make_proxy_summary(self, proxy_id: str = "px1"):
        from cairn.server.models_pkg.proxies import ProxySummary

        ts = _ts()
        return ProxySummary(
            id=proxy_id, name="n", type="socks5", host="h", port=1,
            has_auth=False, created_at=ts, updated_at=ts,
        )

    def test_resolve_no_proxy_populates_none(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = MagicMock(spec=DispatcherLoop)
        loop.project_caches = ProjectCaches()
        loop._ai_overlay_cache = MagicMock()
        project = self._make_project()
        # Bind the real method onto the spec'd instance
        DispatcherLoop._resolve_project_proxy(loop, project)
        self.assertIn("p1", loop.project_caches.proxy)
        self.assertIsNone(loop.project_caches.proxy["p1"])

    def test_resolve_fetches_proxy_when_proxy_summary_present(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = MagicMock(spec=DispatcherLoop)
        loop.project_caches = ProjectCaches()
        loop._ai_overlay_cache = MagicMock()
        loop.client = MagicMock()
        loop.client.get_proxy.return_value = _make_proxy()
        project = self._make_project(proxy=self._make_proxy_summary("px1"))
        DispatcherLoop._resolve_project_proxy(loop, project)
        self.assertEqual(loop.project_caches.proxy["p1"].id, "proxy_abc")
        loop.client.get_proxy.assert_called_once_with("px1")

    def test_resolve_lookup_error_falls_back_to_none(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = MagicMock(spec=DispatcherLoop)
        loop.project_caches = ProjectCaches()
        loop._ai_overlay_cache = MagicMock()
        loop.client = MagicMock()
        loop.client.get_proxy.side_effect = LookupError("not found")
        project = self._make_project(proxy=self._make_proxy_summary("px_missing"))
        DispatcherLoop._resolve_project_proxy(loop, project)
        self.assertIsNone(loop.project_caches.proxy["p1"])

    def test_resolve_request_exception_falls_back_to_none(self) -> None:
        import requests
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = MagicMock(spec=DispatcherLoop)
        loop.project_caches = ProjectCaches()
        loop._ai_overlay_cache = MagicMock()
        loop.client = MagicMock()
        loop.client.get_proxy.side_effect = requests.RequestException("boom")
        project = self._make_project(proxy=self._make_proxy_summary("px_err"))
        DispatcherLoop._resolve_project_proxy(loop, project)
        self.assertIsNone(loop.project_caches.proxy["p1"])

    def test_resolve_refetches_on_every_call(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = MagicMock(spec=DispatcherLoop)
        loop.project_caches = ProjectCaches()
        loop._ai_overlay_cache = MagicMock()
        loop.client = MagicMock()
        loop.client.get_proxy.return_value = _make_proxy()
        project = self._make_project(proxy=self._make_proxy_summary("px1"))
        # First call fetches and caches
        DispatcherLoop._resolve_project_proxy(loop, project)
        # Second call also fetches (always-refresh semantics) — cache is
        # used by _resolve_proxy_env at container-launch time, not by
        # _resolve_project_proxy itself.
        DispatcherLoop._resolve_project_proxy(loop, project)
        # Must be called every time (always-refresh semantics)
        self.assertEqual(len(loop.client.get_proxy.call_args_list), 2)

    def test_resolve_proxy_env_returns_none_for_startup_healthcheck(self) -> None:
        from cairn.dispatcher.runtime.containers import ContainerManager
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = MagicMock(spec=DispatcherLoop)
        loop.project_caches = ProjectCaches()
        loop.project_caches.proxy = {"p1": _make_proxy()}
        # Real method bound to the spec
        result = DispatcherLoop._resolve_proxy_env(loop, ContainerManager._STARTUP_PROJECT_ID)
        self.assertIsNone(result)

    def test_resolve_proxy_env_returns_env_for_cached_project(self) -> None:
        from cairn.dispatcher.scheduler.loop import DispatcherLoop

        loop = MagicMock(spec=DispatcherLoop)
        loop.project_caches = ProjectCaches()
        loop.project_caches.proxy = {"p1": _make_proxy()}
        result = DispatcherLoop._resolve_proxy_env(loop, "p1")
        self.assertIsNotNone(result)
        self.assertIn("ALL_PROXY", result)


class ContainerManagerProxyWiringTests(unittest.TestCase):
    """``ContainerManager`` accepts the ``proxy_resolver`` callable and merges."""

    def test_proxy_resolver_none_returns_empty_env(self) -> None:
        from cairn.shared.dispatch_config import ContainerConfig
        from cairn.dispatcher.runtime.containers import ContainerManager

        cfg = ContainerConfig(image="img", network_mode="net", completed_action="stop")
        with patch("cairn.dispatcher.runtime.containers.docker.from_env", return_value=MagicMock()):
            mgr = ContainerManager(cfg, proxy_resolver=None)
        self.assertEqual(mgr._proxy_environment("p1"), {})

    def test_proxy_resolver_returning_dict_is_merged(self) -> None:
        from cairn.shared.dispatch_config import ContainerConfig
        from cairn.dispatcher.runtime.containers import ContainerManager

        cfg = ContainerConfig(image="img", network_mode="net", completed_action="stop")
        with patch("cairn.dispatcher.runtime.containers.docker.from_env", return_value=MagicMock()):
            mgr = ContainerManager(cfg, proxy_resolver=lambda pid: {"HTTP_PROXY": "http://h:80"})
        self.assertEqual(mgr._proxy_environment("p1"), {"HTTP_PROXY": "http://h:80"})

    def test_proxy_resolver_returning_none_yields_empty(self) -> None:
        from cairn.shared.dispatch_config import ContainerConfig
        from cairn.dispatcher.runtime.containers import ContainerManager

        cfg = ContainerConfig(image="img", network_mode="net", completed_action="stop")
        with patch("cairn.dispatcher.runtime.containers.docker.from_env", return_value=MagicMock()):
            mgr = ContainerManager(cfg, proxy_resolver=lambda pid: None)
        self.assertEqual(mgr._proxy_environment("p1"), {})


class ProxyDatabaseTests(unittest.TestCase):
    """Server proxy CRUD persists in dispatch.yaml."""

    def setUp(self) -> None:
        from helpers import TempYamlConfig, reset_postgres_db

        self.yaml = TempYamlConfig()
        self.yaml.__enter__()
        self.db = reset_postgres_db()
        from cairn.server.routers import proxies as proxies_router
        self.proxies_router = proxies_router

    def tearDown(self) -> None:
        self.db.reset_for_tests()
        self.yaml.__exit__(None, None, None)

    def test_create_and_get_proxy(self) -> None:
        from cairn.server.models_pkg.proxies import ProxyCreate

        body = ProxyCreate(name="n1", type="socks5", host="h1", port=1080, username="u", password="p")
        created = self.proxies_router.create_proxy(body)
        self.assertTrue(created.id.startswith("proxy_"))
        fetched = self.proxies_router.get_proxy(created.id)
        self.assertEqual(fetched.username, "u")
        self.assertEqual(fetched.password, "p")

    def test_list_proxies_returns_summaries_without_credentials(self) -> None:
        from cairn.server.models_pkg.proxies import ProxyCreate

        body = ProxyCreate(name="n1", type="socks5", host="h1", port=1080, username="u", password="p")
        self.proxies_router.create_proxy(body)
        summaries = self.proxies_router.list_proxies()
        self.assertEqual(len(summaries), 1)
        self.assertTrue(summaries[0].has_auth)
        # summary model does not expose credentials
        self.assertNotIn("password", summaries[0].model_dump())

    def test_delete_proxy_removes_yaml_entry(self) -> None:
        from cairn.server.models_pkg.proxies import ProxyCreate

        body = ProxyCreate(name="n1", type="socks5", host="h1", port=1080)
        created = self.proxies_router.create_proxy(body)
        self.proxies_router.delete_proxy(created.id)
        self.assertEqual(self.proxies_router.list_proxies(), [])

    def test_create_project_with_invalid_proxy_id_returns_400(self) -> None:
        from fastapi import HTTPException
        from cairn.server.routers import projects as projects_router
        from cairn.server.models_pkg.ai_profiles import (
            AiProfileCreate,
            AiProfileSelection,
            TaskAiProfileSelections,
        )
        from cairn.server.models_pkg.intents import CreateProjectRequest
        from cairn.server.routers.ai_profiles import create_ai_profile

        profile = create_ai_profile(AiProfileCreate(
            name="p",
            worker_type="codex",
            model="m",
            api_key_env="OPENAI_API_KEY",
            sk="test-key",
        ))
        selection = AiProfileSelection(
            primary_profile_id=profile.id,
            primary_model="m",
            primary_reasoning_type="medium",
        )

        body = CreateProjectRequest(
            title="t",
            origin="o",
            goal="g",
            proxy_id="proxy_does_not_exist",
            ai_profiles=TaskAiProfileSelections(
                bootstrap=selection,
                explore=selection,
                reason=selection,
            ),
        )
        with self.assertRaises(HTTPException) as cm:
            projects_router.create_project(body)
        self.assertEqual(cm.exception.status_code, 400)


class ProjectDetailProxySummaryTests(unittest.TestCase):
    """``ProjectDetail.proxy`` is ``ProxySummary | None`` (no creds leak)."""

    def test_proxy_field_default_none(self) -> None:
        from cairn.server.models_pkg.projects import ProjectDetail, ProjectMeta

        project = ProjectMeta(
            id="p1", title="t", origin="o", goal="g", status="active",
            created_at=_ts(), updated_at=_ts(),
        )
        detail = ProjectDetail(project=project, facts=[], intents=[], hints=[])
        self.assertIsNone(detail.proxy)


if __name__ == "__main__":
    unittest.main()
