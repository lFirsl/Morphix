"""Encoding engine — RunContext orchestrates a single compression run.

Pipeline steps (executed in order by ``execute()``):
1. Ensure ffmpeg/ffprobe binaries are available
2. Resolve the output file path
3. Probe media for duration/streams
4. Configure hardware acceleration
5. Select encoder and strategy
6. Apply trim input kwargs (if trimming)
7. Compute resolution scaling
8. Pick and execute the encoding strategy
"""

from __future__ import annotations

import logging
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
    select_encoder,
)
from morphix_core.ffmpeg_executor import FFmpegExecutor
from morphix_core.ffmpeg_utils import (
    detect_available_encoders,
    ffprobe_media,
    find_ffmpeg_binaries,
)
from morphix_core.gpu_detection import detect_cuda, resolve_device_info
from morphix_core.strategies import (
    STRATEGY_REGISTRY,
    CRFStrategy,
)

logger = logging.getLogger("morphix")


class RunContext:
    """Orchestrates a single compression run based on a CompressConfig.

    All user-facing parameters come from the frozen CompressConfig.
    This class holds mutable runtime state and coordinates the pipeline:
    ffmpeg discovery → probe → encoder selection → strategy execution.
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

        # FFmpeg executor — handles all subprocess interaction.
        self.executor = FFmpegExecutor(
            ffmpeg_path=self.ffmpeg_path or "",
            overwrite=config.overwrite,
            disable_logs=config.disable_logs,
            progress=config.progress,
            progress_cb=config.progress_cb,
        )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def execute(self) -> str:
        """Run the full compression pipeline. Returns the output file path.

        Steps:
        1. Ensure ffmpeg available
        2. Resolve output path
        3. Probe media
        4. Configure hwaccel
        5. Select encoder
        6. Apply trim kwargs
        7. Compute scaling
        8. Pick strategy → execute
        """
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

        if self.config.trimming:
            self.input_kwargs = {
                **self.input_kwargs,
                "ss": str(self.config.start),
                "t": str(self.config.trim_duration),
            }

        self._compute_scaling()

        strategy = self._pick_strategy()
        return strategy.execute(self)

    # -------------------------------------------------------------------------
    # Stream-building helpers (used by strategies)
    # -------------------------------------------------------------------------

    def _build_output_stream(
        self, output_path: str, **video_kwargs
    ) -> ffmpeg.Stream:
        """Build an ffmpeg output stream with optional scale and audio."""
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
    # Strategy selection
    # -------------------------------------------------------------------------

    def _pick_strategy(self):
        """Select the encoding strategy.

        - CRF if trimmed segment fits within target (quality-preserving)
        - Otherwise dispatch by encoder_strategy name via STRATEGY_REGISTRY
        """
        if CRFStrategy.should_use(self):
            est = self._estimated_segment_mb()
            logger.info(
                "Trimmed segment (~%.1fMB) fits within %sMB"
                " — using CRF encode.",
                est,
                self.config.max_mb,
            )
            return CRFStrategy()

        strategy_cls = STRATEGY_REGISTRY[self.encoder_strategy]
        return strategy_cls()

    def _estimated_segment_mb(self) -> float:
        """Estimate the size of the trim segment based on the source bitrate."""
        total_bitrate = int(self.probe["format"].get("bit_rate", 0))
        return (total_bitrate * self.config.trim_duration) / 8 / 1_000_000

    # -------------------------------------------------------------------------
    # Pipeline setup steps
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
        """Resolve device preference to a label and hwaccel string."""
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
            parsed = parse_resolution(self.config.resolution)
            if parsed:
                self.scale = parsed
        else:
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

    # -------------------------------------------------------------------------
    # FFmpeg execution (delegates to FFmpegExecutor)
    # -------------------------------------------------------------------------

    def _run_ffmpeg(self, stream, phase: str) -> None:
        """Execute ffmpeg with optional progress parsing.

        Dispatches to _run_ffmpeg_with_progress or _run_ffmpeg_simple.
        On failure, writes an error log and raises RuntimeError.
        """
        try:
            if self.config.progress:
                self._run_ffmpeg_with_progress(stream, phase)
            else:
                self._run_ffmpeg_simple(stream)
        except ffmpeg.Error as exc:
            if not self.log_dir:
                self.log_dir = self.input_dir / ".output"
            FFmpegExecutor._write_error_log(exc, self.log_dir)
            raise RuntimeError(FFmpegExecutor.parse_error(exc)) from exc

    def _run_ffmpeg_with_progress(self, stream, phase: str) -> None:
        """Delegate to executor's progress-enabled run."""
        self.executor._run_with_progress(stream, phase, self.duration)

    def _run_ffmpeg_simple(self, stream) -> None:
        """Delegate to executor's simple run."""
        self.executor._run_simple(stream)
