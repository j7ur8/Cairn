import json
from pathlib import Path

import click
import uvicorn

from cairn.dispatcher.logging import configure_logging
from cairn.dispatcher.scheduler.loop import DispatcherLoop
from cairn.server import db
from cairn.server.observability import db as observability_db


@click.group()
def main():
    """Cairn - Fact-graph based collaborative exploration protocol."""


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host")
@click.option("--port", default=8000, show_default=True, help="Bind port")
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(db.DEFAULT_DB),
    show_default=True,
    help="SQLite database path",
)
@click.option(
    "--observability-db-path",
    type=click.Path(),
    default=str(observability_db.DEFAULT_OBSERVABILITY_DB),
    show_default=True,
    help="LLM execution observability SQLite database path",
)
@click.option("--log-level", default="info", show_default=True, help="Uvicorn log level")
@click.option("--access-log/--no-access-log", default=True, show_default=True, help="Enable Uvicorn access log")
def serve(host: str, port: int, db_path: str, observability_db_path: str, log_level: str, access_log: bool):
    """Start the Cairn API server."""
    db.configure(Path(db_path))
    observability_db.configure(Path(observability_db_path))
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
    loop = DispatcherLoop(config_path)
    try:
        if startup_healthcheck_only:
            loop.run_startup_healthchecks_only()
            return
        loop.run(once=once)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc


@main.group("db")
def db_commands():
    """SQLite maintenance commands."""


@db_commands.command("status")
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(db.DEFAULT_DB),
    show_default=True,
    help="SQLite database path",
)
@click.option(
    "--observability-db-path",
    type=click.Path(),
    default=str(observability_db.DEFAULT_OBSERVABILITY_DB),
    show_default=True,
    help="LLM execution observability SQLite database path",
)
def db_status(db_path: str, observability_db_path: str):
    """Print SQLite status for the main and observability databases."""
    db.configure(Path(db_path))
    observability_db.configure(Path(observability_db_path))
    click.echo(
        json.dumps(
            {
                "main": db.sqlite_status(),
                "observability": observability_db.sqlite_status(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@db_commands.command("integrity-check")
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(db.DEFAULT_DB),
    show_default=True,
    help="SQLite database path",
)
@click.option(
    "--observability-db-path",
    type=click.Path(),
    default=str(observability_db.DEFAULT_OBSERVABILITY_DB),
    show_default=True,
    help="LLM execution observability SQLite database path",
)
def db_integrity_check(db_path: str, observability_db_path: str):
    """Run PRAGMA integrity_check on both SQLite databases."""
    db.configure(Path(db_path))
    observability_db.configure(Path(observability_db_path))
    result = {
        "main": db.integrity_check(),
        "observability": observability_db.integrity_check(),
    }
    click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    if result["main"] != ["ok"] or result["observability"] != ["ok"]:
        raise click.ClickException("SQLite integrity check failed")


@db_commands.command("backup")
@click.argument("destination", type=click.Path(path_type=Path))
@click.option(
    "--db-path",
    type=click.Path(),
    default=str(db.DEFAULT_DB),
    show_default=True,
    help="SQLite database path",
)
@click.option(
    "--observability-db-path",
    type=click.Path(),
    default=str(observability_db.DEFAULT_OBSERVABILITY_DB),
    show_default=True,
    help="LLM execution observability SQLite database path",
)
def db_backup(destination: Path, db_path: str, observability_db_path: str):
    """Create online backups for both SQLite databases."""
    db.configure(Path(db_path))
    observability_db.configure(Path(observability_db_path))
    if destination.suffix:
        main_destination = destination
        obs_destination = destination.with_name(
            f"{destination.stem}-observability{destination.suffix}"
        )
    else:
        destination.mkdir(parents=True, exist_ok=True)
        main_destination = destination
        obs_destination = destination
    main_backup = db.backup_to(main_destination)
    obs_backup = observability_db.backup_to(obs_destination)
    click.echo(
        json.dumps(
            {
                "main": str(main_backup),
                "observability": str(obs_backup),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
