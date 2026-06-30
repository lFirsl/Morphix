"""Background compression worker for Morphix UI."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from morphix_core.core import (
    detect_available_encoders,
    find_ffmpeg_binaries,
    resolve_device_info,
    run,
    select_encoder,
)


@dataclass
class CompressionCallbacks:
    """Callbacks the worker invokes to communicate with the UI."""

    on_progress: Callable[[float, str], None] | None = None
    on_status: Callable[[str], None] | None = None
    on_done: Callable[[], None] | None = None
    on_error: Callable[[str], None] | None = None
    on_warning: Callable[[str], None] | None = None
    on_encoder_info: Callable[[str, str], None] | None = None


def start_compression(
    *,
    input_path: str,
    output_path: str | None,
    size_value: float,
    device_preference: str,
    encoder_override: str | None,
    trim_start: float | None,
    trim_end: float | None,
    callbacks: CompressionCallbacks,
) -> threading.Thread:
    """Spawn a daemon thread to run the compression.

    Args:
        input_path: Path to input video.
        output_path: Explicit output path or None for auto.
        size_value: Target size in MB.
        device_preference: Device key ("auto", "nvidia", "cpu", etc.).
        encoder_override: Encoder name or None for auto-selection.
        trim_start: Trim start in seconds, or None.
        trim_end: Trim end in seconds, or None.
        callbacks: CompressionCallbacks instance.

    Returns:
        The started daemon thread.
    """

    def _progress_cb(pct: float, phase: str) -> None:
        if phase == "PASS1":
            msg = f"Pass 1/2: Analyzing video... {pct:.1f}%"
        elif phase == "PASS2":
            msg = f"Pass 2/2: Encoding final output... {pct:.1f}%"
        elif phase == "CRF":
            msg = f"Encoding (quality-preserving)... {pct:.1f}%"
        else:
            msg = f"Encoding... {pct:.1f}%"
        if callbacks.on_status:
            callbacks.on_status(msg)

    def _on_warning(msg: str) -> None:
        if callbacks.on_warning:
            callbacks.on_warning(msg)

    def worker() -> None:
        try:
            # Resolve encoder info for UI display.
            device_label, _ = resolve_device_info(device_preference)
            detected = "nvidia" if "NVIDIA" in device_label else None
            ffmpeg_path, _, _ = find_ffmpeg_binaries()
            available = detect_available_encoders(ffmpeg_path)

            if encoder_override and encoder_override != "Auto":
                enc_name = encoder_override
            else:
                try:
                    enc_name, _ = select_encoder(
                        available, device_preference, detected
                    )
                except RuntimeError:
                    enc_name = "none"

            if callbacks.on_encoder_info:
                callbacks.on_encoder_info(device_label, enc_name)

            run(
                input_path=input_path,
                max_mb=size_value,
                output_path=output_path or None,
                quality="medium",
                resolution=None,
                device_preference=device_preference,
                overwrite=True,
                disable_logs=True,
                progress=True,
                progress_cb=_progress_cb,
                start=trim_start,
                end=trim_end,
                warning_cb=_on_warning,
                encoder_override=encoder_override,
            )

            if callbacks.on_status:
                callbacks.on_status("Done.")
            if callbacks.on_done:
                callbacks.on_done()

        except Exception as exc:
            if callbacks.on_status:
                callbacks.on_status(f"Failed: {exc}")
            if callbacks.on_error:
                callbacks.on_error(str(exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread
