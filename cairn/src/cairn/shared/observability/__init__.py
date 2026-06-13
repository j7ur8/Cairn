"""Cross-cutting observability for the Cairn server and dispatcher.

Exposes:
  * :func:`configure_logging` — one-call setup that wires a JSON or
    human formatter and the request-id filter.
  * :mod:`trace` — context-var based trace-id propagation.
  * :mod:`metrics` — Prometheus collectors shared by server and
    dispatcher.
"""
