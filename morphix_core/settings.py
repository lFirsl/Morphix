"""User settings persistence for Morphix."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass


@dataclass
class MorphixSettings:
    """Morphix user settings stored at %APPDATA%/Morphix/settings.json."""

    default_mb: float = 20


def _settings_path() -> str:
    """Return the path to the settings JSON file."""
    appdata = os.environ.get("APPDATA", "")
    return os.path.join(appdata, "Morphix", "settings.json")


def read_settings() -> MorphixSettings:
    """Read settings from disk. Returns defaults on any failure."""
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        default_mb = data.get("default_mb")
        if not isinstance(default_mb, (int, float)) or default_mb <= 0:
            return MorphixSettings()
        return MorphixSettings(default_mb=default_mb)
    except Exception:
        return MorphixSettings()


def write_settings(settings: MorphixSettings | float) -> None:
    """Write settings to disk, creating directories as needed.

    Accepts either a MorphixSettings instance or a raw float (for backward
    compatibility with callers that pass just the MB value).
    """
    if isinstance(settings, (int, float)):
        settings = MorphixSettings(default_mb=settings)
    settings_dir = os.path.dirname(_settings_path())
    os.makedirs(settings_dir, exist_ok=True)
    with open(_settings_path(), "w", encoding="utf-8") as f:
        json.dump(asdict(settings), f)
