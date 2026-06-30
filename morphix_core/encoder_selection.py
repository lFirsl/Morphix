"""Encoder selection logic — picks the best available H.264 encoder."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EncoderConfig:
    """Configuration for a single encoder option."""

    name: str
    strategy: str
    required_device: str | None


ENCODER_PRIORITY: list[EncoderConfig] = [
    EncoderConfig("h264_nvenc", "nvenc_multipass", "nvidia"),
    # Future: EncoderConfig("h264_amf", "single_pass_cbr", "amd"),
    # Future: EncoderConfig("h264_qsv", "single_pass_cbr", "intel"),
    EncoderConfig("libx264", "two_pass", None),
    EncoderConfig("libopenh264", "single_pass_cbr", None),
]

OPENH264_WARNING = (
    "No GPU or licensed ffmpeg detected \u2014 falling back to OpenH264,"
    " which produces lower quality output. See Help \u2192 About FFmpeg"
    " for instructions on how to get better encoding quality."
)

SAFETY_MARGIN = 0.85  # For single-pass encoders, target 85% of calculated bitrate.


def select_encoder(
    available_encoders: set[str],
    device_preference: str,
    detected_device: str | None,
) -> tuple[str, str]:
    """Select the best encoder based on availability and device.

    Args:
        available_encoders: set of encoder names from detect_available_encoders()
        device_preference: user preference ("auto", "nvidia", "cpu")
        detected_device: what was actually detected ("nvidia", None, etc.)

    Returns:
        (encoder_name, strategy) or raises RuntimeError if none available.
    """
    for encoder in ENCODER_PRIORITY:
        if encoder.name not in available_encoders:
            continue
        if encoder.required_device is not None:
            if device_preference == "cpu":
                continue
            if (
                device_preference != "auto"
                and device_preference != encoder.required_device
            ):
                continue
            if detected_device != encoder.required_device:
                continue
        return encoder.name, encoder.strategy

    raise RuntimeError(
        "No compatible H.264 encoder found. Install ffmpeg with "
        "libx264 or use a supported GPU."
    )
