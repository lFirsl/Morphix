import os
import subprocess
import sys

from morphix_core.cli_args import parse_args
from morphix_core.core import run
from morphix_core.validation import (  # noqa: F401
    check_low_compression_ratio,
    check_target_exceeds_file_size,
    check_trim_values,
)


def main():
    args = parse_args()

    if args.no_console and os.name == "nt":
        relaunch_args = [sys.executable, "-m", "morphix_core.cli"]
        relaunch_args += [arg for arg in sys.argv[1:] if arg != "--no-console"]
        subprocess.Popen(
            relaunch_args,
            creationflags=subprocess.CREATE_NO_WINDOW,
            cwd=os.getcwd(),
        )
        return

    try:
        check_target_exceeds_file_size(args.max_mb, args.input)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if check_low_compression_ratio(args.max_mb, args.input):
        print(
            "Warning: The target size is less than 3% of the original file size. "
            "The output quality will likely be very poor. "
            "Consider a target of at least 5% of the original "
            "file size for a viewable result.",
            file=sys.stderr,
        )

    # Validate trim values when both start and end are provided
    # (we don't yet have video metadata in CLI).
    if args.start is not None and args.end is not None:
        ok, msg = check_trim_values(args.start, args.end, float("inf"))
        if not ok:
            print(f"Error: {msg}", file=sys.stderr)
            sys.exit(1)

    run(
        input_path=args.input,
        max_mb=args.max_mb,
        output_path=args.output,
        quality=args.quality,
        resolution=args.resolution,
        device_preference="auto",
        overwrite=args.overwrite,
        disable_logs=args.disable_logs,
        progress=args.progress,
        progress_cb=None,
        start=args.start,
        end=args.end,
    )


if __name__ == "__main__":
    main()
