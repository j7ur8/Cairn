from __future__ import annotations

import shutil

from cairn.server import db
from cairn.server.application.replay.attachments import attachments_root, copy_project_attachments
from cairn.server.application.replay.service import (
    activate_replay_project,
    advance_replay_run_in_transaction,
    create_replay_run_in_transaction,
)
from cairn.server.repositories.projects import ProjectRepository
from cairn.server.schemas import (
    ReplayRunCreateRequest,
    ReplayRunCreateResponse,
)


def create_replay_run(project_id: str, body: ReplayRunCreateRequest):
    replay_project_id: str | None = None
    run_id: str | None = None
    with db.session_scope() as conn:
        run_id, replay_project_id = create_replay_run_in_transaction(conn, project_id, body)

    try:
        copy_project_attachments(project_id, replay_project_id)
        with db.session_scope() as conn:
            detail = activate_replay_project(conn, replay_project_id)
            return ReplayRunCreateResponse(
                run_id=run_id,
                source_project_id=project_id,
                project=detail,
            )
    except Exception:
        if replay_project_id:
            delete_replay_project_best_effort(replay_project_id)
        raise


def advance_replay_run(project_id: str):
    with db.session_scope() as conn:
        return advance_replay_run_in_transaction(conn, project_id)


def delete_replay_project_best_effort(replay_project_id: str) -> None:
    shutil.rmtree(attachments_root() / replay_project_id, ignore_errors=True)
    with db.session_scope() as conn:
        ProjectRepository(conn).delete(replay_project_id)
