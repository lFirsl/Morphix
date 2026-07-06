"""Unit tests for morphix_core.ffmpeg_executor.FFmpegExecutor."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest

from morphix_core.ffmpeg_executor import FFmpegExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_executor(**kwargs) -> FFmpegExecutor:
    """Create an FFmpegExecutor with sensible test defaults."""
    defaults = {
        "ffmpeg_path": "/fake/ffmpeg",
        "overwrite": True,
        "disable_logs": True,
        "progress": True,
        "progress_cb": None,
    }
    defaults.update(kwargs)
    return FFmpegExecutor(**defaults)


# ---------------------------------------------------------------------------
# iter_progress_seconds tests
# ---------------------------------------------------------------------------


class TestIterProgressSeconds:
    def test_parses_out_time_ms_to_seconds(self):
        """Converts out_time_ms=5000000 to 5.0 seconds."""
        raw = b"out_time_ms=5000000\n"
        stream = io.BytesIO(raw)
        results = list(FFmpegExecutor.iter_progress_seconds(stream))
        assert len(results) == 1
        elapsed, line = results[0]
        assert elapsed == pytest.approx(5.0)
        assert line == raw

    def test_yields_none_for_non_matching_lines(self):
        """Lines without out_time_ms yield None as elapsed."""
        raw = b"frame=100\n"
        stream = io.BytesIO(raw)
        results = list(FFmpegExecutor.iter_progress_seconds(stream))
        assert len(results) == 1
        elapsed, line = results[0]
        assert elapsed is None
        assert line == raw

    def test_handles_multiple_lines(self):
        """Correctly handles a mix of matching and non-matching lines."""
        data = b"frame=10\nout_time_ms=2000000\nbitrate=500k\nout_time_ms=4000000\n"
        stream = io.BytesIO(data)
        results = list(FFmpegExecutor.iter_progress_seconds(stream))
        assert len(results) == 4
        assert results[0][0] is None
        assert results[1][0] == pytest.approx(2.0)
        assert results[2][0] is None
        assert results[3][0] == pytest.approx(4.0)

    def test_zero_value(self):
        """out_time_ms=0 yields 0.0 seconds."""
        stream = io.BytesIO(b"out_time_ms=0\n")
        results = list(FFmpegExecutor.iter_progress_seconds(stream))
        assert results[0][0] == pytest.approx(0.0)

    def test_empty_stream(self):
        """Empty stream yields no results."""
        stream = io.BytesIO(b"")
        results = list(FFmpegExecutor.iter_progress_seconds(stream))
        assert results == []


# ---------------------------------------------------------------------------
# _render_progress tests
# ---------------------------------------------------------------------------


class TestRenderProgress:
    def test_computes_correct_percentage_via_callback(self):
        """Calls progress_cb with correct pct = (elapsed / duration) * 100."""
        calls = []
        executor = make_executor(progress_cb=lambda pct, phase: calls.append((pct, phase)))
        executor._render_progress(50.0, None, "PASS1", 200.0)
        assert len(calls) == 1
        assert calls[0][0] == pytest.approx(25.0)
        assert calls[0][1] == "PASS1"

    def test_100_percent_at_end(self):
        """Yields 100% when elapsed equals duration."""
        calls = []
        executor = make_executor(progress_cb=lambda pct, phase: calls.append((pct, phase)))
        executor._render_progress(60.0, None, "PASS2", 60.0)
        assert calls[0][0] == pytest.approx(100.0)

    def test_clamps_above_100(self):
        """Clamps percentage to 100 even if elapsed > duration."""
        calls = []
        executor = make_executor(progress_cb=lambda pct, phase: calls.append((pct, phase)))
        executor._render_progress(70.0, None, "PASS1", 60.0)
        assert calls[0][0] == pytest.approx(100.0)

    def test_noop_when_duration_zero(self):
        """Does nothing when duration is 0 (avoids division by zero)."""
        calls = []
        executor = make_executor(progress_cb=lambda pct, phase: calls.append((pct, phase)))
        executor._render_progress(50.0, None, "PASS1", 0.0)
        assert calls == []

    def test_stdout_fallback_when_no_callback(self, capsys):
        """Writes to stdout when progress_cb is None."""
        executor = make_executor(progress_cb=None)
        executor._render_progress(50.0, None, "PASS1", 100.0)
        captured = capsys.readouterr()
        assert "50.0" in captured.out

    def test_no_stdout_when_callback_set(self, capsys):
        """Does not write to stdout when progress_cb is provided."""
        executor = make_executor(progress_cb=lambda pct, phase: None)
        executor._render_progress(50.0, None, "PASS1", 100.0)
        captured = capsys.readouterr()
        assert captured.out == ""


# ---------------------------------------------------------------------------
# parse_error tests
# ---------------------------------------------------------------------------


class TestParseError:
    def _make_error(self, stderr: bytes):
        import ffmpeg as ffmpeg_lib

        return ffmpeg_lib.Error("ffmpeg", None, stderr)

    def test_nvenc_driver_too_old(self):
        exc = self._make_error(b"Driver does not support the required nvenc API version")
        msg = FFmpegExecutor.parse_error(exc)
        assert "NVIDIA driver is too old" in msg

    def test_no_nvenc_devices(self):
        exc = self._make_error(b"No NVENC capable devices found")
        msg = FFmpegExecutor.parse_error(exc)
        assert "No NVIDIA GPU found" in msg

    def test_nvcuda_dll_missing(self):
        exc = self._make_error(b"Cannot load nvcuda.dll")
        msg = FFmpegExecutor.parse_error(exc)
        assert "CUDA drivers not found" in msg

    def test_generic_error_extraction(self):
        exc = self._make_error(b"frame=0\n[libx264] Error: something failed badly\n")
        msg = FFmpegExecutor.parse_error(exc)
        assert "FFmpeg error:" in msg
        assert "failed" in msg

    def test_unknown_error_fallback(self):
        exc = self._make_error(b"frame=0\nfps=0\n")
        msg = FFmpegExecutor.parse_error(exc)
        assert "unknown FFmpeg error" in msg

    def test_empty_stderr(self):
        exc = self._make_error(b"")
        msg = FFmpegExecutor.parse_error(exc)
        assert "unknown FFmpeg error" in msg

    def test_none_stderr(self):
        import ffmpeg as ffmpeg_lib

        exc = ffmpeg_lib.Error("ffmpeg", None, None)
        msg = FFmpegExecutor.parse_error(exc)
        assert "unknown FFmpeg error" in msg


# ---------------------------------------------------------------------------
# _write_error_log tests
# ---------------------------------------------------------------------------


class TestWriteErrorLog:
    def test_writes_stderr_to_file(self, tmp_path):
        """Writes exc.stderr content to ffmpeg-error.log in log_dir."""
        import ffmpeg as ffmpeg_lib

        exc = ffmpeg_lib.Error("ffmpeg", None, b"fatal error details")
        FFmpegExecutor._write_error_log(exc, tmp_path)
        log_file = tmp_path / "ffmpeg-error.log"
        assert log_file.exists()
        assert log_file.read_bytes() == b"fatal error details"

    def test_writes_placeholder_when_no_stderr(self, tmp_path):
        """Writes a placeholder message when stderr is None."""
        import ffmpeg as ffmpeg_lib

        exc = ffmpeg_lib.Error("ffmpeg", None, None)
        FFmpegExecutor._write_error_log(exc, tmp_path)
        log_file = tmp_path / "ffmpeg-error.log"
        assert b"No stderr captured" in log_file.read_bytes()

    def test_creates_log_dir_if_missing(self, tmp_path):
        """Creates the log directory if it doesn't exist."""
        import ffmpeg as ffmpeg_lib

        log_dir = tmp_path / "nested" / "logs"
        exc = ffmpeg_lib.Error("ffmpeg", None, b"error")
        FFmpegExecutor._write_error_log(exc, log_dir)
        assert (log_dir / "ffmpeg-error.log").exists()

    def test_noop_when_log_dir_is_none(self):
        """Does nothing when log_dir is None."""
        import ffmpeg as ffmpeg_lib

        exc = ffmpeg_lib.Error("ffmpeg", None, b"error")
        # Should not raise
        FFmpegExecutor._write_error_log(exc, None)


