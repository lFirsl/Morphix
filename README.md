# Morphix

Compress any video to a target file size — in one click.

![](docs/demo.gif)

## What it does

Morphix wraps ffmpeg into a simple interface to allow you to:

1. Pick a video
2. Set a target size in MB
3. Hit Compress

It automatically selects the best encoder available on your system and handles two-pass encoding, bitrate calculation, and resolution scaling.

## Download

Grab the latest release from the [Releases page](https://github.com/lFirsl/Morphix/releases).

| Version | What's included |
|---------|----------------|
| **Morphix UI** | Full package — includes ffmpeg, works out of the box |
| **Morphix UI Lite** | Smaller download — bring your own ffmpeg (see Help → About FFmpeg in-app) |
| **Morphix CLI** | Command-line interface for scripting and automation |

## Quick Start

1. Download **Morphix UI** from the latest release
2. Extract and run `Morphix_UI.exe`
3. Select a video, set your target size, click **Compress**

That's it. Output is saved next to the original file.

## Features

- **Target size compression** — specify an exact file size in MB or GB
- **Smart encoder selection** — NVIDIA NVENC → libx264 → OpenH264, picked automatically
- **Trim & compress** — set start/end times to extract and compress a segment
- **GPU acceleration** — uses NVENC multipass when an NVIDIA GPU is detected
- **Bring your own ffmpeg** — drop a GPL ffmpeg build next to the app for libx264 support
- **CLI & GUI** — use whichever fits your workflow
- **Windows Explorer integration** — right-click context menu (MSIX install)

## Requirements

- Windows 10 or later
- **Lite version only:** ffmpeg on PATH or in a `ffmpeg/` folder next to the EXE

## For Developers

See [docs/development.md](docs/development.md) for setup, building, testing, and project structure.

## License

AGPL-3.0. See [LICENSE](LICENSE).

The bundled ffmpeg binary is the latest available LGPL build at the time of release. Users may provide their own GPL ffmpeg for additional encoder support (libx264).
