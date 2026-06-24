import os
import re
import subprocess
import sys

import ffmpeg

from morphix_core.bitrate import (
    clamp_even,
    compute_scaled_resolution,
    parse_fps,
    target_kbps_for_size_mb,
)
from morphix_core.encoder_selection import (
    OPENH264_WARNING,
    SAFETY_MARGIN,
    select_encoder,
)
from morphix_core.ffmpeg_utils import (
    detect_available_encoders,
    ffprobe_media,
    find_ffmpeg_binaries,
    popen_no_window_kwargs,
)
from morphix_core.gpu_detection import detect_cuda, resolve_device_info


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
        warning_cb=None,
        encoder_override: str | None = None,
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
        self.warning_cb = warning_cb
        self.encoder_override = encoder_override

        # Trim fields.
        self.trim_start = start
        self.trim_end = end
        self.trim_duration = (
            (end - start) if (start is not None and end is not None) else 0.0
        )
        self.trimming = start is not None and end is not None

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
        self.encoder_name = ""
        self.encoder_strategy = ""
        self.encoder_warning = ""

    def execute(self):
        print("Morphix Prototype")
        self._ensure_ffmpeg_available()
        self._resolve_output_path()
        print(f"Proceeding with a compression down to a size of {self.max_mb}mb")

        self._probe_media()
        self._configure_hwaccel()

        # Select encoder based on available encoders and device.
        available = detect_available_encoders(self.ffmpeg_path)
        if self.encoder_override and self.encoder_override != "Auto":
            # Manual override — look up strategy from priority list.
            from morphix_core.encoder_selection import ENCODER_PRIORITY

            strategy_map = {name: strategy for name, strategy, _ in ENCODER_PRIORITY}
            self.encoder_name = self.encoder_override
            self.encoder_strategy = strategy_map.get(
                self.encoder_override, "single_pass_cbr"
            )
        else:
            self.encoder_name, self.encoder_strategy = select_encoder(
                available, self.device_preference, self.detected_device
            )
        print(f"Encoder: {self.encoder_name} (strategy: {self.encoder_strategy})")

        if self.encoder_name == "libopenh264":
            self.encoder_warning = OPENH264_WARNING
            print(self.encoder_warning, file=sys.stderr)
            if self.warning_cb:
                self.warning_cb(self.encoder_warning)

        # Merge trim -ss/-t into input_kwargs when trimming is active.
        if self.trimming:
            self.input_kwargs = {
                **self.input_kwargs,
                "ss": str(self.trim_start),
                "t": str(self.trim_duration),
            }

        self._compute_scaling()

        # If the estimated segment already fits within max_mb, use a single-pass
        # CRF encode (quality-preserving, no bitrate target).
        if self.trimming and self._estimated_segment_mb() <= self.max_mb:
            if self.encoder_name in ("libx264", "h264_nvenc"):
                est = self._estimated_segment_mb()
                print(
                    f"Trimmed segment (~{est:.1f}MB) fits within "
                    f"{self.max_mb}MB — using CRF encode."
                )
                return self._run_crf_encode()

        # Dispatch to the appropriate encoding strategy.
        if self.encoder_strategy == "two_pass":
            return self._encode_two_pass()
        elif self.encoder_strategy == "nvenc_multipass":
            return self._encode_nvenc_multipass()
        elif self.encoder_strategy == "single_pass_cbr":
            return self._encode_single_pass_cbr()

    def _estimated_segment_mb(self) -> float:
        """Estimate the size of the trim segment based on the source bitrate."""
        total_bitrate = int(self.probe["format"].get("bit_rate", 0))
        return (total_bitrate * self.trim_duration) / 8 / 1_000_000

    def _run_crf_encode(self) -> str:
        """Single-pass CRF encode — preserves quality without a bitrate target."""
        crf_input = ffmpeg.input(self.input_path, **self.input_kwargs)
        crf_video = crf_input.video
        if self.scale_filter:
            crf_video = crf_video.filter_(
                "scale", *self.scale_filter.split("=", 1)[1].split(":")
            )
        if self.encoder_name == "h264_nvenc":
            vcodec_kwargs = {"vcodec": "h264_nvenc", "rc": "constqp", "qp": 18}
        else:
            vcodec_kwargs = {"vcodec": "libx264", "preset": "medium", "crf": 18}
        if self.has_audio:
            crf_audio = crf_input.audio
            crf_stream = ffmpeg.output(
                crf_video,
                crf_audio,
                self.output_path,
                **vcodec_kwargs,
                acodec="aac",
                audio_bitrate="128k",
            )
        else:
            crf_stream = ffmpeg.output(
                crf_video,
                self.output_path,
                **vcodec_kwargs,
                an=None,
            )
        self._run_ffmpeg(crf_stream, "CRF")
        return self.output_path

    def _encode_two_pass(self):
        """Two-pass libx264 encode."""
        self._prepare_logs()

        # Pass 1: analysis (video only).
        pass1_input = ffmpeg.input(self.input_path, **self.input_kwargs)
        pass1_video = pass1_input.video
        if self.scale_filter:
            pass1_video = pass1_video.filter_(
                "scale", *self.scale_filter.split("=", 1)[1].split(":")
            )
        self._run_ffmpeg(
            ffmpeg.output(
                pass1_video,
                "NUL",
                vcodec=self.encoder_name,
                preset="medium",
                **{"b:v": f"{self.video_kbps}k"},
                **{"pass": 1},
                **{"passlogfile": self.passlog_path},
                an=None,
                f="mp4",
            ),
            "PASS1",
        )

        # Pass 2: actual encode.
        pass2_input = ffmpeg.input(self.input_path, **self.input_kwargs)
        pass2_video = pass2_input.video
        if self.scale_filter:
            pass2_video = pass2_video.filter_(
                "scale", *self.scale_filter.split("=", 1)[1].split(":")
            )
        if self.has_audio:
            pass2_audio = pass2_input.audio
            pass2_stream = ffmpeg.output(
                pass2_video,
                pass2_audio,
                self.output_path,
                vcodec=self.encoder_name,
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
                vcodec=self.encoder_name,
                preset="medium",
                **{"b:v": f"{self.video_kbps}k"},
                **{"pass": 2},
                **{"passlogfile": self.passlog_path},
                an=None,
            )
        self._run_ffmpeg(pass2_stream, "PASS2")

        self._cleanup_logs()
        return self.output_path

    def _encode_nvenc_multipass(self):
        """NVENC multipass encode — single invocation with internal two-pass."""
        enc_input = ffmpeg.input(self.input_path, **self.input_kwargs)
        enc_video = enc_input.video
        if self.scale_filter:
            enc_video = enc_video.filter_(
                "scale", *self.scale_filter.split("=", 1)[1].split(":")
            )
        output_kwargs = {
            "vcodec": "h264_nvenc",
            "preset": "p4",
            "multipass": "fullres",
            "b:v": f"{self.video_kbps}k",
            "maxrate": f"{self.video_kbps}k",
            "bufsize": f"{self.video_kbps * 2}k",
        }
        if self.has_audio:
            enc_audio = enc_input.audio
            stream = ffmpeg.output(
                enc_video,
                enc_audio,
                self.output_path,
                **output_kwargs,
                acodec="aac",
                audio_bitrate="128k",
            )
        else:
            stream = ffmpeg.output(
                enc_video, self.output_path, **output_kwargs, an=None
            )
        self._run_ffmpeg(stream, "NVENC")
        return self.output_path

    def _encode_single_pass_cbr(self):
        """Single-pass CBR encode with safety margin. Retries once if over limit."""
        safe_kbps = int(self.video_kbps * SAFETY_MARGIN)
        output = self._run_single_pass(safe_kbps)

        # Check if output exceeds target; retry with further reduction.
        output_mb = os.path.getsize(output) / 1_000_000
        if output_mb > self.max_mb:
            reduction = self.max_mb / output_mb * 0.95
            retry_kbps = int(safe_kbps * reduction)
            print(
                f"Output {output_mb:.1f}MB exceeds "
                f"{self.max_mb}MB — retrying at {retry_kbps}k"
            )
            output = self._run_single_pass(retry_kbps)

        return output

    def _run_single_pass(self, kbps):
        """Execute a single-pass encode at the given bitrate."""
        enc_input = ffmpeg.input(self.input_path, **self.input_kwargs)
        enc_video = enc_input.video
        if self.scale_filter:
            enc_video = enc_video.filter_(
                "scale", *self.scale_filter.split("=", 1)[1].split(":")
            )
        output_kwargs = {
            "vcodec": self.encoder_name,
            "b:v": f"{kbps}k",
        }
        if self.has_audio:
            enc_audio = enc_input.audio
            stream = ffmpeg.output(
                enc_video,
                enc_audio,
                self.output_path,
                **output_kwargs,
                acodec="aac",
                audio_bitrate="128k",
            )
        else:
            stream = ffmpeg.output(
                enc_video, self.output_path, **output_kwargs, an=None
            )
        self._run_ffmpeg(stream, "ENCODE")
        return self.output_path

    def _resolve_output_path(self):
        # Default output path: original filename + "_{size}mb".
        base_name, ext = os.path.splitext(os.path.basename(self.input_path))
        if not ext:
            ext = ".mp4"
        if self.output_path:
            return
        size_label = f"{self.max_mb:g}"
        self.output_path = os.path.join(
            self.input_dir, f"{base_name}_{size_label}mb{ext}"
        )

    def _ensure_ffmpeg_available(self):
        # Fail early with a clear error if ffmpeg/ffprobe are missing.
        if not self.ffmpeg_path or not self.ffprobe_path:
            raise FileNotFoundError(
                "ffmpeg/ffprobe not found. Place them in a "
                "'ffmpeg' folder next to the app "
                "or install them and add to PATH."
            )

    def _probe_media(self):
        # Use ffprobe to fetch duration and stream metadata without spawning a console.
        self.probe = ffprobe_media(self.input_path, self.ffprobe_path)
        full_duration = float(self.probe["format"]["duration"])
        # Use trim duration for bitrate calc and progress when trimming.
        self.duration = self.trim_duration if self.trimming else full_duration
        self.video_kbps = target_kbps_for_size_mb(
            self.max_mb, self.duration, audio_kbps=128
        )
        self.video_bps = self.video_kbps * 1000
        self.has_audio = any(
            stream.get("codec_type") == "audio"
            for stream in self.probe.get("streams", [])
        )

    def _configure_hwaccel(self):
        # Resolve the requested device preference to a label and hwaccel string.
        self.device_label, hwaccel = resolve_device_info(self.device_preference)
        self.detected_device = None
        if "NVIDIA" in self.device_label:
            self.detected_device = "nvidia"
        if self.device_preference == "nvidia" and not detect_cuda():
            print("NVIDIA GPU requested but not available; falling back to CPU.")
        print(f"Compression device: {self.device_label} (hwaccel={hwaccel or 'none'})")
        self.input_kwargs = {"hwaccel": hwaccel} if hwaccel else {}

    def _compute_scaling(self):
        # Fetch video stream info for auto-scaling decisions.
        vstream = next(
            (
                s
                for s in self.probe.get("streams", [])
                if s.get("codec_type") == "video"
            ),
            None,
        )
        width = int(vstream.get("width", 0)) if vstream else 0
        height = int(vstream.get("height", 0)) if vstream else 0
        fps = (
            parse_fps(vstream.get("avg_frame_rate") or vstream.get("r_frame_rate"))
            if vstream
            else None
        )

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
            scaled = compute_scaled_resolution(
                width, height, fps, self.video_bps, target_bpp, min_height=480
            )
            if scaled:
                scale_filter = f"scale={scaled[0]}:{scaled[1]}"
                w, h = scaled[0], scaled[1]
                print(
                    f"Auto-scaling to {w}x{h} for "
                    f"quality '{self.quality}'."
                )

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
            raise RuntimeError(self._parse_ffmpeg_error(exc)) from exc

    @staticmethod
    def _parse_ffmpeg_error(exc):
        """Extract a user-friendly message from an ffmpeg error."""
        stderr = exc.stderr or b""
        if b"Driver does not support the required nvenc API" in stderr:
            return (
                "NVIDIA driver is too old for this ffmpeg build. "
                "Update your GPU drivers or select a different encoder."
            )
        if b"No NVENC capable devices found" in stderr:
            return "No NVIDIA GPU found. Select a different device or encoder."
        if b"Cannot load" in stderr and b"nvcuda.dll" in stderr:
            return "NVIDIA CUDA drivers not found. Update your GPU drivers."
        # Unknown error — extract first meaningful line.
        for line in stderr.decode(errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith(
                (
                    "frame=",
                    "fps=",
                    "stream_",
                    "bitrate=",
                    "total_size=",
                    "out_time",
                    "dup_frames",
                    "drop_frames",
                    "speed=",
                    "progress=",
                    "Qavg:",
                    "Press [q]",
                )
            ):
                if "Error" in line or "error" in line or "failed" in line:
                    return f"FFmpeg error: {line}"
        return "An unknown FFmpeg error has occurred. Check the error log for details."

    def _run_ffmpeg_with_progress(self, stream, phase):
        # Enable progress reporting and parse out_time_ms from stderr.
        bar = self._maybe_create_progress_bar(phase)
        stream = stream.global_args("-progress", "pipe:2", "-nostats")
        cmd = ffmpeg.compile(
            stream, cmd=self.ffmpeg_path, overwrite_output=self.overwrite
        )
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
            raise ffmpeg.Error("ffmpeg", None, b"".join(stderr_lines))

    def _run_ffmpeg_simple(self, stream):
        # Run without progress parsing; optionally suppress logs and console windows.
        cmd = ffmpeg.compile(
            stream, cmd=self.ffmpeg_path, overwrite_output=self.overwrite
        )
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
            raise ffmpeg.Error("ffmpeg", None, err_bytes)

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
        if not self.log_dir:
            self.log_dir = os.path.join(self.input_dir, ".output")
            os.makedirs(self.log_dir, exist_ok=True)
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
        for filepath in glob.glob(
            os.path.join(self.log_dir, passlog_base + "*.log")
        ) + glob.glob(os.path.join(self.log_dir, passlog_base + "*.log.mbtree")):
            try:
                os.remove(filepath)
            except FileNotFoundError:
                pass

        try:
            if not os.listdir(self.log_dir):
                os.rmdir(self.log_dir)
        except OSError:
            pass
