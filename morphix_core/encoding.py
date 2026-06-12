import os
import re
import subprocess
import sys

import ffmpeg

from morphix_core.ffmpeg_utils import find_ffmpeg_binaries, ffprobe_media, popen_no_window_kwargs
from morphix_core.gpu_detection import detect_cuda, resolve_device_info
from morphix_core.bitrate import target_kbps_for_size_mb, compute_scaled_resolution, clamp_even, parse_fps


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
        start: float | None = None,
        end: float | None = None,
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

        # Trim fields.
        self.trim_start = start
        self.trim_end = end
        self.trim_duration = (end - start) if (start is not None and end is not None) else 0.0
        self.work_path: str | None = None       # Points at original or temp trimmed file.
        self.trimming = False                    # True when trim is active.
        self.trim_temp_path: str | None = None   # Path to temp trimmed file, cleaned up at end.
        self._trim_kwargs = {}                   # ss/t kwargs merged into input_kwargs.

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

        # Probe the original for duration and metadata.
        self._probe_media()

        # Trim pre-phase (if active): stream-copy to temp, measure, decide path.
        trim_result = self._stream_copy_trim()
        if trim_result is not None:
            # Case 3a: temp file fits within target — use directly.
            print(f"Trimmed clip ({self.trim_duration:.1f}s) fits within {self.max_mb}MB target.")
            return trim_result

        # Cases 3b + normal (no trim): two-pass encode path.
        if self.work_path is None:
            self.work_path = self.input_path  # Normal case: use original.

        # Re-probe the working file for stream metadata (may be temp file).
        self._probe_media()
        self._configure_hwaccel()
        # Merge trim ss/t into input_kwargs if trimming is active.
        if self.trimming and self._trim_kwargs:
            self.input_kwargs = {**self.input_kwargs, **self._trim_kwargs}
        self._compute_scaling()
        self._prepare_logs()

        # Pass 1: analysis (video only) on work_path.
        pass1_input = ffmpeg.input(self.work_path, **self.input_kwargs)
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

        # Pass 2: actual encode on work_path.
        pass2_input = ffmpeg.input(self.work_path, **self.input_kwargs)
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

        # Clean up temp file if still present (case 3b path).
        if self.trim_temp_path and os.path.isfile(self.trim_temp_path):
            os.remove(self.trim_temp_path)
            self.trim_temp_path = None

        self._cleanup_logs()
        return self.output_path

    def _stream_copy_trim(self) -> str | None:
        """Stream-copy a trimmed segment to a temp file.

        Returns the final output_path if the temp file fits within max_mb (case 3a).
        Sets self.work_path / self.trim_temp_path when encoding is needed (case 3b).
        Returns None when trimming is not active.
        """
        if not (self.trim_start is not None and self.trim_end is not None):
            return None

        self.trimming = True
        self._trim_kwargs = {"ss": str(self.trim_start), "t": str(self.trim_duration)}

        # Temp file in the same directory as the original input.
        base_name, _ = os.path.splitext(os.path.basename(self.input_path))
        self.trim_temp_path = os.path.join(self.input_dir, f"{base_name}_trimmed.mp4")

        if not self.ffmpeg_path or not os.path.isfile(self.ffmpeg_path):
            raise FileNotFoundError(f"ffmpeg not found at {self.ffmpeg_path}")

        cmd = [
            self.ffmpeg_path,
            "-ss", str(self.trim_start),
            "-i", self.input_path,
            "-c:v", "copy",
            "-c:a", "copy",
            "-t", str(self.trim_duration),
            "-f", "mp4",
            self.trim_temp_path,
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_no_window_kwargs(),
        )
        _, stderr = process.communicate()
        if process.returncode != 0:
            raise RuntimeError(f"Stream-copy trim failed: {stderr.decode(errors='replace')}")

        # Measure real output size against target.
        temp_size_mb = os.path.getsize(self.trim_temp_path) / 1_000_000.0
        if temp_size_mb <= self.max_mb:
            # Case 3a: fits — copy to output and remove temp.
            import shutil
            shutil.copy2(self.trim_temp_path, self.output_path)
            os.remove(self.trim_temp_path)
            self.trim_temp_path = None
            return self.output_path

        # Case 3b: does not fit — encode from the temp file.
        self.work_path = self.trim_temp_path
        return None

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
        # When trimming is active, use the trimmed duration for bitrate calculation
        # since we are encoding only that segment, not the full video.
        duration_for_bitrate = self.trim_duration if self.trimming else self.duration
        self.video_kbps = target_kbps_for_size_mb(self.max_mb, duration_for_bitrate, audio_kbps=128)
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
        # ffmpeg may append a stream index (e.g. "-0") before the extension,
        # so we glob for all matching passlog files rather than exact names.
        import glob
        passlog_base = os.path.basename(self.passlog_path)
        for filepath in glob.glob(os.path.join(self.log_dir, passlog_base + "*.log")) + \
                        glob.glob(os.path.join(self.log_dir, passlog_base + "*.log.mbtree")):
            try:
                os.remove(filepath)
            except FileNotFoundError:
                pass

        try:
            if not os.listdir(self.log_dir):
                os.rmdir(self.log_dir)
        except OSError:
            pass
