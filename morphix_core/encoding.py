"""Encoding engine — RunContext executes a single compression run."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from pathlib import Path

import ffmpeg

from morphix_core.bitrate import (
    compute_scaled_resolution,
    parse_fps,
    target_kbps_for_size_mb,
)
from morphix_core.config import CompressConfig, parse_resolution
from morphix_core.encoder_selection import (
    ENCODER_PRIORITY,
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

logger = logging.getLogger("morphix")


class RunContext:
    """Executes a single compression run based on a CompressConfig.

    All user-facing parameters come from the frozen CompressConfig.
    This class holds only mutable runtime state that evolves during execution.
    """

    def __init__(self, config: CompressConfig):
        self.config = config

        # Derived values populated during execution.
        self.input_dir = config.input_path.parent
        self.output_path: str | None = (
            str(config.output_path) if config.output_path else None
        )
        self.duration = 0.0
        self.video_kbps = 0
        self.video_bps = 0
        self.probe: dict = {}
        self.scale: tuple[int, int] | None = None
        self.passlog_path: Path | None = None
        self.log_dir: Path | None = None
        self.input_kwargs: dict = {}
        self.device_label = "CPU"
        self.detected_device: str | None = None
        self.ffmpeg_path, self.ffprobe_path, self.ffmpeg_source = (
            find_ffmpeg_binaries()
        )
        self.has_audio = False
        self.encoder_name = ""
        self.encoder_strategy = ""
        self.encoder_warning = ""

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def execute(self) -> str:
        """Run the full compression pipeline. Returns the output file path."""
        logger.info("Morphix Prototype")
        self._ensure_ffmpeg_available()
        self._resolve_output_path()
        logger.info(
            "Proceeding with a compression down to a size of %smb",
            self.config.max_mb,
        )

        self._probe_media()
        self._configure_hwaccel()
        self._select_encoder()

        # Merge trim -ss/-t into input_kwargs when trimming is active.
        if self.config.trimming:
            self.input_kwargs = {
                **self.input_kwargs,
                "ss": str(self.config.start),
                "t": str(self.config.trim_duration),
            }

        self._compute_scaling()

        # If the estimated segment already fits within max_mb, use a single-pass
        # CRF encode (quality-preserving, no bitrate target).
        if self.config.trimming and self._estimated_segment_mb() <= self.config.max_mb:
            if self.encoder_name in ("libx264", "h264_nvenc"):
                est = self._estimated_segment_mb()
                logger.info(
                    "Trimmed segment (~%.1fMB) fits within %sMB"
                    " — using CRF encode.",
                    est,
                    self.config.max_mb,
                )
                return self._run_crf_encode()

        # Dispatch to the appropriate encoding strategy.
        strategies = {
            "two_pass": self._encode_two_pass,
            "nvenc_multipass": self._encode_nvenc_multipass,
            "single_pass_cbr": self._encode_single_pass_cbr,
        }
        return strategies[self.encoder_strategy]()

    # -------------------------------------------------------------------------
    # Stream-building helpers (eliminate repeated input/scale/audio pattern)
    # -------------------------------------------------------------------------

    def _build_output_stream(
        self, output_path: str, **video_kwargs
    ) -> ffmpeg.Stream:
        """Build an ffmpeg output stream with optional scale and audio.

        Handles the common pattern: input → video → scale → output (with or
        without audio). Used by all encode methods except Pass 1.
        """
        inp = ffmpeg.input(str(self.config.input_path), **self.input_kwargs)
        video = inp.video
        if self.scale:
            video = video.filter_("scale", self.scale[0], self.scale[1])
        if self.has_audio:
            audio = inp.audio
            return ffmpeg.output(
                video,
                audio,
                output_path,
                **video_kwargs,
                acodec="aac",
                audio_bitrate="128k",
            )
        return ffmpeg.output(video, output_path, **video_kwargs, an=None)

    def _build_analysis_stream(self, **video_kwargs) -> ffmpeg.Stream:
        """Build a Pass 1 analysis stream (video only, output to NUL)."""
        inp = ffmpeg.input(str(self.config.input_path), **self.input_kwargs)
        video = inp.video
        if self.scale:
            video = video.filter_("scale", self.scale[0], self.scale[1])
        return ffmpeg.output(video, "NUL", **video_kwargs, an=None, f="mp4")

    # -------------------------------------------------------------------------
    # Encoding strategies
    # -------------------------------------------------------------------------

    def _estimated_segment_mb(self) -> float:
        """Estimate the size of the trim segment based on the source bitrate."""
        total_bitrate = int(self.probe["format"].get("bit_rate", 0))
        return (total_bitrate * self.config.trim_duration) / 8 / 1_000_000

    def _run_crf_encode(self) -> str:
        """Single-pass CRF encode — preserves quality without a bitrate target."""
        if self.encoder_name == "h264_nvenc":
            vcodec_kwargs = {"vcodec": "h264_nvenc", "rc": "constqp", "qp": 18}
        else:
            vcodec_kwargs = {"vcodec": "libx264", "preset": "medium", "crf": 18}
        stream = self._build_output_stream(self.output_path, **vcodec_kwargs)
        self._run_ffmpeg(stream, "CRF")
        return self.output_path

    def _encode_two_pass(self) -> str:
        """Two-pass libx264 encode."""
        self._prepare_logs()

        # Pass 1: analysis (video only).
        self._run_ffmpeg(
            self._build_analysis_stream(
                vcodec=self.encoder_name,
                preset="medium",
                **{"b:v": f"{self.video_kbps}k"},
                **{"pass": 1},
                **{"passlogfile": str(self.passlog_path)},
            ),
            "PASS1",
        )

        # Pass 2: actual encode.
        stream = self._build_output_stream(
            self.output_path,
            vcodec=self.encoder_name,
            preset="medium",
            **{"b:v": f"{self.video_kbps}k"},
            **{"pass": 2},
            **{"passlogfile": str(self.passlog_path)},
        )
        self._run_ffmpeg(stream, "PASS2")

        self._cleanup_logs()
        return self.output_path

    def _encode_nvenc_multipass(self) -> str:
        """NVENC multipass encode — single invocation with internal two-pass."""
        stream = self._build_output_stream(
            self.output_path,
            vcodec="h264_nvenc",
            preset="p4",
            multipass="fullres",
            **{"b:v": f"{self.video_kbps}k"},
            maxrate=f"{self.video_kbps}k",
            bufsize=f"{self.video_kbps * 2}k",
        )
        self._run_ffmpeg(stream, "NVENC")
        return self.output_path

    def _encode_single_pass_cbr(self) -> str:
        """Single-pass CBR encode with safety margin. Retries once if over limit."""
        safe_kbps = int(self.video_kbps * SAFETY_MARGIN)
        output = self._run_single_pass(safe_kbps)

        # Check if output exceeds target; retry with further reduction.
        output_mb = Path(output).stat().st_size / 1_000_000
        if output_mb > self.config.max_mb:
            reduction = self.config.max_mb / output_mb * 0.95
            retry_kbps = int(safe_kbps * reduction)
            logger.info(
                "Output %.1fMB exceeds %sMB — retrying at %sk",
                output_mb,
                self.config.max_mb,
                retry_kbps,
            )
            output = self._run_single_pass(retry_kbps)

        return output

    def _run_single_pass(self, kbps: int) -> str:
        """Execute a single-pass encode at the given bitrate."""
        stream = self._build_output_stream(
            self.output_path,
            vcodec=self.encoder_name,
            **{"b:v": f"{kbps}k"},
        )
        self._run_ffmpeg(stream, "ENCODE")
        return self.output_path

    # -------------------------------------------------------------------------
    # Setup / configuration helpers
    # -------------------------------------------------------------------------

    def _resolve_output_path(self) -> None:
        """Default output path: original filename + '_{size}mb'."""
        if self.output_path:
            return
        input_p = self.config.input_path
        ext = input_p.suffix or ".mp4"
        size_label = f"{self.config.max_mb:g}"
        self.output_path = str(
            self.input_dir / f"{input_p.stem}_{size_label}mb{ext}"
        )

    def _ensure_ffmpeg_available(self) -> None:
        """Fail early with a clear error if ffmpeg/ffprobe are missing."""
        if not self.ffmpeg_path or not self.ffprobe_path:
            raise FileNotFoundError(
                "ffmpeg/ffprobe not found. Place them in a "
                "'ffmpeg' folder next to the app "
                "or install them and add to PATH."
            )

    def _probe_media(self) -> None:
        """Use ffprobe to fetch duration and stream metadata."""
        self.probe = ffprobe_media(
            str(self.config.input_path), self.ffprobe_path
        )
        full_duration = float(self.probe["format"]["duration"])
        # Use trim duration for bitrate calc and progress when trimming.
        self.duration = (
            self.config.trim_duration if self.config.trimming else full_duration
        )
        self.video_kbps = target_kbps_for_size_mb(
            self.config.max_mb, self.duration, audio_kbps=128
        )
        self.video_bps = self.video_kbps * 1000
        self.has_audio = any(
            s.get("codec_type") == "audio"
            for s in self.probe.get("streams", [])
        )

    def _configure_hwaccel(self) -> None:
        """Resolve the requested device preference to a label and hwaccel string."""
        self.device_label, hwaccel = resolve_device_info(
            self.config.device_preference
        )
        self.detected_device = None
        if "NVIDIA" in self.device_label:
            self.detected_device = "nvidia"
        if self.config.device_preference == "nvidia" and not detect_cuda():
            logger.warning(
                "NVIDIA GPU requested but not available; falling back to CPU."
            )
        logger.info(
            "Compression device: %s (hwaccel=%s)",
            self.device_label,
            hwaccel or "none",
        )
        self.input_kwargs = {"hwaccel": hwaccel} if hwaccel else {}

    def _select_encoder(self) -> None:
        """Select encoder based on available encoders and device."""
        available = detect_available_encoders(self.ffmpeg_path)
        override = self.config.encoder_override
        if override and override != "Auto":
            strategy_map = {
                enc.name: enc.strategy for enc in ENCODER_PRIORITY
            }
            self.encoder_name = override
            self.encoder_strategy = strategy_map.get(override, "single_pass_cbr")
        else:
            self.encoder_name, self.encoder_strategy = select_encoder(
                available, self.config.device_preference, self.detected_device
            )
        logger.info(
            "Encoder: %s (strategy: %s)",
            self.encoder_name,
            self.encoder_strategy,
        )

        if self.encoder_name == "libopenh264" and not override:
            self.encoder_warning = OPENH264_WARNING
            logger.warning(self.encoder_warning)
            if self.config.warning_cb:
                self.config.warning_cb(self.encoder_warning)

    def _compute_scaling(self) -> None:
        """Determine scaled resolution based on config or auto-scaling."""
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
            parse_fps(
                vstream.get("avg_frame_rate") or vstream.get("r_frame_rate")
            )
            if vstream
            else None
        )

        if self.config.resolution:
            # Manual override takes precedence.
            parsed = parse_resolution(self.config.resolution)
            if parsed:
                self.scale = parsed
        else:
            # Auto-scale based on bitrate-derived bpp thresholds.
            bpp_targets = {"low": 0.05, "medium": 0.07, "high": 0.10}
            target_bpp = bpp_targets.get(self.config.quality, 0.07)
            scaled = compute_scaled_resolution(
                width, height, fps, self.video_bps, target_bpp, min_height=480
            )
            if scaled:
                self.scale = scaled
                logger.info(
                    "Auto-scaling to %sx%s for quality '%s'.",
                    scaled[0],
                    scaled[1],
                    self.config.quality,
                )

    def _prepare_logs(self) -> None:
        """Create the log directory and pass log path for two-pass encoding."""
        self.log_dir = self.input_dir / ".output"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.passlog_path = self.log_dir / "ffmpeg2pass"

    # -------------------------------------------------------------------------
    # FFmpeg execution and progress
    # -------------------------------------------------------------------------

    def _render_progress(self, current_seconds: float, bar, phase: str) -> None:
        """Convert elapsed seconds to a 0-100% progress update."""
        if self.duration <= 0:
            return
        pct = min(max(current_seconds / self.duration, 0.0), 1.0) * 100.0
        if self.config.progress_cb:
            self.config.progress_cb(pct, phase)
            return
        if bar is None:
            sys.stdout.write(f"\rProgress: {pct:5.1f}%")
            sys.stdout.flush()
        else:
            bar.n = int(pct * 10)
            bar.refresh()

    def _run_ffmpeg(self, stream, phase: str) -> None:
        """Execute ffmpeg with optional progress parsing."""
        try:
            if self.config.progress:
                self._run_ffmpeg_with_progress(stream, phase)
            else:
                self._run_ffmpeg_simple(stream)
        except ffmpeg.Error as exc:
            self._write_ffmpeg_error(exc)
            raise RuntimeError(self._parse_ffmpeg_error(exc)) from exc

    @staticmethod
    def _parse_ffmpeg_error(exc) -> str:
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
        return (
            "An unknown FFmpeg error has occurred."
            " Check the error log for details."
        )

    def _run_ffmpeg_with_progress(self, stream, phase: str) -> None:
        """Enable progress reporting and parse out_time_ms from stderr."""
        bar = self._maybe_create_progress_bar(phase)
        stream = stream.global_args("-progress", "pipe:2", "-nostats")
        cmd = ffmpeg.compile(
            stream,
            cmd=self.ffmpeg_path,
            overwrite_output=self.config.overwrite,
        )
        stderr_lines: list[bytes] = []
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

    def _run_ffmpeg_simple(self, stream) -> None:
        """Run without progress parsing; optionally suppress logs."""
        cmd = ffmpeg.compile(
            stream,
            cmd=self.ffmpeg_path,
            overwrite_output=self.config.overwrite,
        )
        stderr_target = (
            subprocess.DEVNULL if self.config.disable_logs else subprocess.PIPE
        )
        process = subprocess.Popen(
            cmd,
            stdout=(
                subprocess.DEVNULL if self.config.disable_logs else None
            ),
            stderr=stderr_target,
            **popen_no_window_kwargs(),
        )
        process.wait()
        if process.returncode != 0:
            err_bytes = None
            if process.stderr is not None:
                err_bytes = process.stderr.read()
            raise ffmpeg.Error("ffmpeg", None, err_bytes)

    def _maybe_create_progress_bar(self, phase: str):
        """Create a tqdm bar only for CLI mode (no progress callback)."""
        if self.config.progress_cb is not None:
            return None
        try:
            from tqdm import tqdm
        except ImportError:
            return None
        if self.duration <= 0:
            return None
        return tqdm(total=1000, unit="permille", leave=True, desc=phase)

    def _iter_progress_seconds(self, stderr_stream):
        """Yield elapsed output time in seconds, along with raw stderr lines."""
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

    def _finish_progress_bar(self, bar) -> None:
        """Close the progress bar or emit a trailing newline for stdout mode."""
        if bar is not None:
            bar.close()
        elif self.config.progress_cb is None:
            sys.stdout.write("\n")

    def _write_ffmpeg_error(self, exc) -> None:
        """Persist ffmpeg stderr to a log file for troubleshooting."""
        if not self.log_dir:
            self.log_dir = self.input_dir / ".output"
            self.log_dir.mkdir(parents=True, exist_ok=True)
        err_path = self.log_dir / "ffmpeg-error.log"
        with open(err_path, "wb") as f:
            if exc.stderr:
                f.write(exc.stderr)
            else:
                f.write(b"No stderr captured from ffmpeg.\n")
        logger.error("FFmpeg failed. See: %s", err_path)

    def _cleanup_logs(self) -> None:
        """Remove two-pass log files and delete the log directory if empty."""
        if not self.passlog_path or not self.log_dir:
            return
        passlog_base = self.passlog_path.name
        for filepath in list(self.log_dir.glob(f"{passlog_base}*.log")) + list(
            self.log_dir.glob(f"{passlog_base}*.log.mbtree")
        ):
            try:
                filepath.unlink()
            except FileNotFoundError:
                pass

        try:
            if not any(self.log_dir.iterdir()):
                self.log_dir.rmdir()
        except OSError:
            pass
