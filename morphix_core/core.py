import json
import os
import re
import shutil
import subprocess
import sys

import ffmpeg


def target_kbps_for_size_mb(size_mb, duration_s, audio_kbps=128):
    target_bytes = size_mb * 1_000_000  # MB
    # Convert target size to kbps: bytes -> bits -> bps -> kbps.
    total_kbps = (target_bytes * 8) / duration_s / 1000
    video_kbps = max(total_kbps - audio_kbps, 1)
    return int(video_kbps)


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


def detect_cuda():
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            check=False,
            capture_output=True,
            text=True,
            **popen_no_window_kwargs(),
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def popen_no_window_kwargs():
    # On Windows, suppress console windows for child processes.
    # On other OSes, start a new session to avoid attaching to the parent TTY.
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def ffprobe_media(path):
    # Run ffprobe directly so we can suppress console windows on Windows.
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    result = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        **popen_no_window_kwargs(),
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def run(
    input_path,
    max_mb,
    output_path=None,
    quality="medium",
    resolution=None,
    overwrite=True,
    disable_logs=True,
    progress=True,
    progress_cb=None,
):
    print("Morphix Prototype")

    input_path = os.path.abspath(input_path)
    input_dir = os.path.dirname(input_path)
    base_name, ext = os.path.splitext(os.path.basename(input_path))
    if not ext:
        ext = ".mp4"
    if output_path:
        output_path = output_path
    else:
        size_label = str(max_mb).rstrip("0").rstrip(".")
        output_path = os.path.join(input_dir, f"{base_name}_{size_label}mb{ext}")

    print(f"Proceeding with a compression down to a size of {max_mb}mb")

    # Use ffprobe to fetch duration and stream metadata without spawning a console.
    probe = ffprobe_media(input_path)
    duration = float(probe["format"]["duration"])
    video_kbps = target_kbps_for_size_mb(max_mb, duration, audio_kbps=128)
    video_bps = video_kbps * 1000

    hwaccel = "cuda" if detect_cuda() else None
    print(f"Hardware acceleration present? - {hwaccel}")
    input_kwargs = {"hwaccel": hwaccel} if hwaccel else {}

    # Fetch video stream info for auto-scaling decisions.
    vstream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), None)
    width = int(vstream.get("width", 0)) if vstream else 0
    height = int(vstream.get("height", 0)) if vstream else 0
    fps = parse_fps(vstream.get("avg_frame_rate") or vstream.get("r_frame_rate")) if vstream else None

    # Decide whether to apply a scale filter.
    scale_filter = None
    if resolution:
        # Manual override takes precedence.
        if "x" in resolution:
            w_str, h_str = resolution.lower().split("x", 1)
            try:
                res_w = clamp_even(int(w_str))
                res_h = clamp_even(int(h_str))
                if res_w >= 2 and res_h >= 2:
                    scale_filter = f"scale={res_w}:{res_h}"
            except ValueError:
                pass
    else:
        # Auto-scale based on bitrate-derived bpp thresholds.
        bpp_targets = {"low": 0.05, "medium": 0.07, "high": 0.10}
        target_bpp = bpp_targets.get(quality, 0.07)
        scaled = compute_scaled_resolution(width, height, fps, video_bps, target_bpp, min_height=480)
        if scaled:
            scale_filter = f"scale={scaled[0]}:{scaled[1]}"
            print(f"Auto-scaling to {scaled[0]}x{scaled[1]} for quality '{quality}'.")

    log_dir = os.path.join(input_dir, ".output")
    os.makedirs(log_dir, exist_ok=True)
    passlog_path = os.path.join(log_dir, "ffmpeg2pass")

    def render_progress(current_seconds, bar, phase):
        # Convert out_time_ms to a 0-100% progress update.
        if duration <= 0:
            return
        pct = min(max(current_seconds / duration, 0.0), 1.0) * 100.0
        if progress_cb:
            progress_cb(pct, phase)
            return
        if bar is None:
            sys.stdout.write(f"\rProgress: {pct:5.1f}%")
            sys.stdout.flush()
        else:
            bar.n = int(pct * 10)
            bar.refresh()

    def run_ffmpeg(stream, phase):
        try:
            if progress:
                bar = None
                if progress_cb is None:
                    try:
                        from tqdm import tqdm
                    except ImportError:
                        tqdm = None
                    if tqdm is not None and duration > 0:
                        bar = tqdm(total=1000, unit="‰", leave=True, desc=phase)
                stream = stream.global_args("-progress", "pipe:2", "-nostats")
                # Build the ffmpeg command and run it without showing a console window.
                cmd = ffmpeg.compile(stream, overwrite_output=overwrite)
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    **popen_no_window_kwargs(),
                )
                # Parse ffmpeg progress lines from stderr and emit progress updates.
                time_re = re.compile(r"out_time_ms=(\d+)")
                while True:
                    line = process.stderr.readline()
                    if not line:
                        break
                    text = line.decode(errors="ignore").strip()
                    match = time_re.search(text)
                    if match:
                        total = float(match.group(1)) / 1_000_000.0
                        render_progress(total, bar, phase)
                process.wait()
                if bar is not None:
                    bar.close()
                elif progress_cb is None:
                    sys.stdout.write("\n")
                if process.returncode != 0:
                    raise ffmpeg.Error("ffmpeg", process.stderr.read(), None)
            else:
                # Run without progress parsing; optionally suppress logs and console windows.
                cmd = ffmpeg.compile(stream, overwrite_output=overwrite)
                stderr_target = subprocess.DEVNULL if disable_logs else subprocess.PIPE
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL if disable_logs else None,
                    stderr=stderr_target,
                    **popen_no_window_kwargs(),
                )
                process.wait()
                if process.returncode != 0:
                    err_bytes = None
                    if process.stderr is not None:
                        err_bytes = process.stderr.read()
                    raise ffmpeg.Error("ffmpeg", err_bytes, None)
        except ffmpeg.Error as exc:
            err_path = os.path.join(log_dir, "ffmpeg-error.log")
            with open(err_path, "wb") as f:
                if exc.stderr:
                    f.write(exc.stderr)
                else:
                    f.write(b"No stderr captured from ffmpeg.\n")
            print(f"FFmpeg failed. See: {err_path}")
            raise

    # Pass 1: analysis (video only).
    pass1_input = ffmpeg.input(input_path, **input_kwargs)
    pass1_video = pass1_input.video
    if scale_filter:
        pass1_video = pass1_video.filter_("scale", *scale_filter.split("=", 1)[1].split(":"))
    run_ffmpeg(
        ffmpeg.output(
            pass1_video,
            "NUL",
            vcodec="libx264",
            preset="medium",
            **{"b:v": f"{video_kbps}k"},
            **{"pass": 1},
            **{"passlogfile": passlog_path},
            an=None,
            f="mp4"),
        "PASS1",
    )

    # Pass 2: actual encode.
    pass2_input = ffmpeg.input(input_path, **input_kwargs)
    pass2_video = pass2_input.video
    pass2_audio = pass2_input.audio
    if scale_filter:
        pass2_video = pass2_video.filter_("scale", *scale_filter.split("=", 1)[1].split(":"))
    run_ffmpeg(
        ffmpeg.output(
            pass2_video,
            pass2_audio,
            output_path,
            vcodec="libx264",
            preset="medium",
            **{"b:v": f"{video_kbps}k"},
            **{"pass": 2},
            **{"passlogfile": passlog_path},
            acodec="aac",
            audio_bitrate="128k",
        ),
        "PASS2",
    )

    for suffix in (".log", ".log.mbtree"):
        try:
            os.remove(passlog_path + suffix)
        except FileNotFoundError:
            pass

    try:
        if not os.listdir(log_dir):
            os.rmdir(log_dir)
    except OSError:
        pass

    return output_path
