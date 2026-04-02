"""Version tracker backed by SQLite — records publish history for rollback."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone


class VersionTracker:
    """Tracks published versions of apps in a local SQLite database."""

    def __init__(self, db_path: str = "versions.db") -> None:
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Return a thread-local connection."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _init_db(self) -> None:
        """Create the versions table if it does not exist."""
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS versions (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                team           TEXT    NOT NULL,
                app_slug       TEXT    NOT NULL,
                version        INTEGER NOT NULL,
                commit_hash    TEXT    NOT NULL,
                published_by   TEXT    NOT NULL,
                published_at   TEXT    NOT NULL,
                image_tag      TEXT    NOT NULL,
                message        TEXT    NOT NULL DEFAULT '',
                is_active      INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_latest_version_number(self, team: str, app_slug: str) -> int:
        """Return the highest version number for an app (0 if none)."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM versions WHERE team = ? AND app_slug = ?",
            (team, app_slug),
        ).fetchone()
        return row["v"]

    def record_version(
        self,
        team: str,
        app_slug: str,
        commit_hash: str,
        published_by: str,
        image_tag: str,
        message: str = "",
    ) -> int:
        """Insert a new version, deactivate previous ones, and return the new version number."""
        conn = self._get_conn()

        new_version = self.get_latest_version_number(team, app_slug) + 1
        now = datetime.now(timezone.utc).isoformat()

        # Deactivate all previous versions for this app.
        conn.execute(
            "UPDATE versions SET is_active = 0 WHERE team = ? AND app_slug = ?",
            (team, app_slug),
        )

        conn.execute(
            """
            INSERT INTO versions (team, app_slug, version, commit_hash, published_by, published_at, image_tag, message, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (team, app_slug, new_version, commit_hash, published_by, now, image_tag, message),
        )
        conn.commit()
        return new_version

    def get_versions(self, team: str, app_slug: str) -> list[dict]:
        """List all versions for an app, newest first."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM versions WHERE team = ? AND app_slug = ? ORDER BY version DESC",
            (team, app_slug),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_version(self, team: str, app_slug: str) -> dict | None:
        """Get the currently active version."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM versions WHERE team = ? AND app_slug = ? AND is_active = 1 LIMIT 1",
            (team, app_slug),
        ).fetchone()
        return dict(row) if row else None

    def get_version(self, team: str, app_slug: str, version: int) -> dict | None:
        """Get a specific version."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM versions WHERE team = ? AND app_slug = ? AND version = ?",
            (team, app_slug, version),
        ).fetchone()
        return dict(row) if row else None

    def set_active(self, team: str, app_slug: str, version: int) -> None:
        """Mark a version as active, deactivating all others for the same app."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE versions SET is_active = 0 WHERE team = ? AND app_slug = ?",
            (team, app_slug),
        )
        conn.execute(
            "UPDATE versions SET is_active = 1 WHERE team = ? AND app_slug = ? AND version = ?",
            (team, app_slug, version),
        )
        conn.commit()
