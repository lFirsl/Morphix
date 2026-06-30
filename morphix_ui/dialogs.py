"""Modal dialogs for Morphix UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

from morphix_core.settings import read_settings, write_settings


def show_settings_dialog(parent: tk.Misc) -> None:
    """Open settings dialog for default context menu MB."""
    win = tk.Toplevel(parent)
    win.title("Morphix Settings")
    win.resizable(False, False)
    win.grab_set()

    padding = {"padx": 12, "pady": 8}

    tk.Label(win, text="Default compression size (MB):").grid(
        row=0, column=0, sticky="w", **padding
    )

    current_mb = read_settings().default_mb
    mb_var = tk.StringVar(value=str(current_mb))
    mb_entry = tk.Entry(win, textvariable=mb_var, width=12)
    mb_entry.grid(row=0, column=1, sticky="w", **padding)

    tk.Label(
        win,
        text=(
            "This value is used by the "
            "'Compress with Morphix' context menu entry."
        ),
        fg="#666666",
        wraplength=320,
    ).grid(row=1, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 8))

    def save():
        raw = mb_var.get().strip()
        try:
            value = float(raw)
            if value <= 0:
                raise ValueError("must be positive")
        except ValueError:
            messagebox.showerror(
                "Invalid value",
                "Please enter a positive number for the default "
                "compression size.",
                parent=win,
            )
            return
        write_settings(value)
        win.destroy()

    btn_frame = tk.Frame(win)
    btn_frame.grid(row=2, column=0, columnspan=2, pady=(4, 12))
    tk.Button(btn_frame, text="Save", command=save).pack(side="left", padx=6)
    tk.Button(btn_frame, text="Cancel", command=win.destroy).pack(
        side="left", padx=6
    )


def show_about_morphix(parent: tk.Misc) -> None:
    """Show About Morphix dialog with version info."""
    from morphix_core import __version__

    messagebox.showinfo(
        "About Morphix",
        f"Morphix v{__version__}\n\n"
        "Compress any video to a target file size.\n\n"
        "https://github.com/lFirsl/Morphix",
    )
