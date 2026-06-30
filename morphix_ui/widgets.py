"""Reusable Tkinter UI helpers for Morphix."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox


def set_widgets_state(root: tk.Misc, widgets: list, state: str) -> None:
    """Batch enable/disable widgets via a single after() call.

    Args:
        root: The root widget (used to schedule on the main thread).
        widgets: List of widgets to update.
        state: "normal" or "disabled".
    """

    def _apply():
        for widget in widgets:
            widget.config(state=state)

    root.after(0, _apply)


def show_error(parent: tk.Misc, message: str) -> None:
    """Show a Morphix error dialog on the main thread."""
    parent.after(0, lambda: messagebox.showerror("Morphix", message))


def show_warning(parent: tk.Misc, title: str, message: str) -> None:
    """Show a warning dialog on the main thread."""
    parent.after(0, lambda: messagebox.showwarning(title, message))


def set_status(widget: tk.Label, text: str) -> None:
    """Update a status label on the main thread."""
    widget.after(0, lambda: widget.config(text=text))
