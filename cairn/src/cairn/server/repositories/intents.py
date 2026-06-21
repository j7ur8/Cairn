from __future__ import annotations

import json
from typing import Any

from cairn.server.repositories import sql


def _intent_projection(row: Any, sources_by_intent: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "from": list(sources_by_intent.get(row["id"], [])),
        "to_fact_id": row["to_fact_id"],
        "description": row["description"],
        "creator": row["creator"],
        "worker": row["worker"],
        "last_heartbeat_at": row["last_heartbeat_at"],
        "created_at": row["created_at"],
        "concluded_at": row["concluded_at"],
        "priority_score": row["priority_score"],
        "intent_kind": row["intent_kind"],
        "tags": _decode_tags(row["tags"]),
        "score_reason": row["score_reason"],
    }


class IntentRepository:
    def __init__(self, conn: Any):
        self.conn = conn

    def insert_open(
        self,
        *,
        project_id: str,
        intent_id: str,
        source_fact_ids: list[str],
        description: str,
        creator: str,
        worker: str | None,
        priority_score: float | None = None,
        intent_kind: str | None = None,
        tags: list[str] | None = None,
        score_reason: str | None = None,
        now: str,
    ) -> None:
        claimed = worker is not None
        sql.execute(
            self.conn,
            """
            INSERT INTO intents (
                id, project_id, to_fact_id, description, creator, worker,
                last_heartbeat_at, created_at, concluded_at,
                priority_score, intent_kind, tags, score_reason
            ) VALUES (
                :intent_id, :project_id, NULL, :description, :creator, :worker,
                :last_heartbeat_at, :created_at, NULL,
                :priority_score, :intent_kind, :tags, :score_reason
            )
            """,
            {
                "intent_id": intent_id,
                "project_id": project_id,
                "description": description,
                "creator": creator,
                "worker": worker,
                "last_heartbeat_at": now if claimed else None,
                "created_at": now,
                "priority_score": priority_score,
                "intent_kind": intent_kind,
                "tags": json.dumps(tags or []),
                "score_reason": score_reason,
            },
        )
        self.insert_sources(intent_id, project_id, source_fact_ids)

    def insert_completed_goal(
        self,
        *,
        project_id: str,
        intent_id: str,
        source_fact_ids: list[str],
        description: str,
        worker: str,
        now: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO intents (
                id, project_id, to_fact_id, description, creator, worker,
                last_heartbeat_at, created_at, concluded_at, tags
            ) VALUES (
                :intent_id, :project_id, 'goal', :description, :worker, :worker,
                :now, :now, :now, '[]'
            )
            """,
            {
                "intent_id": intent_id,
                "project_id": project_id,
                "description": description,
                "worker": worker,
                "now": now,
            },
        )
        self.insert_sources(intent_id, project_id, source_fact_ids)

    def insert_concluded(
        self,
        *,
        project_id: str,
        intent_id: str,
        to_fact_id: str,
        source_fact_ids: list[str],
        description: str,
        creator: str,
        now: str,
    ) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO intents (
                id, project_id, to_fact_id, description, creator, worker,
                last_heartbeat_at, created_at, concluded_at, tags
            ) VALUES (
                :intent_id, :project_id, :to_fact_id, :description, :creator, :creator,
                :now, :now, :now, '[]'
            )
            """,
            {
                "intent_id": intent_id,
                "project_id": project_id,
                "to_fact_id": to_fact_id,
                "description": description,
                "creator": creator,
                "now": now,
            },
        )
        self.insert_sources(intent_id, project_id, source_fact_ids)

    def insert_sources(self, intent_id: str, project_id: str, fact_ids: list[str]) -> None:
        for position, fact_id in enumerate(fact_ids):
            sql.execute(
                self.conn,
                """
                INSERT INTO intent_sources (intent_id, project_id, fact_id, position)
                VALUES (:intent_id, :project_id, :fact_id, :position)
                """,
                {
                    "intent_id": intent_id,
                    "project_id": project_id,
                    "fact_id": fact_id,
                    "position": position,
                },
            )

    def insert_fact(self, project_id: str, fact_id: str, description: str) -> None:
        sql.execute(
            self.conn,
            """
            INSERT INTO facts (id, project_id, description)
            VALUES (:fact_id, :project_id, :description)
            """,
            {"fact_id": fact_id, "project_id": project_id, "description": description},
        )

    def claim_open(self, project_id: str, intent_id: str, worker: str, now: str) -> int:
        # Mutual exclusion without an explicit FOR UPDATE: the conditional
        # ``worker IS NULL OR worker = :worker`` predicate plus PostgreSQL
        # row-level locking under READ COMMITTED makes concurrent claims
        # safe. A second writer blocks on the row, re-checks the predicate
        # against the committed version, and matches zero rows. Callers must
        # treat rowcount==1 as "won the claim" and rowcount==0 as "lost".
        # Guarded by tests/test_intent_claim_concurrency.py — do not replace
        # with an unconditional UPDATE or relax the isolation assumption.
        cursor = sql.execute(
            self.conn,
            """
            UPDATE intents
            SET worker = :worker, last_heartbeat_at = :now
            WHERE id = :intent_id
              AND project_id = :project_id
              AND to_fact_id IS NULL
              AND (worker IS NULL OR worker = :worker)
            """,
            {"worker": worker, "now": now, "intent_id": intent_id, "project_id": project_id},
        )
        return cursor.rowcount

    def heartbeat_open(self, project_id: str, intent_id: str, worker: str, now: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE intents
            SET last_heartbeat_at = :now
            WHERE id = :intent_id
              AND project_id = :project_id
              AND to_fact_id IS NULL
              AND worker = :worker
            """,
            {"worker": worker, "now": now, "intent_id": intent_id, "project_id": project_id},
        )
        return cursor.rowcount

    def release_open(self, project_id: str, intent_id: str, worker: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE intents
            SET worker = NULL
            WHERE id = :intent_id
              AND project_id = :project_id
              AND to_fact_id IS NULL
              AND worker = :worker
            """,
            {"intent_id": intent_id, "project_id": project_id, "worker": worker},
        )
        return cursor.rowcount

    def conclude_open(self, project_id: str, intent_id: str, worker: str, fact_id: str, now: str) -> int:
        cursor = sql.execute(
            self.conn,
            """
            UPDATE intents
            SET to_fact_id = :fact_id, worker = :worker, last_heartbeat_at = :now, concluded_at = :now
            WHERE id = :intent_id
              AND project_id = :project_id
              AND to_fact_id IS NULL
              AND worker = :worker
            """,
            {"fact_id": fact_id, "worker": worker, "now": now, "intent_id": intent_id, "project_id": project_id},
        )
        return cursor.rowcount

    def delete_intent(self, project_id: str, intent_id: str) -> None:
        sql.execute(
            self.conn,
            "DELETE FROM intents WHERE id = :intent_id AND project_id = :project_id",
            {"intent_id": intent_id, "project_id": project_id},
        )

    def get_intent(self, project_id: str, intent_id: str) -> Any:
        return sql.fetchone(
            self.conn,
            "SELECT * FROM intents WHERE id = :intent_id AND project_id = :project_id",
            {"intent_id": intent_id, "project_id": project_id},
        )

    def get_intent_projection(self, project_id: str, intent_id: str) -> dict[str, Any] | None:
        row = self.get_intent(project_id, intent_id)
        if row is None:
            return None
        return _intent_projection(row, {intent_id: self.source_fact_ids(project_id, intent_id)})

    def list_intent_projections(self, project_id: str) -> list[dict[str, Any]]:
        rows = sql.fetchall(
            self.conn,
            "SELECT * FROM intents WHERE project_id = :project_id ORDER BY created_at",
            {"project_id": project_id},
        )
        if not rows:
            return []
        source_rows = sql.fetchall(
            self.conn,
            """
            SELECT intent_id, fact_id
            FROM intent_sources
            WHERE project_id = :project_id
            ORDER BY intent_id, position, fact_id
            """,
            {"project_id": project_id},
        )
        sources_by_intent: dict[str, list[str]] = {}
        for source in source_rows:
            sources_by_intent.setdefault(source["intent_id"], []).append(source["fact_id"])
        return [_intent_projection(row, sources_by_intent) for row in rows]

    def list_open_intent_projections(self, project_id: str) -> list[dict[str, Any]]:
        rows = sql.fetchall(
            self.conn,
            """
            SELECT *
            FROM intents
            WHERE project_id = :project_id AND to_fact_id IS NULL
            ORDER BY created_at
            """,
            {"project_id": project_id},
        )
        if not rows:
            return []
        return _hydrate_intent_sources(self.conn, project_id, rows)

    def list_open_intent_projections_batch(
        self, project_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Like :meth:`list_open_intent_projections` but fetches open intents
        and their source facts for *all* the given projects in two queries
        instead of 2\\ :math:`\\times`\\ N. Returns a ``{project_id: [intent, ...]}``
        dict; projects with no open intents are omitted."""
        if not project_ids:
            return {}
        rows = sql.fetchall(
            self.conn,
            """
            SELECT *
            FROM intents
            WHERE project_id = ANY(:project_ids) AND to_fact_id IS NULL
            ORDER BY created_at
            """,
            {"project_ids": project_ids},
        )
        if not rows:
            return {}
        return _hydrate_intent_sources_batch(self.conn, rows)

    def source_fact_ids(self, project_id: str, intent_id: str) -> list[str]:
        rows = sql.fetchall(
            self.conn,
            """
            SELECT fact_id
            FROM intent_sources
            WHERE intent_id = :intent_id AND project_id = :project_id
            ORDER BY position, fact_id
            """,
            {"intent_id": intent_id, "project_id": project_id},
        )
        return [row["fact_id"] for row in rows]


def _hydrate_intent_sources(
    conn: Any, project_id: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach ``source_ids`` to each intent row via a single intent_sources query."""
    intent_ids = {row["id"] for row in rows}
    sources_by_intent: dict[str, list[str]] = {iid: [] for iid in intent_ids}
    for source in sql.fetchall(
        conn,
        """
        SELECT intent_id, fact_id
        FROM intent_sources
        WHERE project_id = :project_id
        ORDER BY intent_id, position, fact_id
        """,
        {"project_id": project_id},
    ):
        bid = sources_by_intent.get(source["intent_id"])
        if bid is not None:
            bid.append(source["fact_id"])
    return [_intent_projection(row, sources_by_intent) for row in rows]


def _hydrate_intent_sources_batch(
    conn: Any, rows: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Same as :func:`_hydrate_intent_sources` but for intents spanning many
    projects. Returns ``{project_id: [intent, …]}``."""
    intent_ids = {row["id"] for row in rows}
    sources_by_intent: dict[str, list[str]] = {iid: [] for iid in intent_ids}
    for source in sql.fetchall(
        conn,
        """
        SELECT intent_id, fact_id
        FROM intent_sources
        WHERE intent_id = ANY(:intent_ids)
        ORDER BY intent_id, position, fact_id
        """,
        {"intent_ids": list(intent_ids)},
    ):
        bid = sources_by_intent.get(source["intent_id"])
        if bid is not None:
            bid.append(source["fact_id"])
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        pid = row["project_id"]
        result.setdefault(pid, []).append(_intent_projection(row, sources_by_intent))
    return result


def _decode_tags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]
