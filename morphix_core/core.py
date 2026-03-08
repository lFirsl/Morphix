import json
import os
import re
import shutil
import subprocess
import sys

import ffmpeg


def target_kbps_for_size_mb(size_mb, duration_s, audio_kbps=128):
    target_bytes = size_mb * 1_000_000  # MB
    # Convert target size to kbps: bytes -> bits -> bps -> kbps.
    total_kbps = (target_bytes * 8) / duration_s / 1000
    video_kbps = max(total_kbps - audio_kbps, 1)
    return int(video_kbps)


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

    return "ffmpeg", "ffprobe", "path"


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


def detect_device_info():
    # Return a user-friendly device label and a preferred hwaccel string.
    if detect_cuda():
        return "NVIDIA GPU", "cuda"
    return "CPU", None


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

    def execute(self):
        print("Morphix Prototype")
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
        pass2_audio = pass2_input.audio
        if self.scale_filter:
            pass2_video = pass2_video.filter_("scale", *self.scale_filter.split("=", 1)[1].split(":"))
        self._run_ffmpeg(
            ffmpeg.output(
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
            ),
            "PASS2",
        )

        self._cleanup_logs()
        return self.output_path

    def _resolve_output_path(self):
        # Default output path: original filename + "_{size}mb".
        base_name, ext = os.path.splitext(os.path.basename(self.input_path))
        if not ext:
            ext = ".mp4"
        if self.output_path:
            return
        size_label = str(self.max_mb).rstrip("0").rstrip(".")
        self.output_path = os.path.join(self.input_dir, f"{base_name}_{size_label}mb{ext}")

    def _probe_media(self):
        # Use ffprobe to fetch duration and stream metadata without spawning a console.
        self.probe = ffprobe_media(self.input_path, self.ffprobe_path)
        self.duration = float(self.probe["format"]["duration"])
        self.video_kbps = target_kbps_for_size_mb(self.max_mb, self.duration, audio_kbps=128)
        self.video_bps = self.video_kbps * 1000

    def _configure_hwaccel(self):
        # Detect a GPU vendor and choose a matching decode accelerator if possible.
        self.device_label, hwaccel = detect_device_info()
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
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_no_window_kwargs(),
        )
        for current_seconds in self._iter_progress_seconds(process.stderr):
            self._render_progress(current_seconds, bar, phase)
        process.wait()
        self._finish_progress_bar(bar)
        if process.returncode != 0:
            raise ffmpeg.Error("ffmpeg", process.stderr.read(), None)

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
        # Yield elapsed output time in seconds from ffmpeg progress lines.
        time_re = re.compile(r"out_time_ms=(\d+)")
        while True:
            line = stderr_stream.readline()
            if not line:
                break
            text = line.decode(errors="ignore").strip()
            match = time_re.search(text)
            if match:
                yield float(match.group(1)) / 1_000_000.0

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
        overwrite=overwrite,
        disable_logs=disable_logs,
        progress=progress,
        progress_cb=progress_cb,
    )
    return ctx.execute()
