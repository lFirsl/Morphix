"""Shared time parsing and formatting utilities for Morphix UI tabs."""

from __future__ import annotations


def parse_time(time_str: str) -> float:
    """Parse MM:SS or HH:MM:SS string to seconds.

    Raises:
        ValueError: if the format is not recognised.
    """
    parts = time_str.strip().split(":")
    if len(parts) == 2:
        m, s = map(int, parts)
        return float(m * 60 + s)
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return float(h * 3600 + m * 60 + s)
    raise ValueError(f"Invalid time format: {time_str!r} — expected MM:SS or HH:MM:SS")


def format_time(seconds: float) -> str:
    """Format seconds as zero-padded HH:MM:SS."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"
