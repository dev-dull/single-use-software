"""SQLite-backed session store for build pod sessions."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


class SessionStore:
    """Manages a lightweight SQLite database that tracks active build sessions."""

    def __init__(self, db_path: str = "sessions.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_table()

    def _create_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                user_id   TEXT NOT NULL,
                app_slug  TEXT NOT NULL,
                pod_name  TEXT NOT NULL,
                branch    TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (user_id, app_slug)
            )
            """
        )
        self._conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        return dict(row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def upsert(self, user_id: str, pod_name: str, branch: str, app_slug: str) -> None:
        """Insert or replace a session record."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO sessions (user_id, pod_name, branch, app_slug, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (user_id, app_slug) DO UPDATE SET
                pod_name  = excluded.pod_name,
                branch    = excluded.branch,
                last_seen = excluded.last_seen
            """,
            (user_id, pod_name, branch, app_slug, now),
        )
        self._conn.commit()

    def get(self, user_id: str, app_slug: str) -> dict | None:
        """Fetch a single session by user and app."""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND app_slug = ?",
            (user_id, app_slug),
        ).fetchone()
        return self._row_to_dict(row)

    def get_by_pod(self, pod_name: str) -> dict | None:
        """Fetch a session by pod name."""
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE pod_name = ?",
            (pod_name,),
        ).fetchone()
        return self._row_to_dict(row)

    def update_last_seen(self, pod_name: str) -> None:
        """Touch the last_seen timestamp for a given pod."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE sessions SET last_seen = ? WHERE pod_name = ?",
            (now, pod_name),
        )
        self._conn.commit()

    def delete(self, user_id: str, app_slug: str) -> None:
        """Remove a session record."""
        self._conn.execute(
            "DELETE FROM sessions WHERE user_id = ? AND app_slug = ?",
            (user_id, app_slug),
        )
        self._conn.commit()

    def list_sessions(self, user_id: str | None = None) -> list[dict]:
        """List sessions, optionally filtered by user."""
        if user_id:
            rows = self._conn.execute(
                "SELECT * FROM sessions WHERE user_id = ?", (user_id,)
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM sessions").fetchall()
        return [dict(r) for r in rows]
