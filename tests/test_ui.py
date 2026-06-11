"""Unit tests for MorphixUI controls and state (Requirements 12.1–12.15, 16.1–16.4)."""

import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Tkinter headless setup — must happen before any tkinter import.
# We replace tkinter with plain Python objects so no display is needed.
# ---------------------------------------------------------------------------


class _FakeStringVar:
    """Minimal StringVar that stores a value and fires write traces."""

    def __init__(self, value=""):
        self._value = value
        self._traces = []

    def get(self):
        return self._value

    def set(self, value):
        self._value = value
        for mode, cb in self._traces:
            if mode == "write":
                try:
                    cb()
                except Exception:
                    pass

    def trace_add(self, mode, callback):
        self._traces.append((mode, callback))


class _FakeWidget:
    """Plain widget stub that tracks state and text via config()."""

    def __init__(self, *args, **kwargs):
        self._state = "normal"
        self._text = kwargs.get("text", "")

    def grid(self, *a, **kw):
        pass

    def pack(self, *a, **kw):
        pass

    def config(self, **kwargs):
        if "state" in kwargs:
            self._state = kwargs["state"]
        if "text" in kwargs:
            self._text = kwargs["text"]

    def configure(self, **kwargs):
        self.config(**kwargs)

    # Allow attribute access for things like .grid_columnconfigure
    def __getattr__(self, name):
        return lambda *a, **kw: None


