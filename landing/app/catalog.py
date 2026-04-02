"""Discover applications by scanning the apps/ directory tree."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def scan_apps(
    root: str | Path | None = None,
    user_groups: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Walk ``apps/{team}/{app-slug}/`` directories and return metadata.

    Each directory that contains a ``sus.json`` file is treated as a
    published application.  The parsed JSON is augmented with ``team``
    and ``slug`` keys derived from the directory structure.

    Parameters
    ----------
    root:
        Filesystem path to the ``apps/`` directory.  Defaults to the
        ``SUS_APPS_ROOT`` environment variable, falling back to
        ``/repo/apps``.
    user_groups:
        If provided, only apps whose ``visibility`` list intersects with
        *user_groups* are returned.  Apps with an empty ``visibility``
        list or one that contains ``"default"`` are visible to everyone.
        When *user_groups* is ``None`` all apps are returned (backwards
        compatible).
    """

    if root is None:
        root = os.environ.get("SUS_APPS_ROOT", "/repo/apps")

    root = Path(root)
    apps: list[dict[str, Any]] = []

    if not root.is_dir():
        return apps

    for team_dir in sorted(root.iterdir()):
        if not team_dir.is_dir():
            continue
        team = team_dir.name

        for app_dir in sorted(team_dir.iterdir()):
            if not app_dir.is_dir():
                continue
            slug = app_dir.name
            manifest = app_dir / "sus.json"

            if not manifest.is_file():
                continue

            try:
                with open(manifest) as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

            meta["team"] = team
            meta["slug"] = slug

            # Group-based visibility filtering
            if user_groups is not None:
                visibility = meta.get("visibility", [])
                if visibility and "default" not in visibility:
                    if not set(visibility) & set(user_groups):
                        continue

            apps.append(meta)

    return apps
