"""MorphixUI — main application window."""

from __future__ import annotations

import os
import sys
import tkinter as tk
from dataclasses import dataclass, field
from tkinter import messagebox

# Ensure repo root is on sys.path so morphix_core can be imported when run directly.
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from morphix_core.core import (  # noqa: E402
    detect_build_type,
    find_ffmpeg_binaries,
    get_available_devices,
    get_ffmpeg_version,
    resolve_device_info,
)
from morphix_ui.widgets import set_widgets_state, show_error  # noqa: E402


@dataclass
class MorphixState:
    """Mutable UI state separate from widget references."""

    is_running: bool = False
    auto_output: bool = True
    suppress_output_trace: bool = False
    trim_duration_seconds: float = 0.0
    openh264_warned: bool = False
    device_label_to_key: dict[str, str] = field(default_factory=dict)
    unavailable_devices: set[str] = field(default_factory=set)


class MorphixUI(tk.Tk):
    def __init__(self, input_file: str | None = None) -> None:
        super().__init__()
        self.title("Morphix")
        self.geometry("560x420")
        self.minsize(520, 420)
        self.resizable(True, True)

        # --- Shared state ---
        self.state = MorphixState()
        device_options = get_available_devices()
        for key, label, available in device_options:
            self.state.device_label_to_key[label] = key
            if not available:
                self.state.unavailable_devices.add(label)

        # --- Build shell UI (tab bar placeholder + static rows) ---
        self._build_ui()

        # --- Instantiate tabs ---
        from morphix_ui.tabs.advanced_tab import AdvancedTab
        from morphix_ui.tabs.target_tab import TargetTab
        from morphix_ui.tabs.trim_tab import TrimTab

        self.tabs = [
            TargetTab(
                self.tab_content,
                self.state,
                self,
                on_file_selected=self._on_file_selected,
            ),
            TrimTab(self.tab_content, self.state, self),
            AdvancedTab(self.tab_content, self.state, self),
        ]

        # --- Build tab bar now that tabs exist ---
        self._build_tab_bar()

        # --- Show first tab by default ---
        self._switch_tab(self.tabs[0])

        # --- Validation chain ---
        from morphix_ui.validation_chain import (
            FileSizeHandler,
            LowCompressionHandler,
            TrimValuesHandler,
            build_chain,
        )

        self.validation_chain = build_chain(
            FileSizeHandler(), TrimValuesHandler(), LowCompressionHandler()
        )

        # --- Post-build initialisation ---
        if input_file:
            target = self._target_tab()
            target.input_var.set(input_file)
            target._set_output_auto(input_file)

        self._refresh_device_label()
        self._refresh_ffmpeg_label()

    # -------------------------------------------------------------------------
    # Layout — shell only (tab bar + content area + buttons + status)
    # -------------------------------------------------------------------------

    def _build_ui(self) -> None:
        """Build the static shell: tab bar, content area, buttons, status."""
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        # Row 0: tab bar placeholder (filled in _build_tab_bar after tabs exist)
        self.tab_bar = tk.Frame(self)
        self.tab_bar.grid(row=0, column=0, sticky="ew", padx=4, pady=(8, 0))

        # Row 1: content area — tabs are gridded inside here
        self.tab_content = tk.Frame(self)
        self.tab_content.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.tab_content.grid_columnconfigure(0, weight=1)

        # Menu bar
        menubar = tk.Menu(self)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About FFmpeg", command=self._open_about_ffmpeg)
        help_menu.add_command(label="About Morphix", command=self._open_about_morphix)
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

        self._build_action_row()
        self._build_tip_row()
        self._build_status_labels()

    def _build_tab_bar(self) -> None:
        """Populate the tab bar with one button per tab."""
        self._tab_buttons: dict[str, tk.Button] = {}
        for tab in self.tabs:
            btn = tk.Button(
                self.tab_bar,
                text=tab.label,
                relief="flat",
                command=lambda t=tab: self._switch_tab(t),
            )
            btn.pack(side="left", padx=(0, 2))
            self._tab_buttons[tab.label] = btn

    def _switch_tab(self, active_tab) -> None:
        """Show *active_tab* and hide all others. Highlight the active button."""
        for tab in self.tabs:
            if tab is active_tab:
                tab.grid(row=0, column=0, sticky="nsew")
            else:
                tab.grid_forget()
        for label, btn in self._tab_buttons.items():
            btn.config(relief="sunken" if label == active_tab.label else "flat")
        self._active_tab = active_tab

    def _build_action_row(self) -> None:
        """Row 2: Compress and Settings buttons."""
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=2, column=0, pady=10)
        self.compress_btn = tk.Button(
            btn_frame, text="Compress", command=self.run_compress
        )
        self.compress_btn.pack(side="left", padx=6)
        self.settings_btn = tk.Button(
            btn_frame, text="Settings", command=self.open_settings
        )
        self.settings_btn.pack(side="left", padx=6)

    def _build_tip_row(self) -> None:
        """Row 3: quality tip."""
        tip_frame = tk.Frame(self)
        tip_frame.grid(row=3, column=0, sticky="ew", padx=10)
        tk.Label(tip_frame, text="Tip:", font=("Segoe UI", 10, "bold")).pack(
            side="left"
        )
        tk.Message(
            tip_frame,
            text=(
                "Lower target sizes can look blurry. Ideally set"
                " the Target Size to the maximum you're able to."
            ),
            width=420,
        ).pack(side="left")

    def _build_status_labels(self) -> None:
        """Rows 4-6: device, ffmpeg, and general status labels."""
        self.device_status = tk.Label(self, text="Device: CPU", fg="#444444")
        self.device_status.grid(row=4, column=0, sticky="w", padx=10, pady=2)

        self.ffmpeg_status = tk.Label(self, text="FFmpeg: path", fg="#444444")
        self.ffmpeg_status.grid(row=5, column=0, sticky="w", padx=10, pady=2)

        self.status = tk.Label(self, text="", fg="#444444")
        self.status.grid(row=6, column=0, sticky="w", padx=10, pady=6)

    # -------------------------------------------------------------------------
    # Tab accessors
    # -------------------------------------------------------------------------

    def _target_tab(self):
        from morphix_ui.tabs.target_tab import TargetTab

        return next(t for t in self.tabs if isinstance(t, TargetTab))

    def _trim_tab(self):
        from morphix_ui.tabs.trim_tab import TrimTab

        return next(t for t in self.tabs if isinstance(t, TrimTab))

    # -------------------------------------------------------------------------
    # File probe callback
    # -------------------------------------------------------------------------

    def _on_file_selected(self, duration_s: float) -> None:
        """Called by TargetTab after a successful media probe."""
        self._trim_tab().set_end_time(duration_s)

    # -------------------------------------------------------------------------
    # Compression
    # -------------------------------------------------------------------------

    def run_compress(self) -> None:
        if self.state.is_running:
            return

        # Collect from all tabs.
        params = {tab.label: tab.collect() for tab in self.tabs}
        target = params["Target"]
        trim = params["Trim"]
        advanced = params["Advanced"]

        # Per-tab validation (each tab's own validate()).
        for tab in self.tabs:
            msg = tab.validate()
            if msg:
                show_error(self, msg)
                return

        # CoR validation chain (errors + warnings).
        params["_trim_duration"] = self.state.trim_duration_seconds
        results = self.validation_chain.handle(params)
        for result in results:
            if result.severity == "error":
                show_error(self, result.message)
                return
            if result.severity == "warning":
                proceed = messagebox.askokcancel(
                    "Morphix — Warning", result.message
                )
                if not proceed:
                    return

        self.state.is_running = True
        self._set_controls_enabled(False)
        self._refresh_device_label()
        self._refresh_ffmpeg_label()
        self._set_status("Running compression...")

        from morphix_ui.compression_worker import (
            CompressionCallbacks,
            start_compression,
        )

        def _on_warning(msg: str) -> None:
            if not self.state.openh264_warned:
                self.state.openh264_warned = True
                self.after(
                    0,
                    lambda: messagebox.showwarning("Morphix — Encoder Warning", msg),
                )

        def _on_finish() -> None:
            self.state.is_running = False
            self._set_controls_enabled(True)

        trim_start = trim.start if trim.enabled else None
        trim_end = trim.end if trim.enabled else None

        callbacks = CompressionCallbacks(
            on_status=self._set_status,
            on_done=_on_finish,
            on_error=lambda msg: (show_error(self, msg), _on_finish()),
            on_warning=_on_warning,
            on_encoder_info=lambda dev, enc: self.after(
                0,
                lambda: self.device_status.config(
                    text=f"Device: {dev} | Encoder: {enc}"
                ),
            ),
        )

        start_compression(
            input_path=target.input_path,
            output_path=target.output_path or None,
            size_value=target.size_mb,
            device_preference=advanced.device_preference,
            encoder_override=advanced.encoder_override,
            trim_start=trim_start,
            trim_end=trim_end,
            callbacks=callbacks,
        )

    # -------------------------------------------------------------------------
    # Settings dialog
    # -------------------------------------------------------------------------

    def open_settings(self) -> None:
        from morphix_ui.dialogs import show_settings_dialog

        show_settings_dialog(self)

    # -------------------------------------------------------------------------
    # UI state helpers
    # -------------------------------------------------------------------------

    def _set_status(self, text: str) -> None:
        self.after(0, lambda: self.status.config(text=text))

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        set_widgets_state(self, [self.compress_btn, self.settings_btn], state)
        for tab in self.tabs:
            tab.set_enabled(enabled)

    def _refresh_device_label(self) -> None:
        from morphix_ui.tabs.advanced_tab import AdvancedTab

        adv_tab = next((t for t in self.tabs if isinstance(t, AdvancedTab)), None)
        pref = adv_tab._get_device_preference() if adv_tab else "auto"
        device_label, _ = resolve_device_info(pref)
        self.device_status.config(text=f"Device: {device_label}")

    def _refresh_ffmpeg_label(self) -> None:
        ffmpeg_path, _, source = find_ffmpeg_binaries()
        version = get_ffmpeg_version(ffmpeg_path)
        build = detect_build_type(ffmpeg_path)
        source_label = {
            "user": "user-provided",
            "path": "system PATH",
            "bundled": "bundled",
        }.get(source, "missing")

        if source == "missing":
            self.ffmpeg_status.config(
                text="FFmpeg: not found — See Help → About FFmpeg"
            )
            self.compress_btn.config(state="disabled")
        else:
            self.ffmpeg_status.config(
                text=(
                    f"FFmpeg: {source_label} ({version}, {build})"
                    " — See Help → About FFmpeg"
                )
            )
            if not self.state.is_running:
                self.compress_btn.config(state="normal")

    def _open_about_ffmpeg(self) -> None:
        from morphix_ui.ffmpeg_download import show_about_ffmpeg

        ffmpeg_path, _, source = find_ffmpeg_binaries()
        version = get_ffmpeg_version(ffmpeg_path)
        build = detect_build_type(ffmpeg_path)
        show_about_ffmpeg(self, ffmpeg_path, version, build, source)

    def _open_about_morphix(self) -> None:
        from morphix_ui.dialogs import show_about_morphix

        show_about_morphix(self)


if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    app = MorphixUI(input_file=input_file)
    app.mainloop()
