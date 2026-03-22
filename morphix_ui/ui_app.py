import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

# Ensure repo root is on sys.path so morphix_core can be imported when run directly.
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from morphix_core.core import (
    find_ffmpeg_binaries,
    get_available_devices,
    get_ffmpeg_version,
    resolve_device_info,
    run,
)
from morphix_core.validation import check_low_compression_ratio, check_target_exceeds_file_size


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
        self.geometry("560x280")
        self.minsize(520, 360)
        self.resizable(True, True)

        # --- State variables ---
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.size_var = tk.StringVar(value="20")
        self.unit_var = tk.StringVar(value="MB")
        self.device_options = get_available_devices()
        self.device_label_to_key = {label: key for key, label in self.device_options}
        default_device_label = self.device_options[0][1] if self.device_options else "CPU"
        self.device_var = tk.StringVar(value=default_device_label)
        self._is_running = False
        self._auto_output = True
        self._suppress_output_trace = False
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

        self._build_input_row(padding)
        self._build_output_row(padding)
        self._build_target_size_row(padding)
        self._build_device_row(padding)
        self._build_compress_button(padding)
        self._build_tip_row(padding)
        self._build_status_labels(padding)

    def _build_input_row(self, padding):
        """Row 0: input file selector."""
        tk.Label(self, text="Input file").grid(row=0, column=0, sticky="w", **padding)
        self.input_entry = tk.Entry(self, textvariable=self.input_var, width=50)
        self.input_entry.grid(row=0, column=1, sticky="ew", **padding)
        self.browse_input_btn = tk.Button(self, text="Browse", command=self.browse_input)
        self.browse_input_btn.grid(row=0, column=2, **padding)

    def _build_output_row(self, padding):
        """Row 1: output file selector."""
        tk.Label(self, text="Output file").grid(row=1, column=0, sticky="w", **padding)
        self.output_entry = tk.Entry(self, textvariable=self.output_var, width=50)
        self.output_entry.grid(row=1, column=1, sticky="ew", **padding)
        self.browse_output_btn = tk.Button(self, text="Browse", command=self.browse_output)
        self.browse_output_btn.grid(row=1, column=2, **padding)

    def _build_target_size_row(self, padding):
        """Row 2: target size entry and unit selector."""
        tk.Label(self, text="Target size").grid(row=2, column=0, sticky="w", **padding)
        self.size_entry = tk.Entry(self, textvariable=self.size_var, width=10)
        self.size_entry.grid(row=2, column=1, sticky="w", **padding)
        self.unit_menu = tk.OptionMenu(self, self.unit_var, "MB", "GB")
        self.unit_menu.grid(row=2, column=2, sticky="w", **padding)

    def _build_device_row(self, padding):
        """Row 3: device selection dropdown."""
        tk.Label(self, text="Device").grid(row=3, column=0, sticky="w", **padding)
        self.device_menu = tk.OptionMenu(self, self.device_var, *self.device_label_to_key.keys())
        self.device_menu.grid(row=3, column=1, sticky="w", **padding)

    def _build_compress_button(self, padding):
        """Row 4: compress action button."""
        self.compress_btn = tk.Button(self, text="Compress", command=self.run_compress)
        self.compress_btn.grid(row=4, column=0, columnspan=3, pady=12)

    def _build_tip_row(self, padding):
        """Row 5: quality tip message."""
        tk.Label(self, text="Tip:", font=("Segoe UI", 10, "bold")).grid(
            row=5, column=0, sticky="w", **padding
        )
        tk.Message(
            self,
            text="Lower target sizes can look blurry. Ideally set the Target Size to the maximum you're able to.",
            width=420,
        ).grid(row=5, column=1, columnspan=2, sticky="w", **padding)

    def _build_status_labels(self, padding):
        """Rows 6-8: device status, ffmpeg status, and general status labels."""
        self.device_status = tk.Label(self, text="Device: CPU", fg="#444444")
        self.device_status.grid(row=6, column=0, columnspan=3, sticky="w", padx=10, pady=2)

        self.ffmpeg_status = tk.Label(self, text="FFmpeg: path", fg="#444444")
        self.ffmpeg_status.grid(row=7, column=0, columnspan=3, sticky="w", padx=10, pady=2)

        self.status = tk.Label(self, text="", fg="#444444")
        self.status.grid(row=8, column=0, columnspan=3, sticky="w", padx=10, pady=6)

    # -------------------------------------------------------------------------
    # Event handlers — file browsing
    # -------------------------------------------------------------------------

    def browse_input(self):
        path = filedialog.askopenfilename(
            title="Select video",
            filetypes=[("Video files", "*.mp4;*.mov;*.mkv;*.avi;*.webm"), ("All files", "*.*")],
        )
        if path:
            self.input_var.set(path)
            if not self.output_var.get() or self._auto_output:
                self._set_output_auto(path)

    def browse_output(self):
        path = filedialog.asksaveasfilename(
            title="Select output file",
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("All files", "*.*")],
        )
        if path:
            self._set_output_manual(path)

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

        if check_low_compression_ratio(size_value, input_path):
            proceed = messagebox.askokcancel(
                "Morphix — High Compression Warning",
                "The target size is less than 3% of the original file size. "
                "The output will very likely look poor.\n\n"
                "For a viewable result, consider a target of at least 5% of the original file size.\n\n"
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
                self._set_status(
                    f"Pass 1/2: Analyzing video for bitrate data... {pct:.1f}%"
                )
            else:
                self._set_status(
                    f"Pass 2/2: Encoding final output... {pct:.1f}%"
                )

        def worker():
            try:
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
                )
                self._set_status("Done.")
            except Exception as exc:
                self._set_status(f"Failed: {exc}")
                self.after(0, lambda: messagebox.showerror("Morphix", str(exc)))
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
        self.after(0, lambda: self.input_entry.config(state=state))
        self.after(0, lambda: self.output_entry.config(state=state))
        self.after(0, lambda: self.size_entry.config(state=state))
        self.after(0, lambda: self.unit_menu.config(state=state))
        self.after(0, lambda: self.browse_input_btn.config(state=state))
        self.after(0, lambda: self.browse_output_btn.config(state=state))
        self.after(0, lambda: self.device_menu.config(state=state))

    def _refresh_device_label(self):
        # Resolve the selected device and update the UI label.
        device_label, _ = resolve_device_info(self._get_device_preference())
        self.device_status.config(text=f"Device: {device_label}")

    def _refresh_ffmpeg_label(self):
        # Detect whether bundled or PATH ffmpeg binaries are being used.
        ffmpeg_path, _, source = find_ffmpeg_binaries()
        version = get_ffmpeg_version(ffmpeg_path)
        if source == "bundled":
            label = "bundled"
        elif source == "path":
            label = "system PATH"
        else:
            label = "missing"
        self.ffmpeg_status.config(text=f"FFmpeg: {label} (Version: {version})")

    def _get_device_preference(self):
        # Map the selected label to a device key for the core logic.
        return self.device_label_to_key.get(self.device_var.get(), "auto")

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
