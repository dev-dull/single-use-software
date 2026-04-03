"""Track published apps and their serving endpoints."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


class PublishedAppStore:
    """SQLite-backed store mapping published apps to their serving pod IP."""

    def __init__(self, db_path: str = "published_apps.db") -> None:
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS published_apps (
                team      TEXT NOT NULL,
                app_slug  TEXT NOT NULL,
                pod_ip    TEXT NOT NULL,
                pod_name  TEXT NOT NULL,
                published_by TEXT NOT NULL DEFAULT 'anonymous',
                published_at TEXT NOT NULL,
                PRIMARY KEY (team, app_slug)
            )
            """
        )
        self._conn.commit()

    def publish(self, team: str, app_slug: str, pod_ip: str, pod_name: str, published_by: str = "anonymous") -> None:
        """Register or update a published app's serving endpoint."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO published_apps (team, app_slug, pod_ip, pod_name, published_by, published_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (team, app_slug) DO UPDATE SET
                pod_ip = excluded.pod_ip,
                pod_name = excluded.pod_name,
                published_by = excluded.published_by,
                published_at = excluded.published_at
            """,
            (team, app_slug, pod_ip, pod_name, published_by, now),
        )
        self._conn.commit()

    def get(self, team: str, app_slug: str) -> dict | None:
        """Look up a published app's serving endpoint."""
        row = self._conn.execute(
            "SELECT * FROM published_apps WHERE team = ? AND app_slug = ?",
            (team, app_slug),
        ).fetchone()
        return dict(row) if row else None

    def delete(self, team: str, app_slug: str) -> None:
        """Remove a published app."""
        self._conn.execute(
            "DELETE FROM published_apps WHERE team = ? AND app_slug = ?",
            (team, app_slug),
        )
        self._conn.commit()

    def list_all(self) -> list[dict]:
        """List all published apps."""
        rows = self._conn.execute("SELECT * FROM published_apps").fetchall()
        return [dict(r) for r in rows]
