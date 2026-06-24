import os


def check_target_exceeds_file_size(target_mb: float, input_path: str) -> None:
    """Raise ValueError if target_mb is >= the actual file size in MB.

    Must be called before any ffprobe or ffmpeg invocation.
    """
    file_size_mb = os.path.getsize(input_path) / 1_000_000
    if target_mb >= file_size_mb:
        raise ValueError(
            f"Target size {target_mb} MB is not smaller than the input file size "
            f"({file_size_mb:.2f} MB). Choose a smaller target."
        )


def check_low_compression_ratio(target_mb: float, input_path: str) -> bool:
    """Return True if target_mb is below 3% of the input file size.

    Indicates very high compression. Returns False otherwise.
    """
    file_size_mb = os.path.getsize(input_path) / 1_000_000
    return target_mb < 0.03 * file_size_mb


def check_trim_values(start: float | None, end: float | None, full_duration: float):
    """Validate trim start/end values against video duration.

    Returns a tuple (ok: bool, error_message: str or None).
    Both start and end must be provided together for trimming to be enabled.

    Rules:
      1. If only one of start/end is provided, return False ("both required").
      2. Both must be >= 0.
      3. end must be greater than start.
      4. (end - start) must not exceed full_duration.
    """
    if (start is not None) != (end is not None):
        return False, "Both Start and End times must be provided for trimming."
    if start is None:
        return True, None
    if start < 0:
        return False, "Start time must be >= 0."
    if end < 0:
        return False, "End time must be >= 0."
    if end <= start:
        return False, "End time must be greater than Start time."
    if (end - start) > full_duration:
        trim_dur = end - start
        return (
            False,
            f"Trim duration ({trim_dur:.1f}s) exceeds "
            f"video duration ({full_duration:.1f}s).",
        )
    return True, None