class _FakeTk(_FakeWidget):
    """Fake root Tk window — MorphixUI inherits from tk.Tk."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def after(self, delay, func=None, *args):
        """Execute callback immediately (synchronous for tests)."""
        if func is not None:
            func(*args)

    def title(self, *a):
        pass

    def geometry(self, *a):
        pass

    def minsize(self, *a):
        pass

    def resizable(self, *a):
        pass

    def grid_columnconfigure(self, *a, **kw):
        pass

    def mainloop(self):
        pass

    def destroy(self):
        pass


# Build the fake tkinter module
_tk_mod = types.ModuleType("tkinter")
_tk_mod.Tk = _FakeTk
_tk_mod.StringVar = _FakeStringVar
_tk_mod.Label = _FakeWidget
_tk_mod.Entry = _FakeWidget
_tk_mod.Button = _FakeWidget
_tk_mod.OptionMenu = _FakeWidget
_tk_mod.Frame = _FakeWidget
_tk_mod.Message = _FakeWidget
_tk_mod.Toplevel = _FakeWidget

_filedialog_mod = types.ModuleType("tkinter.filedialog")
_filedialog_mod.askopenfilename = MagicMock(return_value="")
_filedialog_mod.asksaveasfilename = MagicMock(return_value="")
_tk_mod.filedialog = _filedialog_mod

_messagebox_mod = types.ModuleType("tkinter.messagebox")
_messagebox_mod.showerror = MagicMock()
_messagebox_mod.askokcancel = MagicMock(return_value=True)
_tk_mod.messagebox = _messagebox_mod

sys.modules["tkinter"] = _tk_mod
sys.modules["tkinter.filedialog"] = _filedialog_mod
sys.modules["tkinter.messagebox"] = _messagebox_mod

# ---------------------------------------------------------------------------
# Helper: apply all core patches needed to instantiate MorphixUI
# ---------------------------------------------------------------------------


def _core_patches():
    """Return a patch.multiple context manager for all morphix_core.core functions."""
    return patch.multiple(
        "morphix_core.core",
        get_available_devices=MagicMock(return_value=[("cpu", "CPU")]),
        find_ffmpeg_binaries=MagicMock(
            return_value=("/fake/ffmpeg", "/fake/ffprobe", "bundled")
        ),
        get_ffmpeg_version=MagicMock(return_value="6.0"),
        resolve_device_info=MagicMock(return_value=("CPU", None)),
        run=MagicMock(),
    )


def _make_app(input_file=None):
    """Instantiate MorphixUI with all core functions mocked."""
    import importlib
    import morphix_ui.ui_app as ui_mod

    with _core_patches():
        importlib.reload(ui_mod)
        app = ui_mod.MorphixUI(input_file=input_file)
    return app, ui_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMorphixUIDefaults(unittest.TestCase):
    """Default field values on startup."""

    def setUp(self):
        self.app, self.ui_mod = _make_app()

    # --- Test 1: Target size pre-populated with 20 ---

    def test_target_size_default_is_20(self):
        """Target size field is pre-populated with '20' on startup (Req 12.4, 16.2)."""
        self.assertEqual(self.app.size_var.get(), "20")

    # --- Test 2: Unit selector defaults to MB ---

    def test_unit_selector_defaults_to_mb(self):
        """Unit selector defaults to 'MB' on startup (Req 15.1, 16.2)."""
        self.assertEqual(self.app.unit_var.get(), "MB")


class TestMorphixUIValidation(unittest.TestCase):
    """Input validation error dialogs."""

    def setUp(self):
        self.app, self.ui_mod = _make_app()
        _messagebox_mod.showerror.reset_mock()

    # --- Test 3: Error dialog when input file is missing ---

    def test_error_dialog_when_input_file_missing(self):
        """Error dialog shown when Compress clicked with no input file (Req 12.6)."""
        self.app.input_var.set("")
        self.app.size_var.set("20")

        with patch.object(self.ui_mod, "messagebox") as mock_mb:
            self.app.run_compress()
            mock_mb.showerror.assert_called_once()

    # --- Test 4: Error dialog when target size is missing ---

    def test_error_dialog_when_target_size_missing(self):
        """Error dialog shown when Compress clicked with no target size (Req 12.7)."""
        self.app.input_var.set("/some/video.mp4")
        self.app.size_var.set("")

        with patch.object(self.ui_mod, "messagebox") as mock_mb:
            self.app.run_compress()
            mock_mb.showerror.assert_called_once()


class TestMorphixUIOutputAutoPopulate(unittest.TestCase):
    """Automatic output path population."""

    def setUp(self):
        self.app, self.ui_mod = _make_app()

    # --- Test 5: Output field auto-populated with -morphix-compressed suffix ---

    def test_output_auto_populated_with_morphix_compressed_suffix(self):
        """Output field auto-populated from input filename with '-morphix-compressed' suffix (Req 12.3)."""
        self.app._set_output_auto("/videos/myclip.mp4")
        output = self.app.output_var.get()
        self.assertIn("-morphix-compressed", output)
        self.assertTrue(output.endswith(".mp4"))
        self.assertIn("myclip", output)

    def test_output_auto_populated_preserves_extension(self):
        """Auto-populated output preserves the original file extension."""
        self.app._set_output_auto("/videos/myclip.mkv")
        output = self.app.output_var.get()
        self.assertTrue(output.endswith(".mkv"))

    def test_output_auto_populated_from_input_with_no_extension(self):
        """Auto-populated output uses .mp4 when input has no extension."""
        self.app._set_output_auto("/videos/rawvideo")
        output = self.app.output_var.get()
        self.assertTrue(output.endswith(".mp4"))

    def test_output_auto_populated_on_startup_with_input_file(self):
        """Output field is pre-populated when input_file is passed at construction."""
        app, _ = _make_app(input_file="/videos/startup.mp4")
        output = app.output_var.get()
        self.assertIn("-morphix-compressed", output)
        self.assertIn("startup", output)


class TestMorphixUIControlState(unittest.TestCase):
    """Control enable/disable during compression."""

    def setUp(self):
        self.app, self.ui_mod = _make_app()

    # --- Test 6: Controls disabled during compression, re-enabled on completion ---

    def test_controls_disabled_during_compression_and_reenabled_on_completion(self):
        """Controls are disabled during compression and re-enabled on completion (Req 12.8, 12.10)."""
        app = self.app

        app.input_var.set("/videos/test.mp4")
        app.size_var.set("20")

        states_during = {}
        worker_started = threading.Event()
        worker_may_finish = threading.Event()

        def fake_run(*args, **kwargs):
            worker_started.set()
            # Capture widget states while "running"
            states_during["compress_btn"] = app.compress_btn._state
            states_during["input_entry"] = app.input_entry._state
            states_during["device_menu"] = app.device_menu._state
            worker_may_finish.wait(timeout=3)

        with patch.object(self.ui_mod, "run", side_effect=fake_run), \
             patch.object(self.ui_mod, "check_target_exceeds_file_size"), \
             patch.object(self.ui_mod, "check_low_compression_ratio", return_value=False):
            app.run_compress()
            worker_started.wait(timeout=3)
            worker_may_finish.set()

        # Give the thread time to finish and re-enable controls
        time.sleep(0.15)

        # During compression, controls should have been disabled
        self.assertEqual(states_during.get("compress_btn"), "disabled",
                         "compress_btn should be disabled during compression")
        self.assertEqual(states_during.get("input_entry"), "disabled",
                         "input_entry should be disabled during compression")
        self.assertEqual(states_during.get("device_menu"), "disabled",
                         "device_menu should be disabled during compression")

        # After completion, controls should be re-enabled
        self.assertEqual(app.compress_btn._state, "normal",
                         "compress_btn should be normal after completion")
        self.assertEqual(app.input_entry._state, "normal",
                         "input_entry should be normal after completion")
        self.assertEqual(app.device_menu._state, "normal",
                         "device_menu should be normal after completion")

    # --- Test 7: Controls re-enabled on error ---

    def test_controls_reenabled_on_error(self):
        """Controls are re-enabled when compression raises an exception (Req 12.11)."""
        app = self.app
        app.input_var.set("/videos/test.mp4")
        app.size_var.set("20")

        def fake_run_raises(*args, **kwargs):
            raise RuntimeError("ffmpeg failed")

        with patch.object(self.ui_mod, "run", side_effect=fake_run_raises), \
             patch.object(self.ui_mod, "messagebox"), \
             patch.object(self.ui_mod, "check_target_exceeds_file_size"), \
             patch.object(self.ui_mod, "check_low_compression_ratio", return_value=False):
            app.run_compress()

        # Give the background thread time to finish
        time.sleep(0.15)

        self.assertEqual(app.compress_btn._state, "normal",
                         "compress_btn should be re-enabled after error")
        self.assertEqual(app.input_entry._state, "normal",
                         "input_entry should be re-enabled after error")
        self.assertEqual(app.device_menu._state, "normal",
                         "device_menu should be re-enabled after error")
        self.assertFalse(app._is_running,
                         "_is_running should be False after error")


if __name__ == "__main__":
    unittest.main()
