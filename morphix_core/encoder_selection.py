"""Encoder selection logic — picks the best available H.264 encoder."""

# Encoder configs: (name, strategy, required_device)
# required_device: None means CPU, "nvidia" means NVIDIA GPU, etc.
# Strategy: "two_pass", "nvenc_multipass", "single_pass_cbr"
ENCODER_PRIORITY = [
    ("h264_nvenc", "nvenc_multipass", "nvidia"),
    # Future: ("h264_amf", "single_pass_cbr", "amd"),
    # Future: ("h264_qsv", "single_pass_cbr", "intel"),
    ("libx264", "two_pass", None),
    ("libopenh264", "single_pass_cbr", None),
]

OPENH264_WARNING = (
    "No GPU or licensed ffmpeg detected \u2014 falling back to OpenH264,"
    " which produces lower quality output. For better results, download"
    " ffmpeg from https://ffmpeg.org/download.html and place ffmpeg.exe"
    " in the same folder as Morphix."
)

SAFETY_MARGIN = 0.85  # For single-pass encoders, target 85% of calculated bitrate.


def select_encoder(
    available_encoders: set, device_preference: str, detected_device: str | None
) -> tuple[str, str]:
    """Select the best encoder based on availability and device.

    Args:
        available_encoders: set of encoder names from detect_available_encoders()
        device_preference: user preference ("auto", "nvidia", "cpu")
        detected_device: what was actually detected ("nvidia", None, etc.)

    Returns:
        (encoder_name, strategy) or raises RuntimeError if none available.
    """
    for encoder_name, strategy, required_device in ENCODER_PRIORITY:
        if encoder_name not in available_encoders:
            continue
        if required_device is not None:
            # GPU encoder — check device matches
            if device_preference == "cpu":
                continue
            if device_preference != "auto" and device_preference != required_device:
                continue
            if detected_device != required_device:
                continue
        return encoder_name, strategy

    raise RuntimeError(
        "No compatible H.264 encoder found. Install ffmpeg with "
        "libx264 or use a supported GPU."
    )
