"""SQLite-backed analytics tracker for usage events and daily stats."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone


class AnalyticsTracker:
    """Tracks usage events and computes aggregate statistics."""

    def __init__(self, db_path: str = "analytics.db") -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS events (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                user_id    TEXT NOT NULL,
                team       TEXT NOT NULL DEFAULT '',
                app_slug   TEXT NOT NULL DEFAULT '',
                metadata   TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_type ON events (event_type);
            CREATE INDEX IF NOT EXISTS idx_events_user ON events (user_id);
            CREATE INDEX IF NOT EXISTS idx_events_created ON events (created_at);

            CREATE TABLE IF NOT EXISTS daily_stats (
                date            TEXT NOT NULL,
                active_users    INTEGER NOT NULL DEFAULT 0,
                build_sessions  INTEGER NOT NULL DEFAULT 0,
                run_sessions    INTEGER NOT NULL DEFAULT 0,
                apps_published  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (date)
            );
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Event tracking
    # ------------------------------------------------------------------

    def track_event(
        self,
        event_type: str,
        user_id: str,
        team: str = "",
        app_slug: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Insert an analytics event."""
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT INTO events (event_type, user_id, team, app_slug, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event_type,
                user_id,
                team,
                app_slug,
                json.dumps(metadata or {}),
                now,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_events(
        self,
        event_type: str | None = None,
        user_id: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events with optional filters."""
        clauses: list[str] = []
        params: list[str | int] = []

        if event_type is not None:
            clauses.append("event_type = ?")
            params.append(event_type)
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        query = f"SELECT * FROM events{where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            # Parse metadata JSON back to dict
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = {}
            results.append(d)
        return results

    def get_daily_stats(self, days: int = 30) -> list[dict]:
        """Return daily stats for the last N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self._conn.execute(
            "SELECT * FROM daily_stats WHERE date >= ? ORDER BY date DESC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]

    def compute_daily_stats(self, date: str) -> dict:
        """Aggregate events for a given date into the daily_stats table.

        *date* should be in YYYY-MM-DD format.
        """
        day_start = f"{date}T00:00:00"
        day_end = f"{date}T23:59:59"

        active_users = self._conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= ? AND created_at <= ?",
            (day_start, day_end),
        ).fetchone()[0]

        build_sessions = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'build_view' AND created_at >= ? AND created_at <= ?",
            (day_start, day_end),
        ).fetchone()[0]

        run_sessions = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'run_view' AND created_at >= ? AND created_at <= ?",
            (day_start, day_end),
        ).fetchone()[0]

        apps_published = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'app_published' AND created_at >= ? AND created_at <= ?",
            (day_start, day_end),
        ).fetchone()[0]

        stats = {
            "date": date,
            "active_users": active_users,
            "build_sessions": build_sessions,
            "run_sessions": run_sessions,
            "apps_published": apps_published,
        }

        self._conn.execute(
            """
            INSERT INTO daily_stats (date, active_users, build_sessions, run_sessions, apps_published)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (date) DO UPDATE SET
                active_users   = excluded.active_users,
                build_sessions = excluded.build_sessions,
                run_sessions   = excluded.run_sessions,
                apps_published = excluded.apps_published
            """,
            (date, active_users, build_sessions, run_sessions, apps_published),
        )
        self._conn.commit()
        return stats

    def get_summary(self) -> dict:
        """Return high-level summary statistics."""
        total_users = self._conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM events"
        ).fetchone()[0]

        total_builds = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'build_view'"
        ).fetchone()[0]

        total_runs = self._conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'run_view'"
        ).fetchone()[0]

        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        weekly_active = self._conn.execute(
            "SELECT COUNT(DISTINCT user_id) FROM events WHERE created_at >= ?",
            (week_ago,),
        ).fetchone()[0]

        return {
            "total_users": total_users,
            "total_builds": total_builds,
            "total_runs": total_runs,
            "weekly_active_users": weekly_active,
        }
