import os
import shutil
import subprocess
import ffmpeg
from cli_args import parse_args

print("Morphix Prototype")

# Compression to specific size now.

def target_kbps_for_size_mb(size_mb, duration_s, audio_kbps=128):
    target_bytes = size_mb * 1_000_000  # MB
    # Convert target size to kbps: bytes -> bits -> bps -> kbps.
    total_kbps = (target_bytes * 8) / duration_s / 1000
    video_kbps = max(total_kbps - audio_kbps, 1)
    return int(video_kbps)

def detect_cuda():
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and bool(result.stdout.strip())

def main():
    args = parse_args()
    input_path = os.path.abspath(args.input)
    input_dir = os.path.dirname(input_path)
    base_name, ext = os.path.splitext(os.path.basename(input_path))
    if not ext:
        ext = ".mp4"
    if args.output:
        output_path = args.output
    else:
        size_label = str(args.max_mb).rstrip("0").rstrip(".")
        output_path = os.path.join(input_dir, f"{base_name}_{size_label}mb{ext}")

    print(f"Proceeding with a compression down to a size of {args.max_mb}mb")

    duration = float(ffmpeg.probe(args.input)["format"]["duration"])
    video_kbps = target_kbps_for_size_mb(args.max_mb, duration, audio_kbps=128)
    hwaccel = "cuda" if detect_cuda() else None
    print(f"Hardware acceleration present? - {hwaccel}")
    input_kwargs = {"hwaccel": hwaccel} if hwaccel else {}

    log_dir = os.path.join(input_dir, ".output")
    os.makedirs(log_dir, exist_ok=True)
    passlog_path = os.path.join(log_dir, "ffmpeg2pass")

    def run_ffmpeg(stream):
        try:
            stream.run(quiet=args.disable_logs, overwrite_output=args.overwrite)
        except ffmpeg.Error as exc:
            err_path = os.path.join(log_dir, "ffmpeg-error.log")
            with open(err_path, "wb") as f:
                if exc.stderr:
                    f.write(exc.stderr)
                else:
                    f.write(b"No stderr captured from ffmpeg.\n")
            print(f"FFmpeg failed. See: {err_path}")
            raise

    # pass 1
    run_ffmpeg(
        ffmpeg
        .input(args.input, **input_kwargs)
        .output(
            "NUL",
            vcodec="libx264",
            preset="medium",
            **{"b:v": f"{video_kbps}k"},
            **{"pass": 1},
            **{"passlogfile": passlog_path},
            an=None,
            f="mp4")
    )

    # pass 2
    run_ffmpeg(
        ffmpeg
        .input(args.input, **input_kwargs)
        .output(
            output_path,
            vcodec="libx264",
            preset="medium",
            **{"b:v": f"{video_kbps}k"},
            **{"pass": 2},
            **{"passlogfile": passlog_path},
            acodec="aac",
            audio_bitrate="128k",
        )
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


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Error: {exc}")
        try:
            input("Press Enter to exit...")
        except EOFError:
            pass
