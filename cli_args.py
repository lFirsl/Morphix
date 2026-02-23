import argparse

# This is using argparse - which is a built-in python CLI interface library
# Details here: https://docs.python.org/3/library/argparse.html

def parse_args():
    parser = argparse.ArgumentParser(description="Compress a video to a target size.")
    parser.add_argument(
        "input",
        nargs="?",
        help="Path to the input video file.",
    )
    parser.add_argument(
        "--max-mb",
        type=float,
        help="Target maximum output size in MB.",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Use test defaults for input and max-mb.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Path to the output file. Defaults to input name with _{max_mb}mb suffix.",
    )
    parser.add_argument(
        "--disable-logs",
        dest="disable_logs",
        action="store_true",
        default=True,
        help="Disable ffmpeg logging output.",
    )
    parser.add_argument(
        "--enable-logs",
        dest="disable_logs",
        action="store_false",
        help="Enable ffmpeg logging output.",
    )
    parser.add_argument(
        "--overwrite",
        dest="overwrite",
        action="store_true",
        default=True,
        help="Overwrite output file if it exists.",
    )
    parser.add_argument(
        "--no-overwrite",
        dest="overwrite",
        action="store_false",
        help="Do not overwrite output file if it exists.",
    )
    args = parser.parse_args()

    if args.test:
        if args.input is None:
            args.input = ".example_videos/Rainmaker Pre-Pop WipeOut.mp4"
        if args.max_mb is None:
            args.max_mb = 15
    else:
        if args.input is None:
            parser.error("the following arguments are required: input (or use --test)")
        if args.max_mb is None:
            parser.error("the following arguments are required: --max-mb (or use --test)")

    return args
