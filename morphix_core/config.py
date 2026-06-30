"""Compression configuration dataclass — the single config object for a run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from morphix_core.bitrate import clamp_even


@dataclass(frozen=True)
class CompressConfig:
    """Immutable configuration for a single compression run.

    Constructed by the CLI, UI, or any other interface and passed into
    RunContext for execution. All user-facing parameters live here;
    mutable runtime state belongs in RunContext.
    """

    input_path: Path
    max_mb: float
    output_path: Path | None = None
    quality: Literal["low", "medium", "high"] = "medium"
    resolution: str | None = None
    device_preference: Literal["auto", "nvidia", "amd", "intel", "cpu"] = "auto"
    overwrite: bool = True
    disable_logs: bool = True
    progress: bool = True
    progress_cb: Callable[[float, str], None] | None = None
    start: float | None = None
    end: float | None = None
    warning_cb: Callable[[str], None] | None = None
    encoder_override: str | None = None

    def __post_init__(self) -> None:
        # Coerce input_path to an absolute Path.
        if isinstance(self.input_path, str):
            object.__setattr__(self, "input_path", Path(self.input_path).resolve())
        elif isinstance(self.input_path, Path):
            object.__setattr__(self, "input_path", self.input_path.resolve())

        # Coerce output_path to Path if provided as str.
        if isinstance(self.output_path, str):
            object.__setattr__(self, "output_path", Path(self.output_path))

    @property
    def trimming(self) -> bool:
        """Whether trim mode is active (both start and end provided)."""
        return self.start is not None and self.end is not None

    @property
    def trim_duration(self) -> float:
        """Duration of the trim segment in seconds, or 0.0 if not trimming."""
        if self.trimming:
            return self.end - self.start
        return 0.0


def parse_resolution(resolution: str) -> tuple[int, int] | None:
    """Parse a resolution string like '1280x720' into (width, height).

    Returns None if the string is invalid or produces dimensions < 2.
    Both dimensions are clamped to even values for H.264 compatibility.
    """
    if "x" not in resolution.lower():
        return None
    parts = resolution.lower().split("x", 1)
    try:
        w = clamp_even(int(parts[0]))
        h = clamp_even(int(parts[1]))
    except (ValueError, IndexError):
        return None
    if w < 2 or h < 2:
        return None
    return w, h
