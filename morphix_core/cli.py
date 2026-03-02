import os
import subprocess
import sys

from morphix_core.cli_args import parse_args
from morphix_core.core import run


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

    run(
        input_path=args.input,
        max_mb=args.max_mb,
        output_path=args.output,
        quality=args.quality,
        resolution=args.resolution,
        overwrite=args.overwrite,
        disable_logs=args.disable_logs,
        progress=args.progress,
        progress_cb=None,
    )


if __name__ == "__main__":
    main()
