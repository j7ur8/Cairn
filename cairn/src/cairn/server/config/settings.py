from __future__ import annotations

from cairn.server.config.files import load_dispatch_data, save_dispatch_data
from cairn.server.models_pkg.common import Settings


def get_yaml_settings() -> Settings:
    data = load_dispatch_data()
    server_settings = data.get("server_settings") if isinstance(data.get("server_settings"), dict) else {}
    tasks = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
    return Settings(
        intent_timeout=int(server_settings.get("intent_timeout") or tasks.get("explore", {}).get("conclude_timeout") or 15),
        reason_timeout=int(server_settings.get("reason_timeout") or tasks.get("reason", {}).get("timeout") or 15),
    )


def update_yaml_settings(body: Settings) -> Settings:
    data = load_dispatch_data()
    data["server_settings"] = {
        "intent_timeout": body.intent_timeout,
        "reason_timeout": body.reason_timeout,
    }
    tasks = data.setdefault("tasks", {})
    tasks.setdefault("explore", {})["conclude_timeout"] = body.intent_timeout
    tasks.setdefault("reason", {})["timeout"] = body.reason_timeout
    save_dispatch_data(data)
    return body

