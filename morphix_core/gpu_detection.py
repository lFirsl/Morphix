"""GPU detection — vendor registry pattern for device discovery."""

from __future__ import annotations

import os
import shutil
import subprocess

from morphix_core.ffmpeg_utils import find_ffmpeg_binaries, popen_no_window_kwargs

# ---------------------------------------------------------------------------
# Per-vendor detection functions
# ---------------------------------------------------------------------------


def detect_cuda() -> bool:
    """Detect CUDA capability using nvidia-smi."""
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


def detect_amd() -> bool:
    """Detect AMD GPU via rocm-smi (Linux) or WMI query (Windows)."""
    if shutil.which("rocm-smi") is not None:
        try:
            result = subprocess.run(
                ["rocm-smi"],
                check=False,
                capture_output=True,
                text=True,
                **popen_no_window_kwargs(),
            )
            if result.returncode == 0:
                return True
        except OSError:
            pass

    if os.name == "nt":
        try:
            import wmi  # type: ignore

            c = wmi.WMI()
            for adapter in c.Win32_VideoController():
                name = (adapter.Name or "").upper()
                if "AMD" in name or "RADEON" in name or "ATI" in name:
                    return True
        except Exception:
            pass

    return False


def detect_intel() -> bool:
    """Detect Intel GPU via WMI query (Windows) or registry check."""
    if os.name == "nt":
        try:
            import wmi  # type: ignore

            c = wmi.WMI()
            for adapter in c.Win32_VideoController():
                name = (adapter.Name or "").upper()
                if "INTEL" in name:
                    return True
        except Exception:
            pass

        try:
            import winreg  # type: ignore

            key_path = (
                r"SYSTEM\CurrentControlSet\Control\Class"
                r"\{4d36e968-e325-11ce-bfc1-08002be10318}"
            )
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, key_path
            ) as base_key:
                i = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(base_key, i)
                        with winreg.OpenKey(base_key, sub_name) as sub_key:
                            try:
                                desc, _ = winreg.QueryValueEx(
                                    sub_key, "DriverDesc"
                                )
                                if "INTEL" in str(desc).upper():
                                    return True
                            except FileNotFoundError:
                                pass
                        i += 1
                    except OSError:
                        break
        except Exception:
            pass

    return False


# ---------------------------------------------------------------------------
# Vendor registry — data-driven dispatch
# ---------------------------------------------------------------------------

# Each entry: (key, detect_fn_name, label, hwaccel)
# Using function names (not references) so that unittest.mock.patch works correctly.
_VENDORS: list[tuple[str, str, str, str]] = [
    ("nvidia", "detect_cuda", "NVIDIA GPU", "cuda"),
    ("amd", "detect_amd", "AMD GPU", "amf"),
    ("intel", "detect_intel", "Intel GPU", "qsv"),
]


def _get_detect_fn(name: str):
    """Look up a detection function by name from this module."""
    import morphix_core.gpu_detection as _self

    return getattr(_self, name)


# ---------------------------------------------------------------------------
# NVENC-specific probe (requires actual ffmpeg encode attempt)
# ---------------------------------------------------------------------------


def check_nvenc_usable(ffmpeg_path: str | None = None) -> bool:
    """Probe whether h264_nvenc actually works (drivers new enough)."""
    if not ffmpeg_path:
        ffmpeg_path, _, _ = find_ffmpeg_binaries()
    if not ffmpeg_path:
        return False
    try:
        result = subprocess.run(
            [
                ffmpeg_path,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "nullsrc=s=256x256:d=0.1",
                "-c:v",
                "h264_nvenc",
                "-f",
                "null",
                "NUL",
            ],
            check=False,
            capture_output=True,
            **popen_no_window_kwargs(),
        )
    except OSError:
        return False
    return result.returncode == 0


# ---------------------------------------------------------------------------
# Public API — built on the vendor registry
# ---------------------------------------------------------------------------


def detect_device_info() -> tuple[str, str | None]:
    """Return (label, hwaccel) for the best available device."""
    for _key, detect_fn_name, label, hwaccel in _VENDORS:
        try:
            if _get_detect_fn(detect_fn_name)():
                return label, hwaccel
        except Exception:
            continue
    return "CPU", None


def resolve_device_info(preference: str) -> tuple[str, str | None]:
    """Resolve a device preference into (label, hwaccel).

    Args:
        preference: "auto", "nvidia", "amd", "intel", or "cpu"

    Returns:
        (device_label, hwaccel_string_or_None)
    """
    if preference == "cpu":
        return "CPU", None

    if preference == "auto":
        return detect_device_info()

    # Specific vendor requested — look up in registry.
    for key, detect_fn_name, label, hwaccel in _VENDORS:
        if key == preference:
            try:
                if _get_detect_fn(detect_fn_name)():
                    return label, hwaccel
            except Exception:
                pass
            return "CPU", None

    # Unknown preference — fall back to auto.
    return detect_device_info()


def get_available_devices() -> list[tuple[str, str, bool]]:
    """Return all device options with availability flag.

    Returns a list of (key, display_label, is_available) tuples.
    Always ends with ("cpu", "CPU", True).
    """
    devices: list[tuple[str, str, bool]] = []

    # NVIDIA gets special handling — check if nvenc actually works.
    nvidia_available = False
    nvidia_label = "NVIDIA GPU"
    try:
        if detect_cuda():
            if check_nvenc_usable():
                nvidia_available = True
            else:
                nvidia_label = "NVIDIA GPU (update drivers or ffmpeg)"
        else:
            nvidia_label = "NVIDIA GPU (not detected)"
    except Exception:
        nvidia_label = "NVIDIA GPU (not detected)"
    devices.append(("nvidia", nvidia_label, nvidia_available))

    devices.append(("cpu", "CPU", True))
    return devices