# ---------------------------------------------------------------------------
# run() integration tests (mocked subprocess)
# ---------------------------------------------------------------------------


class TestRun:
    def test_raises_runtime_error_on_ffmpeg_failure(self, tmp_path):
        """run() raises RuntimeError with user-friendly message on failure."""
        import ffmpeg as ffmpeg_lib

        executor = make_executor(progress=False)
        stream = MagicMock()

        with patch.object(
            executor,
            "_run_simple",
            side_effect=ffmpeg_lib.Error("ffmpeg", None, b"fatal error line"),
        ):
            with pytest.raises(RuntimeError, match="FFmpeg error: fatal error"):
                executor.run(stream, "PASS1", 100.0, tmp_path)

    def test_dispatches_to_progress_mode_when_enabled(self):
        """Calls _run_with_progress when progress=True."""
        executor = make_executor(progress=True)
        stream = MagicMock()
        with patch.object(executor, "_run_with_progress") as mock_prog:
            executor.run(stream, "PASS1", 100.0, None)
        mock_prog.assert_called_once_with(stream, "PASS1", 100.0)

    def test_dispatches_to_simple_mode_when_disabled(self):
        """Calls _run_simple when progress=False."""
        executor = make_executor(progress=False)
        stream = MagicMock()
        with patch.object(executor, "_run_simple") as mock_simple:
            executor.run(stream, "PASS1", 100.0, None)
        mock_simple.assert_called_once_with(stream)

    def test_error_log_written_on_failure(self, tmp_path):
        """Error log is written when ffmpeg fails."""
        import ffmpeg as ffmpeg_lib

        executor = make_executor(progress=False)
        stream = MagicMock()

        with patch.object(
            executor,
            "_run_simple",
            side_effect=ffmpeg_lib.Error("ffmpeg", None, b"some stderr"),
        ):
            with pytest.raises(RuntimeError):
                executor.run(stream, "PASS1", 100.0, tmp_path)

        assert (tmp_path / "ffmpeg-error.log").exists()
