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
    output_path = args.output

    print(f"Proceeding with a compression down to a size of {args.max_mb}mb")

    duration = float(ffmpeg.probe(args.input)["format"]["duration"])
    video_kbps = target_kbps_for_size_mb(args.max_mb, duration, audio_kbps=128)
    hwaccel = "cuda" if detect_cuda() else None
    print(f"Hardware acceleration present? - {hwaccel}")
    input_kwargs = {"hwaccel": hwaccel} if hwaccel else {}

    # pass 1
    (
        ffmpeg
        .input(args.input, **input_kwargs)
        .output(
            "NUL", 
            vcodec="libx264", 
            preset="medium", 
            **{"b:v": f"{video_kbps}k"}, 
            **{"pass": 1}, 
            an=None, 
            f="mp4")
        .run(quiet=args.disable_logs, overwrite_output=args.overwrite)
    )

    # pass 2
    (
        ffmpeg
        .input(args.input, **input_kwargs)
        .output(
            output_path,
            vcodec="libx264",
            preset="medium",
            **{"b:v": f"{video_kbps}k"},
            **{"pass": 2},
            acodec="aac",
            audio_bitrate="128k",
        )
        .run(quiet=args.disable_logs, overwrite_output=args.overwrite)
    )


if __name__ == "__main__":
    main()
