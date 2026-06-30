# morphix_core/core.py — public API facade
# No logic lives here; all symbols are re-exported from submodules so that
# existing import paths (cli.py, main_window.py, tests) continue to work unchanged.

# Re-export internal utilities that tests currently import from here.
# These will be removed in Task 4 once test imports are updated.
from morphix_core.bitrate import (  # noqa: F401
    clamp_even,
    compute_scaled_resolution,
    parse_fps,
    target_kbps_for_size_mb,
)
from morphix_core.config import CompressConfig, parse_resolution  # noqa: F401
from morphix_core.encoder_selection import (  # noqa: F401
    ENCODER_PRIORITY,
    OPENH264_WARNING,
    SAFETY_MARGIN,  # noqa: F401
    select_encoder,
)
from morphix_core.encoding import RunContext  # noqa: F401
from morphix_core.ffmpeg_utils import (  # noqa: F401
    detect_available_encoders,
    detect_build_type,
    ffprobe_media,
    find_ffmpeg_binaries,
    get_ffmpeg_version,
    popen_no_window_kwargs,
)
from morphix_core.gpu_detection import (  # noqa: F401
    detect_amd,
    detect_cuda,
    detect_device_info,
    detect_intel,
    get_available_devices,
    resolve_device_info,
)
from morphix_core.settings import read_settings, write_settings  # noqa: F401
from morphix_core.validation import (  # noqa: F401
    check_low_compression_ratio,
    check_target_exceeds_file_size,
    check_trim_values,
)


def run(
    input_path=None,
    max_mb=None,
    output_path=None,
    quality="medium",
    resolution=None,
    device_preference="auto",
    overwrite=True,
    disable_logs=True,
    progress=True,
    progress_cb=None,
    start: float | None = None,
    end: float | None = None,
    warning_cb=None,
    encoder_override: str | None = None,
    *,
    config: CompressConfig | None = None,
):
    """Backwards-compatible entry point used by CLI and UI.

    Accepts either individual kwargs or a pre-built CompressConfig via the
    config keyword argument. If config is provided, all other kwargs are ignored.
    """
    if config is None:
        config = CompressConfig(
            input_path=input_path,
            max_mb=max_mb,
            output_path=output_path,
            quality=quality,
            resolution=resolution,
            device_preference=device_preference,
            overwrite=overwrite,
            disable_logs=disable_logs,
            progress=progress,
            progress_cb=progress_cb,
            start=start,
            end=end,
            warning_cb=warning_cb,
            encoder_override=encoder_override,
        )
    ctx = RunContext(config)
    return ctx.execute()
