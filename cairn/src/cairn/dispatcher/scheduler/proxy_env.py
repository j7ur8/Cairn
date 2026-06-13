from __future__ import annotations

from cairn.shared.contracts import ProxyConfig


def proxy_config_to_env(cfg: ProxyConfig) -> dict[str, str]:
    """Translate a proxy config into worker container environment variables."""
    userpass = ""
    if cfg.username and cfg.password:
        userpass = f"{cfg.username}:{cfg.password}@"
    elif cfg.username:
        userpass = f"{cfg.username}@"
    no_proxy = "localhost,127.0.0.1,cairn-server,cairn"
    if cfg.type == "socks5":
        return {
            "ALL_PROXY": f"socks5://{userpass}{cfg.host}:{cfg.port}",
            "NO_PROXY": no_proxy,
        }
    return {
        "HTTP_PROXY": f"http://{userpass}{cfg.host}:{cfg.port}",
        "HTTPS_PROXY": f"http://{userpass}{cfg.host}:{cfg.port}",
        "NO_PROXY": no_proxy,
    }
