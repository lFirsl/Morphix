"""Standalone helper for FFmpeg download and About dialog."""

import io
import os
import sys
import threading
import tkinter as tk
import webbrowser
import zipfile
from urllib.request import urlopen

GPL_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases"
    "/download/latest/ffmpeg-master-latest-win64-gpl.zip"
)
RELEASES_URL = "https://github.com/BtbN/FFmpeg-Builds/releases"


def download_gpl_ffmpeg(dest_dir, progress_cb=None):
    """Download GPL ffmpeg and extract binaries to dest_dir."""
    os.makedirs(dest_dir, exist_ok=True)
    if progress_cb:
        progress_cb("Downloading GPL ffmpeg...")
    data = urlopen(GPL_URL).read()
    if progress_cb:
        progress_cb("Extracting...")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            basename = os.path.basename(name)
            if basename in ("ffmpeg.exe", "ffprobe.exe"):
                with open(os.path.join(dest_dir, basename), "wb") as f:
                    f.write(zf.read(name))
    if progress_cb:
        progress_cb("Done")
    return True


def _get_dest_dir():
    """Return the ffmpeg/ folder next to the running executable."""
    return os.path.join(os.path.dirname(sys.executable), "ffmpeg")


def show_about_ffmpeg(parent, ffmpeg_path, version, build_type, source):
    """Open the About FFmpeg dialog."""
    win = tk.Toplevel(parent)
    win.title("About FFmpeg")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()

    pad = {"padx": 12, "pady": 4}

    # --- What is FFmpeg? ---
    tk.Label(win, text="What is FFmpeg?", font=("", 10, "bold")).pack(
        anchor="w", **pad
    )
    what_is = (
        "FFmpeg is the engine that does the actual video work.\n"
        "Morphix handles the settings and the interface — FFmpeg\n"
        "is what reads your video, compresses it, and saves the\n"
        "result. Without it, Morphix cannot process any files."
    )
    tk.Label(win, text=what_is, justify="left").pack(
        anchor="w", padx=12, pady=(0, 8)
    )

    tk.Frame(win, height=1, bd=0, bg="#cccccc").pack(
        fill="x", padx=12, pady=(0, 6)
    )

    # --- Current info ---
    source_labels = {
        "user": "user-provided",
        "path": "system PATH",
        "bundled": "bundled (LGPL)",
        "missing": "not found",
    }
    source_text = source_labels.get(source, source)
    path_display = ffmpeg_path or "N/A"

    tk.Label(win, text="Current FFmpeg", font=("", 10, "bold")).pack(
        anchor="w", **pad
    )
    tk.Label(win, text=f"Path: {path_display}").pack(anchor="w", padx=12)
    tk.Label(win, text=f"Version: {version}").pack(anchor="w", padx=12)
    tk.Label(
        win, text=f"Build: {build_type}  •  Source: {source_text}"
    ).pack(anchor="w", padx=12, pady=(0, 8))

    # --- Explanation ---
    tk.Label(win, text="Why upgrade?", font=("", 10, "bold")).pack(
        anchor="w", **pad
    )
    explanation = (
        "Morphix includes a basic encoder (OpenH264) that works out\n"
        "of the box. A higher-quality encoder (libx264) is available\n"
        "for free but cannot be bundled with the app due to licensing."
    )
    tk.Label(win, text=explanation, justify="left").pack(
        anchor="w", padx=12, pady=(0, 8)
    )

    # --- Manual instructions ---
    tk.Label(
        win, text="Manual installation:", font=("", 10, "bold")
    ).pack(anchor="w", **pad)
    steps = (
        "1. Download ffmpeg-master-latest-win64-gpl.zip from:"
    )
    tk.Label(win, text=steps, justify="left").pack(anchor="w", padx=12)
    link = tk.Label(
        win, text=RELEASES_URL, fg="blue", cursor="hand2"
    )
    link.pack(anchor="w", padx=20)
    link.bind("<Button-1>", lambda e: webbrowser.open(RELEASES_URL))

    steps2 = (
        "2. Open the zip → go into the bin folder\n"
        "3. Copy ffmpeg.exe and ffprobe.exe into a\n"
        "   'ffmpeg' folder next to Morphix"
    )
    tk.Label(win, text=steps2, justify="left").pack(
        anchor="w", padx=12, pady=(4, 8)
    )

    # --- Auto download ---
    tk.Label(
        win,
        text=(
            "Alternatively, the button below will attempt to\n"
            "perform the above for you."
        ),
        justify="left",
    ).pack(anchor="w", padx=12, pady=(0, 4))

    status_var = tk.StringVar()
    btn = tk.Button(win, text="Download GPL FFmpeg", width=22)
    btn.pack(pady=4)
    status_label = tk.Label(win, textvariable=status_var, fg="#666666")
    status_label.pack(pady=(0, 8))

    def _do_download():
        btn.config(state="disabled")
        dest = _get_dest_dir()

        def progress(msg):
            win.after(0, lambda: status_var.set(msg))

        def worker():
            try:
                download_gpl_ffmpeg(dest, progress_cb=progress)
                win.after(
                    0,
                    lambda: status_var.set(
                        "Done — restart Morphix to use the better encoder."
                    ),
                )
            except Exception as exc:
                err = str(exc)
                win.after(0, lambda: status_var.set(f"Failed: {err}"))
            finally:
                win.after(0, lambda: btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    btn.config(command=_do_download)
