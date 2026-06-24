"""Download LGPL ffmpeg binaries from BtbN and place them in ffmpeg_binaries/bin/."""

import io
import os
import zipfile
from urllib.request import urlopen

URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases"
    "/download/latest/ffmpeg-master-latest-win64-lgpl.zip"
)
DEST = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "ffmpeg_binaries", "bin")
)


def main():
    os.makedirs(DEST, exist_ok=True)
    print("Downloading LGPL ffmpeg from BtbN...")
    data = urlopen(URL).read()
    print(f"Extracting to {DEST}...")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            basename = os.path.basename(name)
            if basename in ("ffmpeg.exe", "ffprobe.exe"):
                with open(os.path.join(DEST, basename), "wb") as f:
                    f.write(zf.read(name))
                print(f"  {basename}")
    print("Done.")


if __name__ == "__main__":
    main()
