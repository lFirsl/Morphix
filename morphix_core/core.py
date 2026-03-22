# morphix_core/core.py — public API facade
# No logic lives here; all symbols are re-exported from submodules so that
# existing import paths (cli.py, ui_app.py, tests) continue to work unchanged.

from morphix_core.ffmpeg_utils import (  # noqa: F401
    find_ffmpeg_binaries,
    get_ffmpeg_version,
    ffprobe_media,
    popen_no_window_kwargs,
)
from morphix_core.gpu_detection import (  # noqa: F401
    detect_cuda,
    detect_amd,
    detect_intel,
    detect_device_info,
    get_available_devices,
    resolve_device_info,
)
from morphix_core.encoding import RunContext  # noqa: F401
from morphix_core.bitrate import (  # noqa: F401
    target_kbps_for_size_mb,
    compute_scaled_resolution,
    clamp_even,
    parse_fps,
)
from morphix_core.settings import read_settings, write_settings  # noqa: F401
from morphix_core.validation import (  # noqa: F401
    check_target_exceeds_file_size,
    check_low_compression_ratio,
)


def run(
    input_path,
    max_mb,
    output_path=None,
    quality="medium",
    resolution=None,
    device_preference="auto",
    overwrite=True,
    disable_logs=True,
    progress=True,
    progress_cb=None,
):
    # Backwards-compatible entry point used by CLI and UI.
    ctx = RunContext(
        input_path,
        max_mb,
        output_path=output_path,
        quality=quality,
        resolution=resolution,
        device_preference=device_preference,
        overwrite=overwrite,
        disable_logs=disable_logs,
        progress=progress,
        progress_cb=progress_cb,
    )
    return ctx.execute()
