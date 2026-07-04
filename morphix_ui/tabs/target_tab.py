"""TargetTab — input file, output file, and target size."""

from __future__ import annotations

import os
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from morphix_core.ffmpeg_utils import ffprobe_media, find_ffmpeg_binaries
from morphix_ui.tabs.base import BaseTab
from morphix_ui.time_utils import format_time

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class TargetParams:
    """Collected values from the Target tab."""

    input_path: str
    output_path: str
    size_mb: float


class TargetTab(BaseTab):
    """Tab for selecting input/output files and target compression size."""

    label = "Target"

    def __init__(
        self,
        parent: tk.Misc,
        shared_state: Any,
        app: tk.Misc,
        on_file_selected: Callable[[float], None] | None = None,
        **kwargs: Any,
    ) -> None:
        self._app = app
        self._on_file_selected = on_file_selected
        # StringVars must be created before build() is called by BaseTab.__init__.
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.size_var = tk.StringVar(value="20")
        self.unit_var = tk.StringVar(value="MB")
        super().__init__(parent, shared_state, **kwargs)
        self.output_var.trace_add("write", self._on_output_change)

    def build(self) -> None:
        """Construct input, output and size rows."""
        padding = {"padx": 10, "pady": 6}
        try:
            self.grid_columnconfigure(1, weight=1)
        except Exception:
            pass

        # Row 0: input file
        tk.Label(self, text="Input file").grid(row=0, column=0, sticky="w", **padding)
        self.input_entry = tk.Entry(self, textvariable=self.input_var, width=50)
        self.input_entry.grid(row=0, column=1, sticky="ew", **padding)
        self.browse_input_btn = tk.Button(
            self, text="Browse", command=self.browse_input
        )
        self.browse_input_btn.grid(row=0, column=2, **padding)

        # Row 1: output file
        tk.Label(self, text="Output file").grid(row=1, column=0, sticky="w", **padding)
        self.output_entry = tk.Entry(self, textvariable=self.output_var, width=50)
        self.output_entry.grid(row=1, column=1, sticky="ew", **padding)
        self.browse_output_btn = tk.Button(
            self, text="Browse", command=self.browse_output
        )
        self.browse_output_btn.grid(row=1, column=2, **padding)

        # Row 2: target size
        tk.Label(self, text="Target size").grid(row=2, column=0, sticky="w", **padding)
        self.size_entry = tk.Entry(self, textvariable=self.size_var, width=10)
        self.size_entry.grid(row=2, column=1, sticky="w", **padding)
        self.unit_menu = tk.OptionMenu(self, self.unit_var, "MB", "GB")
        self.unit_menu.grid(row=2, column=2, sticky="w", **padding)

    def collect(self) -> TargetParams:
        """Return current input/output/size as a frozen TargetParams."""
        size_str = self.size_var.get().strip()
        try:
            size_mb = float(size_str)
        except ValueError:
            size_mb = 0.0
        if self.unit_var.get() == "GB":
            size_mb *= 1000
        return TargetParams(
            input_path=self.input_var.get().strip(),
            output_path=self.output_var.get().strip(),
            size_mb=size_mb,
        )

    def validate(self) -> str | None:
        """Return an error message if inputs are invalid, else None."""
        if not self.input_var.get().strip():
            return "Please select an input file."
        size_str = self.size_var.get().strip()
        if not size_str:
            return "Please enter a target size in MB."
        try:
            float(size_str)
        except ValueError:
            return f"Invalid target size: {size_str!r}"
        return None

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all interactive widgets."""
        state = "normal" if enabled else "disabled"
        for widget in (
            self.input_entry,
            self.output_entry,
            self.size_entry,
            self.unit_menu,
            self.browse_input_btn,
            self.browse_output_btn,
        ):
            widget.config(state=state)

    # ------------------------------------------------------------------
    # File browsing
    # ------------------------------------------------------------------

    def browse_input(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="Select video",
            filetypes=[
                ("Video files", "*.mp4;*.mov;*.mkv;*.avi;*.webm"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.input_var.set(path)
            if not self.output_var.get() or self.shared_state.auto_output:
                self._set_output_auto(path)
            self._app.after(0, lambda p=path: self._probe_media_duration(p))

    def browse_output(self) -> None:
        from tkinter import filedialog

        path = filedialog.asksaveasfilename(
            title="Select output file",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self._set_output_manual(path)

    # ------------------------------------------------------------------
    # Output path helpers
    # ------------------------------------------------------------------

    def _set_output_auto(self, input_path: str) -> None:
        base, ext = os.path.splitext(input_path)
        self.shared_state.suppress_output_trace = True
        self.output_var.set(base + "-morphix-compressed" + (ext or ".mp4"))
        self.shared_state.suppress_output_trace = False
        self.shared_state.auto_output = True

    def _set_output_manual(self, output_path: str) -> None:
        self.shared_state.suppress_output_trace = True
        self.output_var.set(output_path)
        self.shared_state.suppress_output_trace = False
        self.shared_state.auto_output = False

    def _on_output_change(self, *_args: Any) -> None:
        if self.shared_state.suppress_output_trace:
            return
        self.shared_state.auto_output = False

    # ------------------------------------------------------------------
    # Media probe
    # ------------------------------------------------------------------

    def _probe_media_duration(self, input_path: str) -> None:
        """Probe the video duration and fire on_file_selected callback."""
        try:
            _, ffprobe_path, _ = find_ffmpeg_binaries()
            if not ffprobe_path:
                return
        except Exception:
            return
        result = ffprobe_media(input_path, ffprobe_path)
        if result is None:
            return
        duration_s = float(result.get("format", {}).get("duration", 0))
        if duration_s <= 0:
            return
        if self._on_file_selected:
            self._on_file_selected(duration_s)

    # ------------------------------------------------------------------
    # Static helpers (kept here for convenience; also in time_utils)
    # ------------------------------------------------------------------

    @staticmethod
    def _format_time(seconds: float) -> str:
        return format_time(seconds)
