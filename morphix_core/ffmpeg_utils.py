import os
import shutil
import subprocess
import sys


def popen_no_window_kwargs():
    # On Windows, suppress console windows for child processes.
    # On other OSes, start a new session to avoid attaching to the parent TTY.
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def find_ffmpeg_binaries():
    # Prefer bundled binaries; fall back to PATH when not found.
    candidates = []
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(os.path.join(bundle_root, "ffmpeg"))
    candidates.append(os.path.join(os.path.dirname(sys.executable), "ffmpeg"))
    candidates.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ffmpeg")))

    for base in candidates:
        ffmpeg_path = os.path.join(base, "ffmpeg.exe")
        ffprobe_path = os.path.join(base, "ffprobe.exe")
        if os.path.isfile(ffmpeg_path) and os.path.isfile(ffprobe_path):
            return ffmpeg_path, ffprobe_path, "bundled"

    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    if ffmpeg_path and ffprobe_path:
        return ffmpeg_path, ffprobe_path, "path"

    return None, None, "missing"


def get_ffmpeg_version(ffmpeg_path):
    # Extract the version string from `ffmpeg -version` output.
    if not ffmpeg_path:
        return "missing"
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            check=False,
            capture_output=True,
            text=True,
            **popen_no_window_kwargs(),
        )
    except OSError:
        return "unknown"
    if result.returncode != 0 or not result.stdout:
        return "unknown"
    first_line = result.stdout.splitlines()[0]
    prefix = "ffmpeg version "
    if first_line.startswith(prefix):
        return first_line[len(prefix):].split(" ", 1)[0]
    return "unknown"


def detect_available_encoders(ffmpeg_path):
    """Run ffmpeg -encoders and return a set of available video encoder names."""
    if not ffmpeg_path:
        return set()
    try:
        result = subprocess.run(
            [ffmpeg_path, "-encoders", "-hide_banner"],
            check=False,
            capture_output=True,
            text=True,
            **popen_no_window_kwargs(),
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()
    encoders = set()
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and len(parts[0]) >= 6 and parts[0][0] == "V":
            encoders.add(parts[1])
    return encoders


def detect_build_type(ffmpeg_path):
    """Return 'gpl' if libx264 is available, 'lgpl' otherwise."""
    encoders = detect_available_encoders(ffmpeg_path)
    return "gpl" if "libx264" in encoders else "lgpl"


def ffprobe_media(path, ffprobe_path):
    import json
    # Run ffprobe directly so we can suppress console windows on Windows.
    cmd = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        **popen_no_window_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    return json.loads(result.stdout)
