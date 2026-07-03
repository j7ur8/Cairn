from __future__ import annotations

import sys
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from pydantic import ValidationError

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class ServerResourceConfigTests(unittest.TestCase):
    def test_rejects_remote_support_in_resources_schema(self) -> None:
        from cairn.shared.config import ResourceConfig

        with self.assertRaises(ValidationError):
            ResourceConfig.model_validate({"remote_support": {"enabled": True}})

    def test_certificate_cert_path_is_confined(self) -> None:
        from cairn.shared.config import ServerResourceConfig

        base = {
            "id": "srv1",
            "name": "Server",
            "host": "host",
            "username": "root",
        }
        ServerResourceConfig.model_validate({**base, "cert_path": "team/client.pem"})
        for bad in ("/tmp/key.pem", "../key.pem", "team/../key.pem", "bad\x00key.pem"):
            with self.assertRaises(ValidationError):
                ServerResourceConfig.model_validate({**base, "cert_path": bad})

    def test_server_rejects_legacy_auth_type_and_requires_auth_material(self) -> None:
        from cairn.shared.config import ServerResourceConfig

        base = {
            "id": "srv1",
            "name": "Server",
            "host": "host",
            "username": "root",
        }
        with self.assertRaises(ValidationError):
            ServerResourceConfig.model_validate({**base, "auth_type": "password", "password": "secret"})
        with self.assertRaises(ValidationError):
            ServerResourceConfig.model_validate(base)

    def test_server_write_schema_does_not_accept_client_auth_order(self) -> None:
        from cairn.server.schemas.servers import ServerCreate, ServerUpdate

        with self.assertRaises(ValidationError):
            ServerCreate(
                id="srv1",
                name="Server",
                host="host",
                username="ops",
                password="secret",
                auth_order=["password"],  # type: ignore[call-arg]
            )
        with self.assertRaises(ValidationError):
            ServerUpdate(auth_order=["password"])  # type: ignore[call-arg]

    def test_yaml_servers_redact_secrets_and_record_missing_sshpass_test(self) -> None:
        import yaml

        from cairn.server.config.servers import create_yaml_server, list_yaml_servers, test_yaml_server
        from cairn.server.schemas.servers import ServerCreate
        from helpers import TempYamlConfig

        with TempYamlConfig(resources={"servers": [], "capabilities": {"mcp_servers": [], "skills": []}, "roles": []}) as cfg:
            created = create_yaml_server(
                ServerCreate(
                    id="srv1",
                    name="Build host",
                    host="build.internal",
                    username="ops",
                    password="secret",
                )
            )
            self.assertTrue(created.has_password)
            self.assertFalse(created.has_private_key)
            self.assertEqual(created.auth_order, ["password"])

            listed = list_yaml_servers()
            self.assertEqual(len(listed), 1)
            self.assertNotIn("password", listed[0].model_dump())
            self.assertEqual(listed[0].auth_order, ["password"])

            with mock.patch("cairn.server.config.server_ssh.shutil.which", return_value=None):
                result = test_yaml_server("srv1", command="true", timeout_seconds=1)
                self.assertFalse(result.ok)
                self.assertIn("password auth testing requires sshpass", result.message)

            data = yaml.safe_load(cfg.resources_path.read_text(encoding="utf-8"))
            self.assertFalse(data["servers"][0]["last_test_ok"])
            self.assertIn("password auth testing requires sshpass", data["servers"][0]["last_test_message"])

    def test_password_server_uses_sshpass_password_file(self) -> None:
        from cairn.server.config.servers import create_yaml_server, run_yaml_server_command
        from cairn.server.schemas.servers import ServerCommandRequest, ServerCreate
        from helpers import TempYamlConfig

        captured = {}

        def fake_run(argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            password_path = Path(argv[2])
            captured["password_path"] = password_path
            captured["password_text"] = password_path.read_text(encoding="utf-8")
            mock_completed = mock.Mock()
            mock_completed.returncode = 0
            mock_completed.stdout = ""
            mock_completed.stderr = ""
            return mock_completed

        with TempYamlConfig(resources={"servers": [], "capabilities": {"mcp_servers": [], "skills": []}, "roles": []}):
            create_yaml_server(
                ServerCreate(
                    id="srv1",
                    name="Build host",
                    host="build.internal",
                    username="ops",
                    password="secret",
                )
            )
            with mock.patch("cairn.server.config.server_ssh.shutil.which", return_value="/usr/bin/sshpass"), mock.patch(
                "cairn.server.config.server_ssh.subprocess.run",
                side_effect=fake_run,
            ):
                result = run_yaml_server_command("srv1", ServerCommandRequest(command="true", timeout_seconds=1))

        self.assertTrue(result.ok)
        self.assertEqual(captured["argv"][:3], ["sshpass", "-f", str(captured["password_path"])])
        self.assertNotIn("secret", captured["argv"])
        self.assertEqual(captured["password_text"], "secret\n")
        self.assertFalse(captured["password_path"].exists())

    def test_server_command_tries_auth_order_until_success(self) -> None:
        from cairn.server.config.servers import run_yaml_server_command
        from cairn.server.schemas.servers import ServerCommandRequest
        from helpers import TempYamlConfig

        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            mock_completed = mock.Mock()
            mock_completed.stdout = ""
            mock_completed.stderr = ""
            mock_completed.returncode = 1 if len(calls) < 3 else 0
            return mock_completed

        resources = {
            "servers": [
                {
                    "id": "srv1",
                    "name": "Build host",
                    "host": "build.internal",
                    "username": "ops",
                    "password": "secret",
                    "private_key": "-----BEGIN KEY-----\nkey\n-----END KEY-----",
                    "cert_path": "servers/srv1/client.pem",
                }
            ],
            "capabilities": {"mcp_servers": [], "skills": []},
            "roles": [],
        }
        with TempYamlConfig(resources=resources):
            with mock.patch("cairn.server.config.server_ssh.shutil.which", return_value="/usr/bin/sshpass"), mock.patch(
                "cairn.server.config.server_ssh.subprocess.run",
                side_effect=fake_run,
            ):
                result = run_yaml_server_command("srv1", ServerCommandRequest(command="true", timeout_seconds=1))

        self.assertTrue(result.ok)
        self.assertEqual(result.message, "ok via password")
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[0][0], "ssh")
        self.assertEqual(calls[1][0], "ssh")
        self.assertIn("servers/srv1/client.pem", " ".join(calls[1]))
        self.assertEqual(calls[2][:2], ["sshpass", "-f"])

    def test_servers_multipart_create_and_update_certificate_uploads(self) -> None:
        import yaml
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from cairn.server.routers import servers as servers_router
        from cairn.server.security.deps import current_active_superuser
        from helpers import TempYamlConfig

        app = FastAPI()
        app.dependency_overrides[current_active_superuser] = lambda: object()
        app.include_router(servers_router.router)

        with TempYamlConfig(resources={"servers": [], "capabilities": {"mcp_servers": [], "skills": []}, "roles": []}) as cfg:
            with TestClient(app) as client:
                create = client.post(
                    "/servers/add",
                    data={
                        "payload": (
                            '{"id":"srv1","name":"Server","host":"host","username":"ops","password":"secret"}'
                        )
                    },
                    files={"certificate": ("client.pem", b"cert-one", "application/x-pem-file")},
                )
                self.assertEqual(create.status_code, 201, create.text)
                created = create.json()
                self.assertEqual(created["auth_order"], ["certificate", "password"])
                first_rel = created["cert_path"]
                first_path = cfg.root / "capabilities" / "ssh_certs" / first_rel
                self.assertTrue(first_path.exists())
                self.assertEqual(first_path.read_bytes(), b"cert-one")

                update = client.put(
                    "/servers/srv1",
                    data={"payload": '{"name":"Server 2"}'},
                    files={"certificate": ("client two.pem", b"cert-two", "application/x-pem-file")},
                )
                self.assertEqual(update.status_code, 200, update.text)
                updated = update.json()
                self.assertEqual(updated["name"], "Server 2")
                second_rel = updated["cert_path"]
                second_path = cfg.root / "capabilities" / "ssh_certs" / second_rel
                self.assertNotEqual(second_rel, first_rel)
                self.assertFalse(first_path.exists())
                self.assertTrue(second_path.exists())
                self.assertEqual(second_path.read_bytes(), b"cert-two")

                delete = client.delete("/servers/srv1")
                self.assertEqual(delete.status_code, 204, delete.text)
                self.assertFalse(second_path.exists())
                self.assertFalse(second_path.parent.exists())

            data = yaml.safe_load(cfg.resources_path.read_text(encoding="utf-8"))
            self.assertEqual(data["servers"], [])


