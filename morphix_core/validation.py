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
    """Return True if target_mb is below 3% of the input file size (very high compression).

    Returns False otherwise.
    """
    file_size_mb = os.path.getsize(input_path) / 1_000_000
    return target_mb < 0.03 * file_size_mb
