"""AdvancedTab — device and encoder selection."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Any

from morphix_core.ffmpeg_utils import detect_available_encoders, find_ffmpeg_binaries
from morphix_ui.tabs.base import BaseTab


@dataclass(frozen=True)
class AdvancedParams:
    """Collected values from the Advanced tab."""

    device_preference: str
    encoder_override: str | None


class AdvancedTab(BaseTab):
    """Tab for selecting compute device and encoder override."""

    label = "Advanced"

    def __init__(
        self,
        parent: tk.Misc,
        shared_state: Any,
        app: tk.Misc,
        **kwargs: Any,
    ) -> None:
        self._app = app
        # Compute default device label before build() runs.
        available_labels = [
            label
            for label, key in shared_state.device_label_to_key.items()
            if label not in shared_state.unavailable_devices
        ]
        default_label = available_labels[0] if available_labels else "CPU"
        self.device_var = tk.StringVar(value=default_label)
        self.encoder_var = tk.StringVar(value="Auto")
        super().__init__(parent, shared_state, **kwargs)

    def build(self) -> None:
        """Construct device and encoder dropdown rows."""
        padding = {"padx": 10, "pady": 6}

        tk.Label(self, text="Device").grid(
            row=0, column=0, sticky="w", **padding
        )
        self.device_menu = tk.OptionMenu(self, self.device_var, "")
        self._refresh_device_menu()
        self.device_menu.grid(row=0, column=1, sticky="w", pady=6)

        tk.Label(self, text="Encoder").grid(
            row=1, column=0, sticky="w", **padding
        )
        self.encoder_menu = tk.OptionMenu(self, self.encoder_var, "Auto")
        self._refresh_encoder_menu()
        self.encoder_menu.grid(row=1, column=1, sticky="w", pady=6)

        self.device_var.trace_add("write", lambda *_: self._refresh_encoder_menu())

    def collect(self) -> AdvancedParams:
        """Return device preference and encoder override as a frozen AdvancedParams."""
        enc = self.encoder_var.get()
        return AdvancedParams(
            device_preference=self._get_device_preference(),
            encoder_override=None if enc == "Auto" else enc,
        )

    def validate(self) -> str | None:
        """Advanced tab has no invalid states — always returns None."""
        return None

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable device and encoder menus."""
        state = "normal" if enabled else "disabled"
        self.device_menu.config(state=state)
        self.encoder_menu.config(state=state)

    # ------------------------------------------------------------------
    # Device / encoder menu helpers
    # ------------------------------------------------------------------

    def _get_device_preference(self) -> str:
        """Map the selected label to a device key for core logic."""
        return self.shared_state.device_label_to_key.get(
            self.device_var.get(), "auto"
        )

    def _refresh_device_menu(self) -> None:
        """Populate the device dropdown, greying out unavailable options."""
        menu = self.device_menu["menu"]
        menu.delete(0, "end")
        for label in self.shared_state.device_label_to_key:
            if label in self.shared_state.unavailable_devices:
                menu.add_command(label=label, state="disabled")
            else:
                menu.add_command(
                    label=label,
                    command=lambda v=label: self.device_var.set(v),
                )

    def _refresh_encoder_menu(self) -> None:
        """Refresh encoder dropdown, greying out unavailable encoders."""
        ffmpeg_path, _, _ = find_ffmpeg_binaries()
        available = detect_available_encoders(ffmpeg_path)

        device_key = self._get_device_preference()
        has_nvidia = (
            device_key in ("nvidia", "auto") and "NVIDIA" in self.device_var.get()
        )

        all_encoders = [
            (
                "h264_nvenc",
                "no NVIDIA GPU",
                lambda: "h264_nvenc" in available and has_nvidia,
            ),
            ("libx264", "needs GPL ffmpeg", lambda: "libx264" in available),
            (
                "libopenh264",
                "not in this ffmpeg build",
                lambda: "libopenh264" in available,
            ),
        ]

        menu = self.encoder_menu["menu"]
        menu.delete(0, "end")
        menu.add_command(label="Auto", command=lambda: self.encoder_var.set("Auto"))

        for name, reason, check_fn in all_encoders:
            if check_fn():
                menu.add_command(
                    label=name, command=lambda n=name: self.encoder_var.set(n)
                )
            else:
                menu.add_command(
                    label=f"{name}  ({reason})", state="disabled"
                )

        # Reset to Auto if current selection is no longer valid.
        current = self.encoder_var.get()
        if current != "Auto":
            valid = any(
                name == current and check_fn()
                for name, _, check_fn in all_encoders
            )
            if not valid:
                self.encoder_var.set("Auto")
