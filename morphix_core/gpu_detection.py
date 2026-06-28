import os
import shutil
import subprocess

from morphix_core.ffmpeg_utils import find_ffmpeg_binaries, popen_no_window_kwargs


def check_nvenc_usable(ffmpeg_path=None):
    """Probe whether h264_nvenc actually works (drivers new enough)."""
    if not ffmpeg_path:
        ffmpeg_path, _, _ = find_ffmpeg_binaries()
    if not ffmpeg_path:
        return False
    try:
        result = subprocess.run(
            [
                ffmpeg_path, "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
                "-c:v", "h264_nvenc", "-f", "null", "NUL",
            ],
            check=False,
            capture_output=True,
            **popen_no_window_kwargs(),
        )
    except OSError:
        return False
    return result.returncode == 0


def detect_cuda():
    # Detect CUDA capability using nvidia-smi if present.
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


def detect_amd():
    # Detect AMD GPU via rocm-smi (Linux) or WMI query (Windows).
    # Try rocm-smi first (Linux/ROCm environments).
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

    # Fall back to WMI query on Windows.
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


def detect_intel():
    # Detect Intel GPU via WMI query (Windows) or registry check.
    if os.name == "nt":
        # Try WMI first.
        try:
            import wmi  # type: ignore

            c = wmi.WMI()
            for adapter in c.Win32_VideoController():
                name = (adapter.Name or "").upper()
                if "INTEL" in name:
                    return True
        except Exception:
            pass

        # Fall back to registry query.
        try:
            import winreg  # type: ignore

            key_path = (
                r"SYSTEM\CurrentControlSet\Control\Class"
                r"\{4d36e968-e325-11ce-bfc1-08002be10318}"
            )
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as base_key:
                i = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(base_key, i)
                        with winreg.OpenKey(base_key, sub_name) as sub_key:
                            try:
                                desc, _ = winreg.QueryValueEx(sub_key, "DriverDesc")
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


def detect_device_info():
    # Return a user-friendly device label and a preferred hwaccel string.
    # Try each vendor in priority order; catch all exceptions per vendor.
    try:
        if detect_cuda():
            return "NVIDIA GPU", "cuda"
    except Exception:
        pass

    try:
        if detect_amd():
            return "AMD GPU", "amf"
    except Exception:
        pass

    try:
        if detect_intel():
            return "Intel GPU", "qsv"
    except Exception:
        pass

    return "CPU", None


def get_available_devices():
    # Return all device options with availability flag.
    # NOTE: AMD and Intel support is scaffolded but not exposed yet.
    devices = []

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


def resolve_device_info(preference):
    # Resolve a device preference into a label and hwaccel string.
    if preference == "cpu":
        return "CPU", None
    if preference == "nvidia":
        try:
            if detect_cuda():
                return "NVIDIA GPU", "cuda"
        except Exception:
            pass
        return "CPU", None
    if preference == "amd":
        try:
            if detect_amd():
                return "AMD GPU", "amf"
        except Exception:
            pass
        return "CPU", None
    if preference == "intel":
        try:
            if detect_intel():
                return "Intel GPU", "qsv"
        except Exception:
            pass
        return "CPU", None
    # "auto" or unknown preference: use best available device.
    return detect_device_info()
