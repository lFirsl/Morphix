import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

# Ensure repo root is on sys.path so morphix_core can be imported when run directly.
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from morphix_core.core import (  # noqa: E402
    detect_available_encoders,
    detect_build_type,
    find_ffmpeg_binaries,
    get_available_devices,
    get_ffmpeg_version,
    resolve_device_info,
    run,
    select_encoder,
)
from morphix_core.ffmpeg_utils import ffprobe_media  # noqa: E402
from morphix_core.settings import read_settings, write_settings  # noqa: E402
from morphix_core.validation import (  # noqa: E402
    check_low_compression_ratio,
    check_target_exceeds_file_size,
    check_trim_values,
)


def find_morphix_exe():
    candidates = [
        os.path.join(os.getcwd(), "dist", "Morphix.exe"),
        os.path.join(os.getcwd(), "Morphix.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


class MorphixUI(tk.Tk):
    def __init__(self, input_file=None):
        super().__init__()
        self.title("Morphix")
        self.geometry("560x440")
        self.minsize(520, 440)
        self.resizable(True, True)

        # --- State variables ---
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.size_var = tk.StringVar(value="20")
        self.unit_var = tk.StringVar(value="MB")
        self.device_options = get_available_devices()
        self.device_label_to_key = {}
        self._unavailable_devices = set()
        for key, label, available in self.device_options:
            if available:
                self.device_label_to_key[label] = key
            else:
                disabled_label = f"{label} (not detected)"
                self.device_label_to_key[disabled_label] = key
                self._unavailable_devices.add(disabled_label)
        available_labels = [
            label for key, label, avail in self.device_options if avail
        ]
        default_device_label = available_labels[0] if available_labels else "CPU"
        self.device_var = tk.StringVar(value=default_device_label)
        self.encoder_var = tk.StringVar(value="Auto")
        self.advanced_var = tk.BooleanVar(value=False)
        self._is_running = False
        self._auto_output = True
        self._suppress_output_trace = False

        # --- Trim state ---
        self.trim_enabled_var = tk.BooleanVar(value=False)
        self.trim_start_var = tk.StringVar(value="00:00:00")
        self.trim_end_var = tk.StringVar(value="00:00:00")
        self.trim_duration_seconds = 0.0  # From video probe.

        self.output_var.trace_add("write", self._on_output_change)

        # --- Build UI layout ---
        self._build_ui()

        # --- Post-build initialization ---
        if input_file:
            self.input_var.set(input_file)
            self._set_output_auto(input_file)
        # Populate the device label on startup so it doesn't stay at CPU until run.
        self._refresh_device_label()
        # Show whether bundled or PATH ffmpeg is being used.
        self._refresh_ffmpeg_label()

    # -------------------------------------------------------------------------
    # Layout / widget construction
    # -------------------------------------------------------------------------

    def _build_ui(self):
        """Construct and grid all widgets. No event logic here."""
        padding = {"padx": 10, "pady": 6}
        self.grid_columnconfigure(1, weight=1)

        # Menu bar
        menubar = tk.Menu(self)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="About FFmpeg", command=self._open_about_ffmpeg
        )
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

        self._build_input_row(padding)
        self._build_output_row(padding)
        self._build_target_size_row(padding)

        # Visual separator before interactive controls.
        tk.Frame(self, height=2, bd=1, relief="groove").grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(6, 6)
        )

        self._build_trim_section(padding)

        # Separator between trim and advanced.
        tk.Frame(self, height=2, bd=1, relief="groove").grid(
            row=6, column=0, columnspan=3, sticky="ew", pady=(6, 6)
        )

        self._build_advanced_section(padding)
        self._build_compress_button(padding)
        self._build_tip_row(padding)
        self._build_status_labels(padding)

    def _build_input_row(self, padding):
        """Row 0: input file selector."""
        tk.Label(self, text="Input file").grid(row=0, column=0, sticky="w", **padding)
        self.input_entry = tk.Entry(self, textvariable=self.input_var, width=50)
        self.input_entry.grid(row=0, column=1, sticky="ew", **padding)
        self.browse_input_btn = tk.Button(
            self, text="Browse", command=self.browse_input
        )
        self.browse_input_btn.grid(row=0, column=2, **padding)

    def _build_output_row(self, padding):
        """Row 1: output file selector."""
        tk.Label(self, text="Output file").grid(row=1, column=0, sticky="w", **padding)
        self.output_entry = tk.Entry(self, textvariable=self.output_var, width=50)
        self.output_entry.grid(row=1, column=1, sticky="ew", **padding)
        self.browse_output_btn = tk.Button(
            self, text="Browse", command=self.browse_output
        )
        self.browse_output_btn.grid(row=1, column=2, **padding)

    def _build_target_size_row(self, padding):
        """Row 2: target size entry and unit selector."""
        tk.Label(self, text="Target size").grid(row=2, column=0, sticky="w", **padding)
        self.size_entry = tk.Entry(self, textvariable=self.size_var, width=10)
        self.size_entry.grid(row=2, column=1, sticky="w", **padding)
        self.unit_menu = tk.OptionMenu(self, self.unit_var, "MB", "GB")
        self.unit_menu.grid(row=2, column=2, sticky="w", **padding)

    def _build_advanced_section(self, padding):
        """Row 7: Advanced collapsible section with Device and Encoder."""
        tk.Checkbutton(
            self,
            text="Advanced",
            variable=self.advanced_var,
            command=self._on_advanced_toggle,
        ).grid(row=7, column=0, columnspan=3, sticky="w", **padding)

        self.advanced_frame = tk.Frame(self)

        tk.Label(self.advanced_frame, text="Device").grid(
            row=0, column=0, sticky="w", padx=(15, 4), pady=2
        )
        self.device_menu = tk.OptionMenu(
            self.advanced_frame, self.device_var, ""
        )
        self._refresh_device_menu()
        self.device_menu.grid(row=0, column=1, sticky="w", pady=2)

        tk.Label(self.advanced_frame, text="Encoder").grid(
            row=1, column=0, sticky="w", padx=(15, 4), pady=2
        )

        self._build_encoder_menu()
        self.encoder_menu.grid(row=1, column=1, sticky="w", pady=2)

        # Update encoder availability when device changes.
        self.device_var.trace_add("write", lambda *_: self._refresh_encoder_menu())

    def _refresh_device_menu(self):
        """Populate device dropdown, greying out unavailable options."""
        menu = self.device_menu["menu"]
        menu.delete(0, "end")
        for label in self.device_label_to_key:
            if label in self._unavailable_devices:
                menu.add_command(
                    label=label, state="disabled"
                )
            else:
                menu.add_command(
                    label=label,
                    command=lambda v=label: self.device_var.set(v),
                )

    def _build_encoder_menu(self):
        """Build the encoder OptionMenu with greyed-out unavailable items."""
        self.encoder_menu = tk.OptionMenu(self.advanced_frame, self.encoder_var, "Auto")
        self._refresh_encoder_menu()

    def _refresh_encoder_menu(self):
        """Refresh encoder dropdown: grey out unavailable encoders."""
        ffmpeg_path, _, _ = find_ffmpeg_binaries()

        ffmpeg_path, _, _ = find_ffmpeg_binaries()
        available = detect_available_encoders(ffmpeg_path)

        device_key = self.device_label_to_key.get(self.device_var.get(), "cpu")
        has_nvidia = (
            device_key in ("nvidia", "auto") and "NVIDIA" in self.device_var.get()
        )

        # All possible encoders with their requirements.
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
                menu.add_command(label=f"{name}  ({reason})", state="disabled")

        # If current selection is no longer valid, reset to Auto.
        current = self.encoder_var.get()
        if current != "Auto":
            valid = any(
                name == current and check_fn() for name, _, check_fn in all_encoders
            )
            if not valid:
                self.encoder_var.set("Auto")

    def _get_encoder_choices(self):
        """Return available encoder options for the dropdown."""
        ffmpeg_path, _, _ = find_ffmpeg_binaries()
        available = detect_available_encoders(ffmpeg_path)
        choices = ["Auto"]
        for name in ["h264_nvenc", "libx264", "libopenh264"]:
            if name in available:
                choices.append(name)
        return choices

    def _on_advanced_toggle(self):
        """Show/hide the advanced options frame."""
        if self.advanced_var.get():
            self.advanced_frame.grid(row=8, column=0, columnspan=4, sticky="w")
        else:
            self.advanced_frame.grid_forget()

    def _build_trim_section(self, padding):
        """Row 4: trim checkbox and conditional time entries."""
        tk.Checkbutton(
            self,
            text="Enable Trim",
            variable=self.trim_enabled_var,
            command=self._on_trim_toggle,
        ).grid(row=4, column=0, columnspan=3, sticky="w", **padding)

        # Frame for time entries (hidden until checkbox checked).
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

    def _on_trim_toggle(self):
        """Show/hide the time entry frame when the trim checkbox changes."""
        if self.trim_enabled_var.get():
            self.trim_frame.grid(row=5, column=0, columnspan=4, sticky="w")
        else:
            self.trim_frame.grid_forget()

    def _probe_media_duration(self, input_path: str):
        """Probe the video and set trim duration bounds."""
        try:
            _, ffprobe_path, _ = find_ffmpeg_binaries()
            if not ffprobe_path:
                return
        except ImportError:
            return
        result = ffprobe_media(input_path, ffprobe_path)
        if result is None:
            return
        duration_s = float(result.get("format", {}).get("duration", 0))
        if duration_s <= 0:
            return
        self.trim_duration_seconds = duration_s
        # Auto-set the end field to match video length.
        self.trim_end_var.set(self._format_time(duration_s))

    @staticmethod
    def _parse_time(time_str: str) -> float:
        """Parse MM:SS or HH:MM:SS to seconds."""
        parts = time_str.strip().split(":")
        if len(parts) == 2:
            m, s = map(int, parts)
            return m * 60 + s
        elif len(parts) == 3:
            h, m, s = map(int, parts)
            return h * 3600 + m * 60 + s
        raise ValueError(f"Invalid time format: {time_str}")

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as HH:MM:SS with zero-padded hours."""
        h = int(seconds) // 3600
        m = (int(seconds) % 3600) // 60
        s = int(seconds) % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _build_compress_button(self, padding):
        """Row 9: compress action button and settings button."""
        btn_frame = tk.Frame(self)
        btn_frame.grid(row=9, column=0, columnspan=3, pady=12)
        self.compress_btn = tk.Button(
            btn_frame, text="Compress", command=self.run_compress
        )
        self.compress_btn.pack(side="left", padx=6)
        self.settings_btn = tk.Button(
            btn_frame, text="Settings", command=self.open_settings
        )
        self.settings_btn.pack(side="left", padx=6)

    def _build_tip_row(self, padding):
        """Row 10: quality tip message."""
        tk.Label(self, text="Tip:", font=("Segoe UI", 10, "bold")).grid(
            row=10, column=0, sticky="w", **padding
        )
        tk.Message(
            self,
            text=(
                "Lower target sizes can look blurry. Ideally set"
                " the Target Size to the maximum you're able to."
            ),
            width=420,
        ).grid(row=10, column=1, columnspan=2, sticky="w", **padding)

    def _build_status_labels(self, padding):
        """Rows 11-13: device status, ffmpeg status, and general status labels."""
        self.device_status = tk.Label(self, text="Device: CPU", fg="#444444")
        self.device_status.grid(
            row=11, column=0, columnspan=3, sticky="w", padx=10, pady=2
        )

        self.ffmpeg_status = tk.Label(self, text="FFmpeg: path", fg="#444444")
        self.ffmpeg_status.grid(
            row=12, column=0, columnspan=3, sticky="w", padx=10, pady=2
        )

        self.status = tk.Label(self, text="", fg="#444444")
        self.status.grid(row=13, column=0, columnspan=3, sticky="w", padx=10, pady=6)

    # -------------------------------------------------------------------------
    # Event handlers — file browsing
    # -------------------------------------------------------------------------

    def browse_input(self):
        path = filedialog.askopenfilename(
            title="Select video",
            filetypes=[
                ("Video files", "*.mp4;*.mov;*.mkv;*.avi;*.webm"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.input_var.set(path)
            if not self.output_var.get() or self._auto_output:
                self._set_output_auto(path)
            # Probe video duration for trim display (non-blocking via after).
            self.after(0, lambda p=path: self._probe_media_duration(p))

    def browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Select output file",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self._set_output_manual(path)

    # -------------------------------------------------------------------------
    # Event handlers — settings
    # -------------------------------------------------------------------------

    def open_settings(self):
        """Open settings dialog for default context menu MB."""
        win = tk.Toplevel(self)
        win.title("Morphix Settings")
        win.resizable(False, False)
        win.grab_set()  # modal

        padding = {"padx": 12, "pady": 8}

        tk.Label(win, text="Default compression size (MB):").grid(
            row=0, column=0, sticky="w", **padding
        )

        current_mb = read_settings().get("default_mb", 20)
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
                    "Please enter a positive number for the default compression size.",
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

    # -------------------------------------------------------------------------
    # Event handlers — compression
    # -------------------------------------------------------------------------

    def run_compress(self):
        if self._is_running:
            return
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        size_mb = self.size_var.get().strip()

        if not input_path:
            messagebox.showerror("Morphix", "Please select an input file.")
            return
        if not size_mb:
            messagebox.showerror("Morphix", "Please enter a target size in MB.")
            return

        size_value = float(size_mb)
        if self.unit_var.get() == "GB":
            size_value = size_value * 1000

        try:
            check_target_exceeds_file_size(size_value, input_path)
        except ValueError as exc:
            messagebox.showerror("Morphix", str(exc))
            return

        # --- Trim validation ---
        trim_start = None
        trim_end = None
        if self.trim_enabled_var.get():
            try:
                trim_start = self._parse_time(self.trim_start_var.get())
                trim_end = self._parse_time(self.trim_end_var.get())
            except ValueError as exc:
                err_msg = str(exc)
                self.after(0, lambda: messagebox.showerror("Morphix", err_msg))
                return
            ok, msg = check_trim_values(
                trim_start, trim_end, self.trim_duration_seconds
            )
            if not ok:
                self.after(0, lambda: messagebox.showerror("Morphix", msg))
                return

        # --- Low compression ratio warning ---
        # When trimming is active AND we have video duration from probe, check against
        # the estimated trimmed segment size instead of the full file. Otherwise use
        # original behavior (full-file comparison).
        trim_enabled = self.trim_enabled_var.get()
        if (
            not trim_enabled
            or self.trim_duration_seconds <= 0
            or trim_start is None
            or trim_end is None
        ):
            # No trim, or no probe data — compare target against original file.
            if check_low_compression_ratio(size_value, input_path):
                proceed = messagebox.askokcancel(
                    "Morphix — High Compression Warning",
                    "The target size is less than 5% of the original file size. "
                    "The output will very likely look poor.\n\n"
                    "Consider using a larger target for a viewable result.\n\n"
                    "Do you want to continue anyway?",
                )
                if not proceed:
                    return
        else:
            # Trimming is active and we have valid data — use estimated trimmed size.
            orig_file_mb = os.path.getsize(input_path) / 1_000_000
            trim_ratio = (trim_end - trim_start) / self.trim_duration_seconds
            est_trimmed_mb = orig_file_mb * trim_ratio
            if size_value < 0.05 * est_trimmed_mb:
                min_mb = est_trimmed_mb * 0.05
                proceed = messagebox.askokcancel(
                    "Morphix — High Compression Warning",
                    f"Your trimmed clip is estimated to be "
                    f"about {est_trimmed_mb:.1f} MB.\n\n"
                    f"The target size ({size_value:.1f} MB) is "
                    f"less than 5% of the "
                    f"estimated trimmed clip size. The output "
                    f"will very likely look poor.\n\n"
                    f"Consider using a target of at least "
                    f"{min_mb:.1f} MB.\n\n"
                    "Do you want to continue anyway?",
                )
                if not proceed:
                    return

        self._is_running = True
        self._set_controls_enabled(False)
        self._refresh_device_label()
        self._refresh_ffmpeg_label()
        self._set_status("Running compression...")
        device_preference = self._get_device_preference()

        def progress_cb(pct, phase):
            # Update status with pass labels and brief descriptions.
            if phase == "PASS1":
                self._set_status(f"Pass 1/2: Analyzing video... {pct:.1f}%")
            elif phase == "PASS2":
                self._set_status(f"Pass 2/2: Encoding final output... {pct:.1f}%")
            elif phase == "CRF":
                self._set_status(f"Encoding (quality-preserving)... {pct:.1f}%")
            else:
                self._set_status(f"Encoding... {pct:.1f}%")

        def worker():
            try:

                def on_warning(msg):
                    if not getattr(self, "_openh264_warned", False):
                        self._openh264_warned = True
                        self.after(
                            0,
                            lambda: messagebox.showwarning(
                                "Morphix — Encoder Warning", msg
                            ),
                        )

                device_label, _ = resolve_device_info(device_preference)
                detected = "nvidia" if "NVIDIA" in device_label else None
                ffmpeg_path, _, _ = find_ffmpeg_binaries()
                available = detect_available_encoders(ffmpeg_path)
                enc_override = self.encoder_var.get()
                if enc_override and enc_override != "Auto":
                    enc_name = enc_override
                else:
                    enc_override = None
                    try:
                        enc_name, _ = select_encoder(
                            available, device_preference, detected
                        )
                    except RuntimeError:
                        enc_name = "none"
                self.after(
                    0,
                    lambda: self.device_status.config(
                        text=f"Device: {device_label} | Encoder: {enc_name}"
                    ),
                )

                run(
                    input_path=input_path,
                    max_mb=size_value,
                    output_path=output_path or None,
                    quality="medium",
                    resolution=None,
                    device_preference=device_preference,
                    overwrite=True,
                    disable_logs=True,
                    progress=True,
                    progress_cb=progress_cb,
                    start=trim_start,
                    end=trim_end,
                    warning_cb=on_warning,
                    encoder_override=enc_override,
                )
                self._set_status("Done.")
            except Exception as exc:
                self._set_status(f"Failed: {exc}")
                err_msg = str(exc)
                self.after(0, lambda: messagebox.showerror("Morphix", err_msg))
            finally:
                self._is_running = False
                self._set_controls_enabled(True)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    # -------------------------------------------------------------------------
    # UI state helpers
    # -------------------------------------------------------------------------

    def _set_status(self, text):
        # Ensure UI updates happen on the main thread.
        self.after(0, lambda: self.status.config(text=text))

    def _set_controls_enabled(self, enabled):
        # Enable/disable all input controls safely from any thread.
        state = "normal" if enabled else "disabled"
        self.after(0, lambda: self.compress_btn.config(state=state))
        self.after(0, lambda: self.settings_btn.config(state=state))
        self.after(0, lambda: self.input_entry.config(state=state))
        self.after(0, lambda: self.output_entry.config(state=state))
        self.after(0, lambda: self.size_entry.config(state=state))
        self.after(0, lambda: self.unit_menu.config(state=state))
        self.after(0, lambda: self.browse_input_btn.config(state=state))
        self.after(0, lambda: self.browse_output_btn.config(state=state))
        self.after(0, lambda: self.device_menu.config(state=state))
        self.after(0, lambda: self.trim_start_entry.config(state=state))
        self.after(0, lambda: self.trim_end_entry.config(state=state))

    def _refresh_device_label(self):
        # Resolve the selected device and update the UI label.
        device_label, _ = resolve_device_info(self._get_device_preference())
        self.device_status.config(text=f"Device: {device_label}")

    def _refresh_ffmpeg_label(self):
        # Detect which ffmpeg is being used and display info.
        ffmpeg_path, _, source = find_ffmpeg_binaries()
        version = get_ffmpeg_version(ffmpeg_path)
        build = detect_build_type(ffmpeg_path)
        if source == "user":
            label = "user-provided"
        elif source == "path":
            label = "system PATH"
        elif source == "bundled":
            label = "bundled"
        else:
            label = "missing"

        if source == "missing":
            self.ffmpeg_status.config(
                text="FFmpeg: not found — See Help → About FFmpeg"
            )
            self.compress_btn.config(state="disabled")
        else:
            self.ffmpeg_status.config(
                text=(
                    f"FFmpeg: {label} ({version}, {build})"
                    " — See Help → About FFmpeg"
                )
            )
            if not self._is_running:
                self.compress_btn.config(state="normal")

    def _get_device_preference(self):
        # Map the selected label to a device key for the core logic.
        return self.device_label_to_key.get(self.device_var.get(), "auto")

    def _open_about_ffmpeg(self):
        """Open the About FFmpeg dialog."""
        from morphix_ui.ffmpeg_download import show_about_ffmpeg

        ffmpeg_path, _, source = find_ffmpeg_binaries()
        version = get_ffmpeg_version(ffmpeg_path)
        build = detect_build_type(ffmpeg_path)
        show_about_ffmpeg(self, ffmpeg_path, version, build, source)

    # -------------------------------------------------------------------------
    # Output path helpers
    # -------------------------------------------------------------------------

    def _set_output_auto(self, input_path):
        # Auto-generate output path based on the selected input.
        base, ext = os.path.splitext(input_path)
        self._suppress_output_trace = True
        self.output_var.set(base + "-morphix-compressed" + (ext or ".mp4"))
        self._suppress_output_trace = False
        self._auto_output = True

    def _set_output_manual(self, output_path):
        # Set output path explicitly and mark it as user-defined.
        self._suppress_output_trace = True
        self.output_var.set(output_path)
        self._suppress_output_trace = False
        self._auto_output = False

    def _on_output_change(self, *_args):
        # Treat direct user edits as manual output selection.
        if self._suppress_output_trace:
            return
        self._auto_output = False


if __name__ == "__main__":
    input_file = sys.argv[1] if len(sys.argv) > 1 else None
    app = MorphixUI(input_file=input_file)
    app.mainloop()
