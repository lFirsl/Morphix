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
    """Plain widget stub that tracks state, text and grid placement."""

    def __init__(self, *args, **kwargs):
        self._state = "normal"
        self._text = kwargs.get("text", "")
        self._grid_info = {}  # tracked from grid() calls

    def grid(self, *a, **kw):
        self._grid_info = dict(kw)  # Tk stores only the last placement args

    def grid_remove(self):
        """Hide widget while preserving geometry for later restore."""
        self._grid_info = {}

    def grid_forget(self):
        """Hide widget and remove from layout."""
        self._grid_info = {}

    def pack(self, *a, **kw):
        pass

    def config(self, **kwargs):
        if "state" in kwargs:
            self._state = kwargs["state"]
        if "text" in kwargs:
            self._text = kwargs["text"]

    def configure(self, **kwargs):
        self.config(**kwargs)

    def grid_info(self, *a, **kw):
        return self._grid_info

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
class _FakeBooleanVar:
    def __init__(self, value=False):
        self._value = bool(value)
    def get(self):
        return self._value
    def set(self, value):
        self._value = bool(value)
_tk_mod.BooleanVar = _FakeBooleanVar
_tk_mod.Label = _FakeWidget
_tk_mod.Checkbutton = _FakeWidget
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


# ===========================================================================
# Trim Feature UI Tests
# ===========================================================================


class TestMorphixUITrimControls(unittest.TestCase):
    """Trim checkbox and time entry behavior."""

    def setUp(self):
        self.app, _ = _make_app()

    def test_trim_checkbox_exists_and_unchecked(self):
        """The trim checkbox is rendered on startup, unchecked."""
        assert hasattr(self.app, "trim_enabled_var")
        assert self.app.trim_enabled_var.get() is False

    def test_time_entries_exist(self):
        """Time entry widgets exist after _build_ui."""
        assert hasattr(self.app, "trim_frame")
        assert hasattr(self.app, "trim_start_entry")
        assert hasattr(self.app, "trim_end_entry")

    def test_time_entries_hidden_by_default(self):
        """Time entry frame is not visible when UI initializes."""
        grid_info = self.app.trim_frame.grid_info()
        assert grid_info == {} or grid_info.get("row") is None

    def test_time_entries_visible_when_checked(self):
        """Time entry frame becomes visible when trim is enabled."""
        self.app.trim_enabled_var.set(True)
        self.app._on_trim_toggle()
        grid_info = self.app.trim_frame.grid_info()
        assert grid_info.get("row") == 6

    def test_time_entries_hidden_when_unchecked(self):
        """Time entry frame hides when trim is disabled."""
        self.app.trim_enabled_var.set(True)
        self.app._on_trim_toggle()
        self.app.trim_enabled_var.set(False)
        self.app._on_trim_toggle()
        grid_info = self.app.trim_frame.grid_info()
        assert grid_info == {} or grid_info.get("row") is None


class TestMorphixUITrimHelpers(unittest.TestCase):
    """Trim helper methods correctness."""

    def setUp(self):
        self.app, _ = _make_app()

    def test_parse_time_mmss(self):
        assert self.app._parse_time("0:25") == 25.0
        assert self.app._parse_time("1:30") == 90.0
        assert self.app._parse_time("10:00") == 600.0

    def test_parse_time_hhmmss(self):
        assert self.app._parse_time("1:05:30") == 3930.0
        assert self.app._parse_time("0:00:00") == 0.0

    def test_format_time(self):
        # _format_time is zero-padded HH:MM:SS
        assert self.app._format_time(0) == "00:00:00"
        assert self.app._format_time(90) == "00:01:30"
        assert self.app._format_time(3661) == "01:01:01"


if __name__ == "__main__":
    unittest.main()
