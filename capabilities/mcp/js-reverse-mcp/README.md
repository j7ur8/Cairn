# js-reverse-mcp Cloak sidecar

Cairn ships `js-reverse-mcp@3.0.9` through a project-scoped CloakBrowser sidecar.
Workers run `/usr/local/bin/js-reverse-mcp-cairn`, which leases a slot from the
project sidecar and then execs `js-reverse-mcp --browserUrl <slot-cdp-url>`.

The sidecar keeps two headed CloakBrowser slots by default, exposes CDP only on
the Cairn Docker network, and publishes noVNC on a random loopback host port for
manual inspection from the Project UI.
