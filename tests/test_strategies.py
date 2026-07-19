"""Unit tests for morphix_core.strategies (Strategy pattern classes)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from morphix_core.strategies import (
    STRATEGY_REGISTRY,
    CRFStrategy,
    EncodingStrategy,
    NvencMultipassStrategy,
    SinglePassCBRStrategy,
    TwoPassStrategy,
)

# ---------------------------------------------------------------------------
# Helpers — mock RunContext with the attributes strategies need
# ---------------------------------------------------------------------------


def _make_context(
    encoder_name="libx264",
    encoder_strategy="two_pass",
    video_kbps=1000,
    output_path="/out/video_15mb.mp4",
    input_path="/in/video.mp4",
    input_kwargs=None,
    scale=None,
    has_audio=True,
    max_mb=15.0,
    trimming=False,
    trim_duration=0.0,
    bit_rate="8000000",
):
    """Create a mock RunContext with the attributes strategies access."""
    ctx = MagicMock()
    ctx.encoder_name = encoder_name
    ctx.encoder_strategy = encoder_strategy
    ctx.video_kbps = video_kbps
    ctx.output_path = output_path
    ctx.input_dir = Path("/in")
    ctx.input_kwargs = input_kwargs or {}
    ctx.scale = scale
    ctx.has_audio = has_audio
    ctx.passlog_path = None
    ctx.log_dir = None
    ctx.probe = {"format": {"bit_rate": bit_rate}}
    ctx.config = MagicMock()
    ctx.config.input_path = Path(input_path)
    ctx.config.max_mb = max_mb
    ctx.config.trimming = trimming
    ctx.config.trim_duration = trim_duration
    ctx.config.start = 0.0 if trimming else None
    ctx.config.end = trim_duration if trimming else None
    # _build_output_stream and _build_analysis_stream return MagicMocks
    ctx._build_output_stream.return_value = MagicMock(name="output_stream")
    ctx._build_analysis_stream.return_value = MagicMock(name="analysis_stream")
    return ctx


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------


class TestStrategyRegistry:
    def test_registry_contains_all_strategies(self):
        assert "two_pass" in STRATEGY_REGISTRY
        assert "nvenc_multipass" in STRATEGY_REGISTRY
        assert "single_pass_cbr" in STRATEGY_REGISTRY
        assert "crf" in STRATEGY_REGISTRY

    def test_registry_values_are_strategy_subclasses(self):
        for cls in STRATEGY_REGISTRY.values():
            assert issubclass(cls, EncodingStrategy)


# ---------------------------------------------------------------------------
# TwoPassStrategy tests
# ---------------------------------------------------------------------------


class TestTwoPassStrategy:
    def test_calls_run_ffmpeg_twice(self):
        """Two-pass strategy calls _run_ffmpeg with PASS1 and PASS2."""
        ctx = _make_context()
        # Output file "fits" — no retry needed.
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 10_000_000
            ctx.config.max_mb = 15.0
            strategy = TwoPassStrategy()
            strategy.execute(ctx)

        assert ctx._run_ffmpeg.call_count == 2
        phases = [c.args[1] for c in ctx._run_ffmpeg.call_args_list]
        assert phases == ["PASS1", "PASS2"]

    def test_returns_output_path(self):
        ctx = _make_context(output_path="/out/result.mp4")
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 10_000_000
            ctx.config.max_mb = 15.0
            strategy = TwoPassStrategy()
            result = strategy.execute(ctx)
        assert result == "/out/result.mp4"

    def test_applies_safety_margin(self):
        """Uses 95% of video_kbps for the target bitrate."""
        ctx = _make_context(encoder_name="libx264", video_kbps=1000)
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 10_000_000
            ctx.config.max_mb = 15.0
            strategy = TwoPassStrategy()
            strategy.execute(ctx)

        # Pass 2 output stream should use 950k (1000 * 0.95)
        kwargs = ctx._build_output_stream.call_args.kwargs
        assert kwargs["b:v"] == "950k"

    def test_applies_vbv_constraints(self):
        """Passes maxrate and bufsize to enforce bitrate ceiling."""
        ctx = _make_context(encoder_name="libx264", video_kbps=1000)
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 10_000_000
            ctx.config.max_mb = 15.0
            strategy = TwoPassStrategy()
            strategy.execute(ctx)

        kwargs = ctx._build_output_stream.call_args.kwargs
        assert kwargs["maxrate"] == "950k"
        assert kwargs["bufsize"] == "1900k"

    def test_retries_when_output_exceeds_target(self):
        """Retries with reduced bitrate when output overshoots."""
        ctx = _make_context(encoder_name="libx264", video_kbps=1000)

        with patch("morphix_core.strategies.Path") as mock_path:
            mock_stat = MagicMock()
            # Output is 20MB, exceeds 15MB target — triggers retry.
            mock_stat.st_size = 20_000_000
            mock_path.return_value.stat.return_value = mock_stat
            ctx.config.max_mb = 15.0

            strategy = TwoPassStrategy()
            strategy.execute(ctx)

        # Should have called _run_ffmpeg 4 times (2 passes × 2 attempts)
        assert ctx._run_ffmpeg.call_count == 4

    def test_no_retry_when_output_fits(self):
        """No retry when output is within target."""
        ctx = _make_context(encoder_name="libx264", video_kbps=1000)
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 14_000_000
            ctx.config.max_mb = 15.0
            strategy = TwoPassStrategy()
            strategy.execute(ctx)

        # Only 2 calls — one pass each
        assert ctx._run_ffmpeg.call_count == 2

    def test_builds_analysis_stream_for_pass1(self):
        ctx = _make_context(encoder_name="libx264", video_kbps=500)
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 10_000_000
            ctx.config.max_mb = 15.0
            strategy = TwoPassStrategy()
            strategy.execute(ctx)

        ctx._build_analysis_stream.assert_called_once()
        kwargs = ctx._build_analysis_stream.call_args.kwargs
        assert kwargs["vcodec"] == "libx264"
        assert kwargs["preset"] == "medium"

    def test_builds_output_stream_for_pass2(self):
        ctx = _make_context(encoder_name="libx264", video_kbps=500)
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 10_000_000
            ctx.config.max_mb = 15.0
            strategy = TwoPassStrategy()
            strategy.execute(ctx)

        ctx._build_output_stream.assert_called_once()
        args = ctx._build_output_stream.call_args
        assert args.args[0] == ctx.output_path

    def test_creates_log_dir(self, tmp_path):
        """Prepare logs creates the .output directory."""
        ctx = _make_context()
        ctx.input_dir = tmp_path
        strategy = TwoPassStrategy()
        strategy._prepare_logs(ctx)

        assert ctx.log_dir == tmp_path / ".output"
        assert ctx.log_dir.exists()
        assert ctx.passlog_path == tmp_path / ".output" / "ffmpeg2pass"

    def test_cleanup_logs_removes_log_files(self, tmp_path):
        """Cleanup removes passlog files and empties directory."""
        log_dir = tmp_path / ".output"
        log_dir.mkdir()
        (log_dir / "ffmpeg2pass-0.log").write_text("data")
        (log_dir / "ffmpeg2pass-0.log.mbtree").write_text("data")

        ctx = _make_context()
        ctx.log_dir = log_dir
        ctx.passlog_path = log_dir / "ffmpeg2pass"

        strategy = TwoPassStrategy()
        strategy._cleanup_logs(ctx)

        assert not list(log_dir.glob("*.log"))
        assert not log_dir.exists()  # empty dir removed


# ---------------------------------------------------------------------------
# NvencMultipassStrategy tests
# ---------------------------------------------------------------------------


class TestNvencMultipassStrategy:
    def test_calls_run_ffmpeg_once(self):
        ctx = _make_context(encoder_name="h264_nvenc", video_kbps=2000)
        strategy = NvencMultipassStrategy()
        strategy.execute(ctx)

        ctx._run_ffmpeg.assert_called_once()
        phase = ctx._run_ffmpeg.call_args.args[1]
        assert phase == "NVENC"

    def test_builds_output_stream_with_nvenc_params(self):
        ctx = _make_context(encoder_name="h264_nvenc", video_kbps=2000)
        strategy = NvencMultipassStrategy()
        strategy.execute(ctx)

        kwargs = ctx._build_output_stream.call_args.kwargs
        assert kwargs["vcodec"] == "h264_nvenc"
        assert kwargs["preset"] == "p4"
        assert kwargs["multipass"] == "fullres"

    def test_applies_full_bitrate(self):
        """NVENC uses full bitrate (safety_margin = 1.0)."""
        ctx = _make_context(encoder_name="h264_nvenc", video_kbps=2000)
        strategy = NvencMultipassStrategy()
        strategy.execute(ctx)

        kwargs = ctx._build_output_stream.call_args.kwargs
        assert kwargs["b:v"] == "2000k"
        assert kwargs["maxrate"] == "2000k"
        assert kwargs["bufsize"] == "4000k"

    def test_returns_output_path(self):
        ctx = _make_context(output_path="/out/nvenc.mp4")
        strategy = NvencMultipassStrategy()
        result = strategy.execute(ctx)
        assert result == "/out/nvenc.mp4"


# ---------------------------------------------------------------------------
# SinglePassCBRStrategy tests
# ---------------------------------------------------------------------------


class TestSinglePassCBRStrategy:
    def test_applies_safety_margin(self):
        """Uses 85% of video_kbps for the first attempt."""
        ctx = _make_context(encoder_name="libopenh264", video_kbps=1000)
        # Make the output file "small enough" so no retry.
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 10_000_000  # 10MB
            ctx.config.max_mb = 15.0
            strategy = SinglePassCBRStrategy()
            strategy.execute(ctx)

        # First call builds stream with 850k (1000 * 0.85)
        kwargs = ctx._build_output_stream.call_args.kwargs
        assert kwargs["b:v"] == "850k"

    def test_retries_when_output_exceeds_target(self):
        """Retries with reduced bitrate when output is too large."""
        ctx = _make_context(encoder_name="libopenh264", video_kbps=1000)

        # First call: output is 20MB (exceeds 15MB target).
        # Second call: output is 12MB (fits).
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_stat = MagicMock()
            # First check: 20MB, triggers retry
            mock_stat.st_size = 20_000_000
            mock_path.return_value.stat.return_value = mock_stat
            ctx.config.max_mb = 15.0

            strategy = SinglePassCBRStrategy()
            strategy.execute(ctx)

        # Should have called _run_ffmpeg twice (initial + retry)
        assert ctx._run_ffmpeg.call_count == 2

    def test_returns_output_path(self):
        ctx = _make_context(output_path="/out/cbr.mp4")
        with patch("morphix_core.strategies.Path") as mock_path:
            mock_path.return_value.stat.return_value.st_size = 10_000_000
            ctx.config.max_mb = 15.0
            strategy = SinglePassCBRStrategy()
            result = strategy.execute(ctx)
        assert result == "/out/cbr.mp4"


# ---------------------------------------------------------------------------
# CRFStrategy tests
# ---------------------------------------------------------------------------


class TestCRFStrategy:
    def test_uses_libx264_crf_by_default(self):
        ctx = _make_context(encoder_name="libx264")
        strategy = CRFStrategy()
        strategy.execute(ctx)

        kwargs = ctx._build_output_stream.call_args.kwargs
        assert kwargs["vcodec"] == "libx264"
        assert kwargs["crf"] == 18
        assert kwargs["preset"] == "medium"

    def test_uses_nvenc_constqp_for_nvidia(self):
        ctx = _make_context(encoder_name="h264_nvenc")
        strategy = CRFStrategy()
        strategy.execute(ctx)

        kwargs = ctx._build_output_stream.call_args.kwargs
        assert kwargs["vcodec"] == "h264_nvenc"
        assert kwargs["rc"] == "constqp"
        assert kwargs["qp"] == 18

    def test_calls_run_ffmpeg_with_crf_phase(self):
        ctx = _make_context()
        strategy = CRFStrategy()
        strategy.execute(ctx)

        phase = ctx._run_ffmpeg.call_args.args[1]
        assert phase == "CRF"

    def test_returns_output_path(self):
        ctx = _make_context(output_path="/out/crf.mp4")
        strategy = CRFStrategy()
        result = strategy.execute(ctx)
        assert result == "/out/crf.mp4"

    def test_should_use_true_when_trim_fits(self):
        """should_use returns True when segment fits in target."""
        ctx = _make_context(
            encoder_name="libx264",
            trimming=True,
            trim_duration=20.0,
            bit_rate="4000000",  # 4Mbps * 20s = 10MB
            max_mb=15.0,
        )
        assert CRFStrategy.should_use(ctx) is True

    def test_should_use_false_when_not_trimming(self):
        ctx = _make_context(trimming=False)
        assert CRFStrategy.should_use(ctx) is False

    def test_should_use_false_when_encoder_unsupported(self):
        ctx = _make_context(
            encoder_name="libopenh264",
            trimming=True,
            trim_duration=20.0,
            bit_rate="4000000",
            max_mb=15.0,
        )
        assert CRFStrategy.should_use(ctx) is False

    def test_should_use_false_when_segment_too_large(self):
        ctx = _make_context(
            encoder_name="libx264",
            trimming=True,
            trim_duration=60.0,
            bit_rate="8000000",  # 8Mbps * 60s = 60MB
            max_mb=15.0,
        )
        assert CRFStrategy.should_use(ctx) is False
