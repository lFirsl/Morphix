"""TrimTab — optional start/end trim controls."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from morphix_core.validation import check_trim_values
from morphix_ui.tabs.base import BaseTab
from morphix_ui.time_utils import format_time, parse_time

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class TrimParams:
    """Collected values from the Trim tab."""

    enabled: bool
    start: float | None
    end: float | None


class TrimTab(BaseTab):
    """Tab for setting optional trim start/end timestamps."""

    label = "Trim"

    def __init__(
        self,
        parent: tk.Misc,
        shared_state: Any,
        app: tk.Misc,
        **kwargs: Any,
    ) -> None:
        self._app = app
        # Create vars before BaseTab.__init__ calls build().
        self.trim_enabled_var = tk.BooleanVar(value=False)
        self.trim_start_var = tk.StringVar(value="00:00:00")
        self.trim_end_var = tk.StringVar(value="00:00:00")
        super().__init__(parent, shared_state, **kwargs)

    def build(self) -> None:
        """Construct trim checkbox and collapsible time entry frame."""
        padding = {"padx": 10, "pady": 6}

        tk.Checkbutton(
            self,
            text="Enable Trim",
            variable=self.trim_enabled_var,
            command=self._on_trim_toggle,
        ).grid(row=0, column=0, columnspan=4, sticky="w", **padding)

        # Time entry sub-frame — hidden by default.
        self.trim_frame = tk.Frame(self)
        self.trim_frame.grid_forget()

        tk.Label(self.trim_frame, text="Start").grid(
            row=0, column=0, sticky="w", padx=(15, 4), pady=2
        )
        self.trim_start_entry = tk.Entry(
            self.trim_frame, textvariable=self.trim_start_var, width=12
        )
        self.trim_start_entry.grid(row=0, column=1, sticky="w", pady=2)

        tk.Label(self.trim_frame, text="End").grid(
            row=0, column=2, padx=(15, 4), pady=2
        )
        self.trim_end_entry = tk.Entry(
            self.trim_frame, textvariable=self.trim_end_var, width=12
        )
        self.trim_end_entry.grid(row=0, column=3, sticky="w", pady=2)

    def collect(self) -> TrimParams:
        """Return trim settings as a frozen TrimParams."""
        if not self.trim_enabled_var.get():
            return TrimParams(enabled=False, start=None, end=None)
        try:
            start = parse_time(self.trim_start_var.get())
            end = parse_time(self.trim_end_var.get())
        except ValueError:
            return TrimParams(enabled=True, start=None, end=None)
        return TrimParams(enabled=True, start=start, end=end)

    def validate(self) -> str | None:
        """Return an error message if trim values are invalid, else None."""
        if not self.trim_enabled_var.get():
            return None
        try:
            start = parse_time(self.trim_start_var.get())
            end = parse_time(self.trim_end_var.get())
        except ValueError as exc:
            return str(exc)
        ok, msg = check_trim_values(
            start, end, self.shared_state.trim_duration_seconds
        )
        return None if ok else msg

    def set_enabled(self, enabled: bool) -> None:
        """Enable/disable time entry widgets (checkbox always stays enabled)."""
        state = "normal" if enabled else "disabled"
        self.trim_start_entry.config(state=state)
        self.trim_end_entry.config(state=state)

    def set_end_time(self, seconds: float) -> None:
        """Called by the main window after a file is probed.

        Updates shared_state.trim_duration_seconds and auto-fills the end field.
        """
        self.shared_state.trim_duration_seconds = seconds
        self.trim_end_var.set(format_time(seconds))

    def _on_trim_toggle(self) -> None:
        """Show or hide the time entry frame when the checkbox changes."""
        if self.trim_enabled_var.get():
            self.trim_frame.grid(row=1, column=0, columnspan=4, sticky="w")
        else:
            self.trim_frame.grid_forget()

    # ------------------------------------------------------------------
    # Static helpers (delegate to time_utils; kept as statics for test compat)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time(time_str: str) -> float:
        return parse_time(time_str)

    @staticmethod
    def _format_time(seconds: float) -> str:
        return format_time(seconds)
