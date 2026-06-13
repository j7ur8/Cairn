import json
from pathlib import Path

import click
import uvicorn

from cairn.dispatcher.logging import configure_logging
from cairn.dispatcher.scheduler.loop import DispatcherLoop
from cairn.server import db
from cairn.shared.config import ConfigError


@click.group()
def main():
    """Cairn - Fact-graph based collaborative exploration protocol."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host")
@click.option("--port", default=8000, show_default=True, help="Bind port")
@click.option("--log-level", default="info", show_default=True, help="Uvicorn log level")
@click.option("--access-log/--no-access-log", default=True, show_default=True, help="Enable Uvicorn access log")
def serve(host: str, port: int, log_level: str, access_log: bool):
    """Start the Cairn API server."""
    from cairn.server.app import app

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level=log_level.lower(),
        access_log=access_log,
    )


@main.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Dispatcher config path",
)
@click.option("--once", is_flag=True, help="Run one scheduling iteration and exit")
@click.option(
    "--startup-healthcheck-only",
    is_flag=True,
    help="Run startup worker healthchecks and exit",
)
@click.option("--log-level", default="INFO", show_default=True, help="Log level")
def dispatch(config_path: Path, once: bool, startup_healthcheck_only: bool, log_level: str):
    """Run the Cairn dispatcher."""
    configure_logging(log_level, bare=startup_healthcheck_only)
    try:
        loop = DispatcherLoop(config_path)
        if startup_healthcheck_only:
            loop.run_startup_healthchecks_only()
            return
        loop.run(once=once)
    except ConfigError as exc:
        # Configuration problems are operator errors, not bugs: emit a single
        # clear fatal line and exit non-zero instead of a bare traceback that
        # would otherwise crash-loop under the container restart policy.
        raise click.ClickException(f"configuration error: {exc}") from exc
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc


@main.group("db")
def db_commands():
    """PostgreSQL database commands."""


@db_commands.command("status")
def db_status():
    """Print PostgreSQL status."""
    db.configure()
    result = {
        "status": db.postgres_status(),
    }
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))


@db_commands.command("migrate")
def db_migrate():
    """Run Alembic migrations to head."""
    db.configure(run_migrations=False)
    db.upgrade_head()
    db.seed_defaults()
    click.echo(json.dumps(db.postgres_status(), ensure_ascii=False, indent=2))


@db_commands.command("reset")
@click.option("--yes", is_flag=True, help="Confirm destructive schema reset")
def db_reset(yes: bool):
    """Drop and recreate the PostgreSQL schema. Destructive."""
    if not yes:
        raise click.ClickException("Refusing to reset without --yes")
    db.configure(run_migrations=False)
    db.drop_all_for_tests()
    db.upgrade_head()
    db.seed_defaults()
    click.echo(json.dumps(db.postgres_status(), ensure_ascii=False, indent=2))
