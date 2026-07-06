"""FFmpeg process execution — compile, run, parse progress, handle errors.

This module extracts all subprocess interaction with ffmpeg from the encoding
pipeline into a single focused class. The :class:`FFmpegExecutor` handles:

- Compiling an ffmpeg-python stream graph into a command
- Running the process (with or without real-time progress parsing)
- Parsing ``out_time_ms`` from ffmpeg's progress output
- Rendering progress percentages (via callback or stdout)
- Extracting user-friendly error messages from ffmpeg stderr
- Persisting error logs for troubleshooting
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from collections.abc import Callable, Generator
from pathlib import Path

import ffmpeg

from morphix_core.ffmpeg_utils import popen_no_window_kwargs

logger = logging.getLogger("morphix")


class FFmpegExecutor:
    """Executes ffmpeg commands with optional progress tracking.

    Args:
        ffmpeg_path: Path to the ffmpeg binary.
        overwrite: Whether to overwrite existing output files.
        disable_logs: Suppress ffmpeg console output when not tracking progress.
        progress: Enable real-time progress parsing.
        progress_cb: Callback receiving (percentage, phase_label). If None and
            progress is enabled, progress is written to stdout.
    """

    def __init__(
        self,
        *,
        ffmpeg_path: str,
        overwrite: bool = True,
        disable_logs: bool = True,
        progress: bool = True,
        progress_cb: Callable[[float, str], None] | None = None,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.overwrite = overwrite
        self.disable_logs = disable_logs
        self.progress = progress
        self.progress_cb = progress_cb

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def run(
        self,
        stream: ffmpeg.Stream,
        phase: str,
        duration: float,
        log_dir: Path | None = None,
    ) -> None:
        """Execute an ffmpeg stream with error handling.

        Args:
            stream: An ffmpeg-python output stream to compile and run.
            phase: Label for the current phase (e.g. "PASS1", "PASS2", "NVENC").
            duration: Expected duration in seconds (for progress calculation).
            log_dir: Directory to write error logs into. Created if missing.

        Raises:
            RuntimeError: With a user-friendly message if ffmpeg fails.
        """
        try:
            if self.progress:
                self._run_with_progress(stream, phase, duration)
            else:
                self._run_simple(stream)
        except ffmpeg.Error as exc:
            self._write_error_log(exc, log_dir)
            raise RuntimeError(self.parse_error(exc)) from exc

    # -------------------------------------------------------------------------
    # Execution modes
    # -------------------------------------------------------------------------

    def _run_with_progress(
        self, stream: ffmpeg.Stream, phase: str, duration: float
    ) -> None:
        """Run ffmpeg with real-time progress parsing from stderr."""
        bar = self._maybe_create_progress_bar(phase, duration)
        stream = stream.global_args("-progress", "pipe:2", "-nostats")
        cmd = ffmpeg.compile(
            stream, cmd=self.ffmpeg_path, overwrite_output=self.overwrite
        )
        stderr_lines: list[bytes] = []
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **popen_no_window_kwargs(),
        )
        for current_seconds, line in self.iter_progress_seconds(process.stderr):
            if line:
                stderr_lines.append(line)
            if current_seconds is not None:
                self._render_progress(current_seconds, bar, phase, duration)
        process.wait()
        self._finish_progress_bar(bar)
        if process.returncode != 0:
            raise ffmpeg.Error("ffmpeg", None, b"".join(stderr_lines))

    def _run_simple(self, stream: ffmpeg.Stream) -> None:
        """Run ffmpeg without progress parsing."""
        cmd = ffmpeg.compile(
            stream, cmd=self.ffmpeg_path, overwrite_output=self.overwrite
        )
        stderr_target = (
            subprocess.DEVNULL if self.disable_logs else subprocess.PIPE
        )
        process = subprocess.Popen(
            cmd,
            stdout=(subprocess.DEVNULL if self.disable_logs else None),
            stderr=stderr_target,
            **popen_no_window_kwargs(),
        )
        process.wait()
        if process.returncode != 0:
            err_bytes = None
            if process.stderr is not None:
                err_bytes = process.stderr.read()
            raise ffmpeg.Error("ffmpeg", None, err_bytes)

    # -------------------------------------------------------------------------
    # Progress parsing and rendering
    # -------------------------------------------------------------------------

    @staticmethod
    def iter_progress_seconds(
        stderr_stream,
    ) -> Generator[tuple[float | None, bytes], None, None]:
        """Yield (elapsed_seconds | None, raw_line) from ffmpeg progress output.

        Parses ``out_time_ms=<microseconds>`` lines. Non-matching lines yield
        ``(None, line)``.
        """
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

    def _render_progress(
        self,
        current_seconds: float,
        bar,
        phase: str,
        duration: float,
    ) -> None:
        """Convert elapsed seconds to a 0–100% progress update."""
        if duration <= 0:
            return
        pct = min(max(current_seconds / duration, 0.0), 1.0) * 100.0
        if self.progress_cb:
            self.progress_cb(pct, phase)
            return
        if bar is None:
            if sys.stdout is not None:
                sys.stdout.write(f"\rProgress: {pct:5.1f}%")
                sys.stdout.flush()
        else:
            bar.n = int(pct * 10)
            bar.refresh()

    def _maybe_create_progress_bar(self, phase: str, duration: float):
        """Create a tqdm progress bar for CLI mode (no callback)."""
        if self.progress_cb is not None:
            return None
        try:
            from tqdm import tqdm
        except ImportError:
            return None
        if duration <= 0:
            return None
        return tqdm(total=1000, unit="permille", leave=True, desc=phase)

    def _finish_progress_bar(self, bar) -> None:
        """Close tqdm bar or emit a trailing newline for raw stdout mode."""
        if bar is not None:
            bar.close()
        elif self.progress_cb is None and sys.stdout is not None:
            sys.stdout.write("\n")

    # -------------------------------------------------------------------------
    # Error handling
    # -------------------------------------------------------------------------

    @staticmethod
    def parse_error(exc: ffmpeg.Error) -> str:
        """Extract a user-friendly message from an ffmpeg error.

        Checks for known NVENC/CUDA errors first, then scans stderr for the
        first line containing 'error' or 'failed'.
        """
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
        # Scan for first meaningful error line.
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

    @staticmethod
    def _write_error_log(exc: ffmpeg.Error, log_dir: Path | None) -> None:
        """Persist ffmpeg stderr to an error log file."""
        if log_dir is None:
            return
        log_dir.mkdir(parents=True, exist_ok=True)
        err_path = log_dir / "ffmpeg-error.log"
        with open(err_path, "wb") as f:
            if exc.stderr:
                f.write(exc.stderr)
            else:
                f.write(b"No stderr captured from ffmpeg.\n")
        logger.error("FFmpeg failed. See: %s", err_path)
