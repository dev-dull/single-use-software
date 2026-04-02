"""SUS configuration loader -- reads sus_config.json and builds providers."""

from __future__ import annotations

import json
import os
from typing import Any

from .identity import (
    IdentityProvider,
    LocalDatabaseProvider,
    ProxyHeaderProvider,
    SingleUserProvider,
)

_DEFAULT_CONFIG_PATH = "sus_config.json"

_DEFAULT_CONFIG: dict[str, Any] = {
    "identity_provider": "single-user",
    "identity_options": {},
}


def load_config() -> dict[str, Any]:
    """Load and return the SUS configuration dictionary.

    The config file path is determined by the ``SUS_CONFIG_PATH``
    environment variable, falling back to ``sus_config.json`` in the
    current working directory.  If the file does not exist, sensible
    defaults are returned.
    """
    path = os.environ.get("SUS_CONFIG_PATH", _DEFAULT_CONFIG_PATH)
    try:
        with open(path) as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(_DEFAULT_CONFIG)


def create_identity_provider(config: dict[str, Any]) -> IdentityProvider:
    """Instantiate the identity provider described by *config*.

    Raises :class:`ValueError` for unrecognised provider names.
    """
    name = config.get("identity_provider", "single-user")
    options = config.get("identity_options", {})

    if name == "single-user":
        return SingleUserProvider()
    if name == "proxy-header":
        return ProxyHeaderProvider()
    if name == "local-database":
        return LocalDatabaseProvider(
            db_path=options.get("db_path", "users.db")
        )
    raise ValueError(f"Unknown identity provider: {name!r}")