class ProjectProxySchemaTests(unittest.TestCase):
    def test_endpoint_defaults_and_validation(self) -> None:
        from cairn.server.schemas.project_proxy import ProjectProxyEndpointCreate

        endpoint = ProjectProxyEndpointCreate(name="  corp  ", host=" proxy.internal ", port=1080)
        self.assertEqual(endpoint.name, "corp")
        self.assertEqual(endpoint.host, "proxy.internal")
        self.assertEqual(endpoint.protocol, "socks5h")
        self.assertIsNone(endpoint.prerequisite_proxy_id)
        self.assertEqual(endpoint.reachable_from, "worker")
        self.assertEqual(endpoint.usage_mode, "tool_native_proxy")

        with self.assertRaises(ValidationError):
            ProjectProxyEndpointCreate(name="bad", host="h", port=0)
        with self.assertRaises(ValidationError):
            ProjectProxyEndpointCreate(name="bad", host="h", port=1080, protocol="ftp")  # type: ignore[arg-type]

    def test_create_project_rejects_legacy_proxy_fields(self) -> None:
        from cairn.server.schemas import CreateProjectRequest
        from helpers import test_task_timeouts

        for field in ("proxy_id", "tool_proxy_id"):
            with self.assertRaises(ValidationError):
                CreateProjectRequest(
                    title="t",
                    origin="o",
                    goal="g",
                    task_timeouts=test_task_timeouts(),
                    **{field: "proxy_001"},
                )


class ProjectProxyRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        from helpers import reset_postgres_db

        self.db = reset_postgres_db()

    def tearDown(self) -> None:
        self.db.reset_for_tests()

    def _seed_project(self, conn, project_id: str = "proj_1") -> None:
        from cairn.server.repositories.projects import ProjectRepository

        ProjectRepository(conn).insert_project(
            project_id=project_id,
            title="Project",
            status="active",
            created_at="2026-06-06T00:00:00Z",
            graph_revision=1,
            timeline_revision=1,
            llm_hidden_event_kinds='["usage"]',
        )

    def test_crud_chain_cycle_and_audit_fields(self) -> None:
        from cairn.server.domain.errors import BadRequestError
        from cairn.server.repositories import sql
        from cairn.server.repositories.project_proxy import ProjectProxyRepository
        from cairn.server.schemas.project_proxy import ProjectProxyEndpointCreate, ProjectProxyEndpointUpdate

        with self.db.session_scope() as conn:
            self._seed_project(conn)
            repo = ProjectProxyRepository(conn)
            entry = repo.create(
                "proj_1",
                ProjectProxyEndpointCreate(
                    id="px_entry",
                    name="Entry",
                    host="entry.internal",
                    port=1080,
                    password="entry-secret",
                    reachable_from="worker",
                    usage_mode="tool_native_proxy",
                ),
            )
            target = repo.create(
                "proj_1",
                ProjectProxyEndpointCreate(
                    id="px_target",
                    name="Target",
                    host="target.internal",
                    port=8080,
                    protocol="http",
                    prerequisite_proxy_id=entry.id,
                    reachable_from="through_prerequisite",
                    usage_mode="proxychains",
                ),
            )

            chain = repo.resolve_chain("proj_1", target.id)
            self.assertTrue(chain.ok)
            self.assertEqual([item.id for item in chain.chain], ["px_entry", "px_target"])

            repo.update("proj_1", entry.id, ProjectProxyEndpointUpdate(description="keep password"))
            row = sql.fetchone(
                conn,
                "SELECT password, description FROM project_proxy_endpoints WHERE project_id = :project_id AND id = :id",
                {"project_id": "proj_1", "id": entry.id},
            )
            self.assertEqual(row["password"], "entry-secret")
            self.assertEqual(row["description"], "keep password")

            with self.assertRaises(BadRequestError):
                repo.update("proj_1", entry.id, ProjectProxyEndpointUpdate(prerequisite_proxy_id=target.id))
            self.assertIsNone(repo.get("proj_1", entry.id).prerequisite_proxy_id)

            tested = repo.record_test("proj_1", target.id, ok=False, message="connect failed")
            self.assertEqual(tested.health_status, "error")
            self.assertFalse(tested.last_test_ok)

            used = repo.record_usage("proj_1", target.id, ok=True, message="curl succeeded")
            self.assertTrue(used.last_usage_ok)
            self.assertEqual(used.last_usage_message, "curl succeeded")

            repo.delete("proj_1", entry.id)
            remaining = repo.get("proj_1", target.id)
            self.assertIsNone(remaining.prerequisite_proxy_id)


class ProxyRedactionTests(unittest.TestCase):
    def _redact(self, source_module: str, line: str) -> str:
        import importlib

        mod = importlib.import_module(source_module)
        return mod.redact_content(line, [])[0]

    def test_proxy_urls_are_redacted_in_logs(self) -> None:
        samples = [
            ("cairn.dispatcher.observability.redaction", "HTTP_PROXY=http://alice:hunter2@proxy.corp:3128"),
            ("cairn.server.observability.redaction", "HTTPS_PROXY=https://u:p@h:443"),
            ("cairn.dispatcher.observability.redaction", "SOCKS5_PROXY=socks5://u:p@1.2.3.4:1080"),
            ("cairn.server.observability.redaction", "ALL_PROXY=socks5://u:p@1.2.3.4:1080"),
        ]
        for module, line in samples:
            with self.subTest(line=line):
                out = self._redact(module, line)
                self.assertNotIn("hunter2", out)
                self.assertNotIn("u:p", out)


if __name__ == "__main__":
    unittest.main()
