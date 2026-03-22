import json
import os


def read_settings():
    # Read %APPDATA%\Morphix\settings.json; return {"default_mb": 20} on any failure.
    try:
        appdata = os.environ.get("APPDATA", "")
        settings_path = os.path.join(appdata, "Morphix", "settings.json")
        with open(settings_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        default_mb = data.get("default_mb")
        if not isinstance(default_mb, (int, float)) or default_mb <= 0:
            return {"default_mb": 20}
        return {"default_mb": default_mb}
    except Exception:
        return {"default_mb": 20}


def write_settings(default_mb):
    # Write {"default_mb": value} to %APPDATA%\Morphix\settings.json, creating dirs as needed.
    appdata = os.environ.get("APPDATA", "")
    settings_dir = os.path.join(appdata, "Morphix")
    os.makedirs(settings_dir, exist_ok=True)
    settings_path = os.path.join(settings_dir, "settings.json")
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump({"default_mb": default_mb}, f)
