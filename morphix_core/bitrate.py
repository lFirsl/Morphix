def target_kbps_for_size_mb(size_mb: float, duration_s: float, audio_kbps: int) -> int:
    return max(int((size_mb * 1_000_000 * 8) / duration_s / 1000) - audio_kbps, 1)


def parse_fps(rate_text):
    # Parse "num/den" or float fps strings from ffprobe.
    if not rate_text or rate_text == "0/0":
        return None
    if "/" in rate_text:
        num, den = rate_text.split("/", 1)
        try:
            return float(num) / float(den)
        except ValueError:
            return None
    try:
        return float(rate_text)
    except ValueError:
        return None


def clamp_even(value):
    # Ensure even dimensions for H.264 compatibility.
    value = int(round(value))
    return value if value % 2 == 0 else value - 1


def compute_scaled_resolution(width, height, fps, video_bps, target_bpp, min_height=480):
    # Determine a scaled resolution based on target bits-per-pixel-per-frame.
    if not all([width, height, fps, video_bps]):
        return None
    current_bpp = video_bps / (fps * width * height)
    if current_bpp >= target_bpp:
        return None
    target_pixels = video_bps / (fps * target_bpp)
    scale = (target_pixels / (width * height)) ** 0.5
    if scale >= 1.0:
        return None
    new_w = clamp_even(width * scale)
    new_h = clamp_even(height * scale)
    if new_h < min_height:
        # Enforce minimum height while keeping aspect ratio.
        new_h = clamp_even(min_height)
        new_w = clamp_even(new_h * (width / height))
    if new_w < 2 or new_h < 2:
        return None
    return new_w, new_h
