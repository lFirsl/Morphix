"""Encoding strategies (Strategy pattern) for Morphix.

Each strategy encapsulates one way of encoding a video via ffmpeg. The
:class:`RunContext` selects the appropriate strategy and calls
``strategy.execute(context)`` — the strategy reads what it needs from the
context (scale, bitrate, paths, etc.) and drives ffmpeg through the context's
executor.

Adding a new encoding strategy:
1. Subclass :class:`EncodingStrategy`.
2. Implement ``execute(context) -> str``.
3. Set ``safety_margin`` if the default (1.0) is not appropriate.
4. Register it in :data:`STRATEGY_REGISTRY`.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from morphix_core.encoding import RunContext

logger = logging.getLogger("morphix")


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class EncodingStrategy(ABC):
    """Abstract base class for encoding strategies.

    Each concrete strategy implements ``execute(context)`` which orchestrates
    one or more ffmpeg invocations and returns the output file path.

    Attributes:
        safety_margin: Fraction of the calculated bitrate to actually target.
            Accounts for container overhead and rate-control variance.
            Subclasses override as needed; default is 1.0 (no margin).
    """

    safety_margin: float = 1.0

    @abstractmethod
    def execute(self, context: RunContext) -> str:
        """Run the encoding and return the output file path."""


# ---------------------------------------------------------------------------
# Concrete strategies
# ---------------------------------------------------------------------------


class TwoPassStrategy(EncodingStrategy):
    """Two-pass libx264 encode for accurate bitrate targeting.

    Pass 1 analyses the video (output to NUL), Pass 2 produces the final file.
    Pass log files are created in a `.output/` subdirectory and cleaned up
    after completion.

    A 5% safety margin accounts for MP4 container overhead (moov atom,
    muxing headers) which becomes significant at small target sizes.
    VBV constraints (maxrate/bufsize) enforce a hard bitrate ceiling.
    If the output still overshoots, a single retry with further reduction
    is attempted.
    """

    safety_margin = 0.95

    def execute(self, context: RunContext) -> str:
        safe_kbps = int(context.video_kbps * self.safety_margin)
        self._prepare_logs(context)

        self._run_two_pass(context, safe_kbps)

        # Post-encode size check — retry once if output overshoots.
        output_mb = Path(context.output_path).stat().st_size / 1_000_000
        if output_mb > context.config.max_mb:
            reduction = context.config.max_mb / output_mb * 0.95
            retry_kbps = int(safe_kbps * reduction)
            logger.info(
                "Two-pass output %.2fMB exceeds %sMB — retrying at %sk",
                output_mb,
                context.config.max_mb,
                retry_kbps,
            )
            self._run_two_pass(context, retry_kbps)

        self._cleanup_logs(context)
        return context.output_path

    def _run_two_pass(self, context: RunContext, kbps: int) -> None:
        """Execute a full two-pass encode at the given bitrate."""
        maxrate = f"{kbps}k"
        bufsize = f"{kbps * 2}k"

        # Pass 1: analysis (video only → NUL).
        context._run_ffmpeg(
            context._build_analysis_stream(
                vcodec=context.encoder_name,
                preset="medium",
                **{"b:v": f"{kbps}k"},
                maxrate=maxrate,
                bufsize=bufsize,
                **{"pass": 1},
                **{"passlogfile": str(context.passlog_path)},
            ),
            "PASS1",
        )

        # Pass 2: actual encode.
        stream = context._build_output_stream(
            context.output_path,
            vcodec=context.encoder_name,
            preset="medium",
            **{"b:v": f"{kbps}k"},
            maxrate=maxrate,
            bufsize=bufsize,
            **{"pass": 2},
            **{"passlogfile": str(context.passlog_path)},
        )
        context._run_ffmpeg(stream, "PASS2")

    # ------------------------------------------------------------------
    # Log management (only relevant for two-pass)
    # ------------------------------------------------------------------

    @staticmethod
    def _prepare_logs(context: RunContext) -> None:
        """Create the log directory and pass log path."""
        context.log_dir = context.input_dir / ".output"
        context.log_dir.mkdir(parents=True, exist_ok=True)
        context.passlog_path = context.log_dir / "ffmpeg2pass"

    @staticmethod
    def _cleanup_logs(context: RunContext) -> None:
        """Remove two-pass log files and delete the log directory if empty."""
        if not context.passlog_path or not context.log_dir:
            return
        passlog_base = context.passlog_path.name
        for filepath in list(
            context.log_dir.glob(f"{passlog_base}*.log")
        ) + list(context.log_dir.glob(f"{passlog_base}*.log.mbtree")):
            try:
                filepath.unlink()
            except FileNotFoundError:
                pass

        try:
            if not any(context.log_dir.iterdir()):
                context.log_dir.rmdir()
        except OSError:
            pass


class NvencMultipassStrategy(EncodingStrategy):
    """NVENC multipass encode — single ffmpeg invocation with internal two-pass.

    Uses NVIDIA's hardware encoder with full-resolution multipass for accurate
    bitrate targeting without needing separate pass log files.

    No safety margin needed — NVENC's internal multipass rate control is
    accurate and already constrained by maxrate/bufsize VBV.
    """

    safety_margin = 1.0

    def execute(self, context: RunContext) -> str:
        kbps = int(context.video_kbps * self.safety_margin)
        stream = context._build_output_stream(
            context.output_path,
            vcodec="h264_nvenc",
            preset="p4",
            multipass="fullres",
            **{"b:v": f"{kbps}k"},
            maxrate=f"{kbps}k",
            bufsize=f"{kbps * 2}k",
        )
        context._run_ffmpeg(stream, "NVENC")
        return context.output_path


class SinglePassCBRStrategy(EncodingStrategy):
    """Single-pass CBR encode with safety margin.

    Targets 85% of calculated bitrate to avoid overshooting. If the output
    still exceeds the target size, retries once with further reduction.
    Used by OpenH264 and other single-pass encoders.
    """

    safety_margin = 0.85

    def execute(self, context: RunContext) -> str:
        safe_kbps = int(context.video_kbps * self.safety_margin)
        output = self._run_single_pass(context, safe_kbps)

        # Check if output exceeds target; retry with further reduction.
        output_mb = Path(output).stat().st_size / 1_000_000
        if output_mb > context.config.max_mb:
            reduction = context.config.max_mb / output_mb * 0.95
            retry_kbps = int(safe_kbps * reduction)
            logger.info(
                "Output %.1fMB exceeds %sMB — retrying at %sk",
                output_mb,
                context.config.max_mb,
                retry_kbps,
            )
            output = self._run_single_pass(context, retry_kbps)

        return output

    @staticmethod
    def _run_single_pass(context: RunContext, kbps: int) -> str:
        """Execute a single-pass encode at the given bitrate."""
        stream = context._build_output_stream(
            context.output_path,
            vcodec=context.encoder_name,
            **{"b:v": f"{kbps}k"},
        )
        context._run_ffmpeg(stream, "ENCODE")
        return context.output_path


class CRFStrategy(EncodingStrategy):
    """Single-pass CRF encode — preserves quality without a bitrate target.

    Used when trimming produces a segment that already fits within the target
    size. CRF 18 is near-visually-lossless for both libx264 and h264_nvenc.

    No safety margin — there is no bitrate target to constrain.
    """

    safety_margin = 1.0

    def execute(self, context: RunContext) -> str:
        if context.encoder_name == "h264_nvenc":
            vcodec_kwargs = {"vcodec": "h264_nvenc", "rc": "constqp", "qp": 18}
        else:
            vcodec_kwargs = {"vcodec": "libx264", "preset": "medium", "crf": 18}
        stream = context._build_output_stream(
            context.output_path, **vcodec_kwargs
        )
        context._run_ffmpeg(stream, "CRF")
        return context.output_path

    @staticmethod
    def should_use(context: RunContext) -> bool:
        """Determine if CRF encoding is appropriate for this context.

        Returns True if trimming is active, the segment fits within max_mb,
        and the encoder supports CRF mode.
        """
        if not context.config.trimming:
            return False
        if context.encoder_name not in ("libx264", "h264_nvenc"):
            return False
        total_bitrate = int(context.probe["format"].get("bit_rate", 0))
        est_mb = (total_bitrate * context.config.trim_duration) / 8 / 1_000_000
        return est_mb <= context.config.max_mb


# ---------------------------------------------------------------------------
# Strategy registry — maps strategy name strings to classes
# ---------------------------------------------------------------------------

STRATEGY_REGISTRY: dict[str, type[EncodingStrategy]] = {
    "two_pass": TwoPassStrategy,
    "nvenc_multipass": NvencMultipassStrategy,
    "single_pass_cbr": SinglePassCBRStrategy,
    "crf": CRFStrategy,
}
