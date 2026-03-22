import json
import os
import re
import shutil
import subprocess
import sys

import ffmpeg


def target_kbps_for_size_mb(size_mb: float, duration_s: float, audio_kbps: int) -> int:
    return max(int((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps, 1)


def parse_fps(rate_text):
    # Parse "num/den" or float fps strings from ffprobe.
    if not rate_text or rate_text == "0/0":
        return None
    if "/" in rate_text:
        num, den = rate_text.split("/", 1)
        try:
            return float(num) / float(den)
        except ValueError:
            return None
    try:
        return float(rate_text)
    except ValueError:
        return None


def clamp_even(value):
    # Ensure even dimensions for H.264 compatibility.
    value = int(round(value))
    return value if value % 2 == 0 else value - 1


def compute_scaled_resolution(width, height, fps, video_bps, target_bpp, min_height=480):
    # Determine a scaled resolution based on target bits-per-pixel-per-frame.
    if not all([width, height, fps, video_bps]):
        return None
    current_bpp = video_bps / (fps * width * height)
    if current_bpp >= target_bpp:
        return None
    target_pixels = video_bps / (fps * target_bpp)
    scale = (target_pixels / (width * height)) ** 0.5
    if scale >= 1.0:
        return None
    new_w = clamp_even(width * scale)
    new_h = clamp_even(height * scale)
    if new_h < min_height:
        # Enforce minimum height while keeping aspect ratio.
        new_h = clamp_even(min_height)
        new_w = clamp_even(new_h * (width / height))
    if new_w < 2 or new_h < 2:
        return None
    return new_w, new_h


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
        return first_line[len(prefix) :].split(" ", 1)[0]
    return "unknown"


def detect_cuda():
    # Detect CUDA capability using nvidia-smi if present.
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            check=False,
            capture_output=True,
            text=True,
            **popen_no_window_kwargs(),
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def detect_amd():
    # Detect AMD GPU via rocm-smi (Linux) or WMI query (Windows).
    # Try rocm-smi first (Linux/ROCm environments).
    if shutil.which("rocm-smi") is not None:
        try:
            result = subprocess.run(
                ["rocm-smi"],
                check=False,
                capture_output=True,
                text=True,
                **popen_no_window_kwargs(),
            )
            if result.returncode == 0:
                return True
        except OSError:
            pass

    # Fall back to WMI query on Windows.
    if os.name == "nt":
        try:
            import wmi  # type: ignore
            c = wmi.WMI()
            for adapter in c.Win32_VideoController():
                name = (adapter.Name or "").upper()
                if "AMD" in name or "RADEON" in name or "ATI" in name:
                    return True
        except Exception:
            pass

    return False


def detect_intel():
    # Detect Intel GPU via WMI query (Windows) or registry check.
    if os.name == "nt":
        # Try WMI first.
        try:
            import wmi  # type: ignore
            c = wmi.WMI()
            for adapter in c.Win32_VideoController():
                name = (adapter.Name or "").upper()
                if "INTEL" in name:
                    return True
        except Exception:
            pass

        # Fall back to registry query.
        try:
            import winreg  # type: ignore
            key_path = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base_key:
                i = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(base_key, i)
                        with winreg.OpenKey(base_key, sub_name) as sub_key:
                            try:
                                desc, _ = winreg.QueryValueEx(sub_key, "DriverDesc")
                                if "INTEL" in str(desc).upper():
                                    return True
                            except FileNotFoundError:
                                pass
                        i += 1
                    except OSError:
                        break
        except Exception:
            pass

    return False


def detect_device_info():
    # Return a user-friendly device label and a preferred hwaccel string.
    # Try each vendor in priority order; catch all exceptions per vendor.
    try:
        if detect_cuda():
            return "NVIDIA GPU", "cuda"
    except Exception:
        pass

    try:
        if detect_amd():
            return "AMD GPU", "amf"
    except Exception:
        pass

    try:
        if detect_intel():
            return "Intel GPU", "qsv"
    except Exception:
        pass

    return "CPU", None


def get_available_devices():
    # Return available device options in preferred order, GPU-first, CPU last.
    devices = []

    try:
        if detect_cuda():
            devices.append(("nvidia", "NVIDIA GPU"))
    except Exception:
        pass

    try:
        if detect_amd():
            devices.append(("amd", "AMD GPU"))
    except Exception:
        pass

    try:
        if detect_intel():
            devices.append(("intel", "Intel GPU"))
    except Exception:
        pass

    devices.append(("cpu", "CPU"))
    return devices


def resolve_device_info(preference):
    # Resolve a device preference into a label and hwaccel string.
    if preference == "cpu":
        return "CPU", None
    if preference == "nvidia":
        try:
            if detect_cuda():
                return "NVIDIA GPU", "cuda"
        except Exception:
            pass
        return "CPU", None
    if preference == "amd":
        try:
            if detect_amd():
                return "AMD GPU", "amf"
        except Exception:
            pass
        return "CPU", None
    if preference == "intel":
        try:
            if detect_intel():
                return "Intel GPU", "qsv"
        except Exception:
            pass
        return "CPU", None
    # "auto" or unknown preference: use best available device.
    return detect_device_info()


def ffprobe_media(path, ffprobe_path):
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


class RunContext:
    # Encapsulates the state and helpers for a single compression run.
    def __init__(
        self,
        input_path,
        max_mb,
        output_path=None,
        quality="medium",
        resolution=None,
        device_preference="auto",
        overwrite=True,
        disable_logs=True,
        progress=True,
        progress_cb=None,
    ):
        self.input_path = os.path.abspath(input_path)
        self.max_mb = max_mb
        self.output_path = output_path
        self.quality = quality
        self.resolution = resolution
        self.device_preference = device_preference
        self.overwrite = overwrite
        self.disable_logs = disable_logs
        self.progress = progress
        self.progress_cb = progress_cb

        # Derived values populated during execution.
        self.input_dir = os.path.dirname(self.input_path)
        self.duration = 0.0
        self.video_kbps = 0
        self.video_bps = 0
        self.probe = {}
        self.scale_filter = None
        self.passlog_path = None
        self.log_dir = None
        self.input_kwargs = {}
        self.device_label = "CPU"
        self.ffmpeg_path, self.ffprobe_path, self.ffmpeg_source = find_ffmpeg_binaries()
        self.has_audio = False

    def execute(self):
        print("Morphix Prototype")
        self._ensure_ffmpeg_available()
        self._resolve_output_path()
        print(f"Proceeding with a compression down to a size of {self.max_mb}mb")

        self._probe_media()
        self._configure_hwaccel()
        self._compute_scaling()
        self._prepare_logs()

        # Pass 1: analysis (video only).
        pass1_input = ffmpeg.input(self.input_path, **self.input_kwargs)
        pass1_video = pass1_input.video
        if self.scale_filter:
            pass1_video = pass1_video.filter_("scale", *self.scale_filter.split("=", 1)[1].split(":"))
        self._run_ffmpeg(
            ffmpeg.output(
                pass1_video,
                "NUL",
                vcodec="libx264",
                preset="medium",
                **{"b:v": f"{self.video_kbps}k"},
                **{"pass": 1},
                **{"passlogfile": self.passlog_path},
                an=None,
                f="mp4"),
            "PASS1",
        )

        # Pass 2: actual encode.
        pass2_input = ffmpeg.input(self.input_path, **self.input_kwargs)
        pass2_video = pass2_input.video
        if self.scale_filter:
            pass2_video = pass2_video.filter_("scale", *self.scale_filter.split("=", 1)[1].split(":"))
        if self.has_audio:
            pass2_audio = pass2_input.audio
            pass2_stream = ffmpeg.output(
                pass2_video,
                pass2_audio,
                self.output_path,
                vcodec="libx264",
                preset="medium",
                **{"b:v": f"{self.video_kbps}k"},
                **{"pass": 2},
                **{"passlogfile": self.passlog_path},
                acodec="aac",
                audio_bitrate="128k",
            )
        else:
            pass2_stream = ffmpeg.output(
                pass2_video,
                self.output_path,
                vcodec="libx264",
                preset="medium",
                **{"b:v": f"{self.video_kbps}k"},
                **{"pass": 2},
                **{"passlogfile": self.passlog_path},
                an=None,
            )
        self._run_ffmpeg(pass2_stream, "PASS2")

        self._cleanup_logs()
        return self.output_path

    def _resolve_output_path(self):
        # Default output path: original filename + "_{size}mb".
        base_name, ext = os.path.splitext(os.path.basename(self.input_path))
        if not ext:
            ext = ".mp4"
        if self.output_path:
            return
        size_label = f"{self.max_mb:g}"
        self.output_path = os.path.join(self.input_dir, f"{base_name}_{size_label}mb{ext}")

    def _ensure_ffmpeg_available(self):
        # Fail early with a clear error if ffmpeg/ffprobe are missing.
        if not self.ffmpeg_path or not self.ffprobe_path:
            raise FileNotFoundError(
                "ffmpeg/ffprobe not found. Place them in a 'ffmpeg' folder next to the app "
                "or install them and add to PATH."
            )

    def _probe_media(self):
        # Use ffprobe to fetch duration and stream metadata without spawning a console.
        self.probe = ffprobe_media(self.input_path, self.ffprobe_path)
        self.duration = float(self.probe["format"]["duration"])
        self.video_kbps = target_kbps_for_size_mb(self.max_mb, self.duration, audio_kbps=128)
        self.video_bps = self.video_kbps * 1000
        self.has_audio = any(
            stream.get("codec_type") == "audio" for stream in self.probe.get("streams", [])
        )

    def _configure_hwaccel(self):
        # Resolve the requested device preference to a label and hwaccel string.
        self.device_label, hwaccel = resolve_device_info(self.device_preference)
        if self.device_preference == "nvidia" and not detect_cuda():
            print("NVIDIA GPU requested but not available; falling back to CPU.")
        print(f"Compression device: {self.device_label} (hwaccel={hwaccel or 'none'})")
        self.input_kwargs = {"hwaccel": hwaccel} if hwaccel else {}

    def _compute_scaling(self):
        # Fetch video stream info for auto-scaling decisions.
        vstream = next((s for s in self.probe.get("streams", []) if s.get("codec_type") == "video"), None)
        width = int(vstream.get("width", 0)) if vstream else 0
        height = int(vstream.get("height", 0)) if vstream else 0
        fps = parse_fps(vstream.get("avg_frame_rate") or vstream.get("r_frame_rate")) if vstream else None

        # Decide whether to apply a scale filter.
        scale_filter = None
        if self.resolution:
            # Manual override takes precedence.
            if "x" in self.resolution:
                w_str, h_str = self.resolution.lower().split("x", 1)
                try:
                    res_w = clamp_even(int(w_str))
                    res_h = clamp_even(int(h_str))
                    if res_w >= 2 and res_h >= 2:
                        scale_filter = f"scale={res_w}:{res_h}"
                except ValueError:
                    pass
        else:
            # Auto-scale based on bitrate-derived bpp thresholds.
            bpp_targets = {"low": 0.05, "medium": 0.07, "high": 0.10}
            target_bpp = bpp_targets.get(self.quality, 0.07)
            scaled = compute_scaled_resolution(width, height, fps, self.video_bps, target_bpp, min_height=480)
            if scaled:
                scale_filter = f"scale={scaled[0]}:{scaled[1]}"
                print(f"Auto-scaling to {scaled[0]}x{scaled[1]} for quality '{self.quality}'.")

        self.scale_filter = scale_filter

    def _prepare_logs(self):
        # Create the log directory and pass log path used for two-pass encoding.
        self.log_dir = os.path.join(self.input_dir, ".output")
        os.makedirs(self.log_dir, exist_ok=True)
        self.passlog_path = os.path.join(self.log_dir, "ffmpeg2pass")

    def _render_progress(self, current_seconds, bar, phase):
        # Convert out_time_ms to a 0-100% progress update.
        if self.duration <= 0:
            return
        pct = min(max(current_seconds / self.duration, 0.0), 1.0) * 100.0
        if self.progress_cb:
            self.progress_cb(pct, phase)
            return
        if bar is None:
            sys.stdout.write(f"\rProgress: {pct:5.1f}%")
            sys.stdout.flush()
        else:
            bar.n = int(pct * 10)
            bar.refresh()

    def _run_ffmpeg(self, stream, phase):
        # Execute ffmpeg with optional progress parsing and suppressed console windows.
        try:
            if self.progress:
                self._run_ffmpeg_with_progress(stream, phase)
            else:
                self._run_ffmpeg_simple(stream)
        except ffmpeg.Error as exc:
            self._write_ffmpeg_error(exc)
            raise

    def _run_ffmpeg_with_progress(self, stream, phase):
        # Enable progress reporting and parse out_time_ms from stderr.
        bar = self._maybe_create_progress_bar(phase)
        stream = stream.global_args("-progress", "pipe:2", "-nostats")
        cmd = ffmpeg.compile(stream, cmd=self.ffmpeg_path, overwrite_output=self.overwrite)
        stderr_lines = []
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_no_window_kwargs(),
        )
        for current_seconds, line in self._iter_progress_seconds(process.stderr):
            if line:
                stderr_lines.append(line)
            if current_seconds is not None:
                self._render_progress(current_seconds, bar, phase)
        process.wait()
        self._finish_progress_bar(bar)
        if process.returncode != 0:
            raise ffmpeg.Error("ffmpeg", b"".join(stderr_lines), None)

    def _run_ffmpeg_simple(self, stream):
        # Run without progress parsing; optionally suppress logs and console windows.
        cmd = ffmpeg.compile(stream, cmd=self.ffmpeg_path, overwrite_output=self.overwrite)
        stderr_target = subprocess.DEVNULL if self.disable_logs else subprocess.PIPE
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL if self.disable_logs else None,
            stderr=stderr_target,
            **popen_no_window_kwargs(),
        )
        process.wait()
        if process.returncode != 0:
            err_bytes = None
            if process.stderr is not None:
                err_bytes = process.stderr.read()
            raise ffmpeg.Error("ffmpeg", err_bytes, None)

    def _maybe_create_progress_bar(self, phase):
        # Create a tqdm bar only for CLI mode (no progress callback).
        if self.progress_cb is not None:
            return None
        try:
            from tqdm import tqdm
        except ImportError:
            return None
        if self.duration <= 0:
            return None
        return tqdm(total=1000, unit="permille", leave=True, desc=phase)

    def _iter_progress_seconds(self, stderr_stream):
        # Yield elapsed output time in seconds, along with raw stderr lines.
        time_re = re.compile(r"out_time_ms=(\d+)")
        while True:
            line = stderr_stream.readline()
            if not line:
                break
            text = line.decode(errors="ignore").strip()
            match = time_re.search(text)
            if match:
                yield float(match.group(1)) / 1_000_000.0, line
            else:
                yield None, line

    def _finish_progress_bar(self, bar):
        # Close the progress bar or emit a trailing newline for stdout mode.
        if bar is not None:
            bar.close()
        elif self.progress_cb is None:
            sys.stdout.write("\n")

    def _write_ffmpeg_error(self, exc):
        # Persist ffmpeg stderr to a log file for troubleshooting.
        err_path = os.path.join(self.log_dir, "ffmpeg-error.log")
        with open(err_path, "wb") as f:
            if exc.stderr:
                f.write(exc.stderr)
            else:
                f.write(b"No stderr captured from ffmpeg.\n")
        print(f"FFmpeg failed. See: {err_path}")

    def _cleanup_logs(self):
        # Remove two-pass log files and delete the log directory if empty.
        for suffix in (".log", ".log.mbtree"):
            try:
                os.remove(self.passlog_path + suffix)
            except FileNotFoundError:
                pass

        try:
            if not os.listdir(self.log_dir):
                os.rmdir(self.log_dir)
        except OSError:
            pass


def run(
    input_path,
    max_mb,
    output_path=None,
    quality="medium",
    resolution=None,
    device_preference="auto",
    overwrite=True,
    disable_logs=True,
    progress=True,
    progress_cb=None,
):
    # Backwards-compatible entry point used by CLI and UI.
    ctx = RunContext(
        input_path,
        max_mb,
        output_path=output_path,
        quality=quality,
        resolution=resolution,
        device_preference=device_preference,
        overwrite=overwrite,
        disable_logs=disable_logs,
        progress=progress,
        progress_cb=progress_cb,
    )
    return ctx.execute()
