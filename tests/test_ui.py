"""Unit tests for MorphixUI controls and state (Requirements 12.1–12.15, 16.1–16.4)."""

import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Tkinter headless setup — must happen before any tkinter import.
# ---------------------------------------------------------------------------


class _FakeStringVar:
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
    def __init__(self, *args, **kwargs):
        self._state = "normal"
        self._text = kwargs.get("text", "")
        self._grid_info = {}

    def grid(self, *a, **kw):
        self._grid_info = dict(kw)

    def grid_remove(self):
        self._grid_info = {}

    def grid_forget(self):
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

    def grid_columnconfigure(self, *a, **kw):
        pass

    def __getattr__(self, name):
        return lambda *a, **kw: None

    def __getitem__(self, key):
        return _FakeWidget()


class _FakeTk(_FakeWidget):
    def after(self, delay, func=None, *args):
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

    def grid_rowconfigure(self, *a, **kw):
        pass

    def mainloop(self):
        pass

    def destroy(self):
        pass


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
_tk_mod.Menu = _FakeWidget

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
    return patch.multiple(
        "morphix_core.core",
        get_available_devices=MagicMock(return_value=[("cpu", "CPU", True)]),
        find_ffmpeg_binaries=MagicMock(
            return_value=("/fake/ffmpeg", "/fake/ffprobe", "bundled")
        ),
        get_ffmpeg_version=MagicMock(return_value="6.0"),
        resolve_device_info=MagicMock(return_value=("CPU", None)),
        run=MagicMock(),
    )


def _tab_patches():
    """Patches needed for tab modules that call ffmpeg helpers directly."""
    return patch.multiple(
        "morphix_ui.tabs.target_tab",
        find_ffmpeg_binaries=MagicMock(
            return_value=("/fake/ffmpeg", "/fake/ffprobe", "bundled")
        ),
    )


def _adv_patches():
    return patch.multiple(
        "morphix_ui.tabs.advanced_tab",
        find_ffmpeg_binaries=MagicMock(
            return_value=("/fake/ffmpeg", "/fake/ffprobe", "bundled")
        ),
        detect_available_encoders=MagicMock(return_value={"libx264", "libopenh264"}),
    )


def _make_app(input_file=None):
    import importlib

    import morphix_ui.main_window as ui_mod

    with _core_patches(), _tab_patches(), _adv_patches():
        importlib.reload(ui_mod)
        app = ui_mod.MorphixUI(input_file=input_file)
    return app, ui_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMorphixUIStructure(unittest.TestCase):
    """Basic structural tests — tabs exist, validation chain wired."""

    def setUp(self):
        self.app, self.ui_mod = _make_app()

    def test_has_three_tabs(self):
        self.assertEqual(len(self.app.tabs), 3)

    def test_tab_labels(self):
        labels = [t.label for t in self.app.tabs]
        self.assertEqual(labels, ["Target", "Trim", "Advanced"])

    def test_validation_chain_exists(self):
        self.assertIsNotNone(self.app.validation_chain)


class TestMorphixUIDefaults(unittest.TestCase):
    """Default field values on startup."""

    def setUp(self):
        self.app, self.ui_mod = _make_app()

    def test_target_size_default_is_20(self):
        """Target size field is pre-populated with '20' on startup (Req 12.4, 16.2)."""
        self.assertEqual(self.app.tabs[0].size_var.get(), "20")

    def test_unit_selector_defaults_to_mb(self):
        """Unit selector defaults to 'MB' on startup (Req 15.1, 16.2)."""
        self.assertEqual(self.app.tabs[0].unit_var.get(), "MB")


class TestMorphixUIValidation(unittest.TestCase):
    """Input validation error dialogs.

    show_error() lives in widgets.py and uses its own messagebox binding, so
    we patch morphix_ui.widgets.messagebox rather than ui_mod.messagebox.
    """

    def setUp(self):
        self.app, self.ui_mod = _make_app()

    def test_error_dialog_when_input_file_missing(self):
        """Error dialog shown when Compress clicked with no input file (Req 12.6)."""
        self.app.tabs[0].input_var.set("")
        self.app.tabs[0].size_var.set("20")
        with patch("morphix_ui.widgets.messagebox") as mock_mb:
            self.app.run_compress()
        mock_mb.showerror.assert_called_once()

    def test_error_dialog_when_target_size_missing(self):
        """Error dialog shown when Compress clicked with no target size (Req 12.7)."""
        self.app.tabs[0].input_var.set("/some/video.mp4")
        self.app.tabs[0].size_var.set("")
        with patch("morphix_ui.widgets.messagebox") as mock_mb:
            self.app.run_compress()
        mock_mb.showerror.assert_called_once()


class TestMorphixUIOutputAutoPopulate(unittest.TestCase):
    """Automatic output path population."""

    def setUp(self):
        self.app, self.ui_mod = _make_app()

    def test_output_auto_populated_with_morphix_compressed_suffix(self):
        """Output field auto-populated with '-morphix-compressed' suffix (Req 12.3)."""
        self.app.tabs[0]._set_output_auto("/videos/myclip.mp4")
        output = self.app.tabs[0].output_var.get()
        self.assertIn("-morphix-compressed", output)
        self.assertTrue(output.endswith(".mp4"))
        self.assertIn("myclip", output)

    def test_output_auto_populated_preserves_extension(self):
        self.app.tabs[0]._set_output_auto("/videos/myclip.mkv")
        self.assertTrue(self.app.tabs[0].output_var.get().endswith(".mkv"))

    def test_output_auto_populated_from_input_with_no_extension(self):
        self.app.tabs[0]._set_output_auto("/videos/rawvideo")
        self.assertTrue(self.app.tabs[0].output_var.get().endswith(".mp4"))

    def test_output_auto_populated_on_startup_with_input_file(self):
        app, _ = _make_app(input_file="/videos/startup.mp4")
        output = app.tabs[0].output_var.get()
        self.assertIn("-morphix-compressed", output)
        self.assertIn("startup", output)


class TestMorphixUIControlState(unittest.TestCase):
    """Control enable/disable during compression."""

    def setUp(self):
        self.app, self.ui_mod = _make_app()

    def test_controls_disabled_during_compression_and_reenabled_on_completion(self):
        """Controls disabled during compression and re-enabled on completion (Req 12.8, 12.10)."""
        app = self.app
        app.tabs[0].input_var.set("/videos/test.mp4")
        app.tabs[0].size_var.set("20")

        states_during = {}
        worker_started = threading.Event()
        worker_may_finish = threading.Event()

        def fake_run(*args, **kwargs):
            worker_started.set()
            states_during["compress_btn"] = app.compress_btn._state
            states_during["input_entry"] = app.tabs[0].input_entry._state
            states_during["device_menu"] = app.tabs[2].device_menu._state
            worker_may_finish.wait(timeout=3)

        with (
            patch("morphix_ui.compression_worker.run", side_effect=fake_run),
            patch.object(self.ui_mod, "messagebox"),
            patch(
                "morphix_ui.validation_chain.check_target_exceeds_file_size"
            ),
            patch(
                "morphix_ui.validation_chain.os.path.isfile",
                return_value=False,
            ),
        ):
            app.run_compress()
            worker_started.wait(timeout=3)
            worker_may_finish.set()

        time.sleep(0.15)

        self.assertEqual(states_during.get("compress_btn"), "disabled")
        self.assertEqual(states_during.get("input_entry"), "disabled")
        self.assertEqual(states_during.get("device_menu"), "disabled")

        self.assertEqual(app.compress_btn._state, "normal")
        self.assertEqual(app.tabs[0].input_entry._state, "normal")
        self.assertEqual(app.tabs[2].device_menu._state, "normal")

    def test_controls_reenabled_on_error(self):
        """Controls re-enabled when compression raises an exception (Req 12.11)."""
        app = self.app
        app.tabs[0].input_var.set("/videos/test.mp4")
        app.tabs[0].size_var.set("20")

        def fake_run_raises(*args, **kwargs):
            raise RuntimeError("ffmpeg failed")

        with (
            patch("morphix_ui.compression_worker.run", side_effect=fake_run_raises),
            patch.object(self.ui_mod, "messagebox"),
            patch(
                "morphix_ui.validation_chain.check_target_exceeds_file_size"
            ),
            patch(
                "morphix_ui.validation_chain.os.path.isfile",
                return_value=False,
            ),
        ):
            app.run_compress()

        time.sleep(0.15)

        self.assertEqual(app.compress_btn._state, "normal")
        self.assertEqual(app.tabs[0].input_entry._state, "normal")
        self.assertEqual(app.tabs[2].device_menu._state, "normal")
        self.assertFalse(app.state.is_running)


class TestMorphixUITrimControls(unittest.TestCase):
    """Trim checkbox and time entry behaviour."""

    def setUp(self):
        self.app, _ = _make_app()

    @property
    def trim_tab(self):
        return self.app.tabs[1]

    def test_trim_checkbox_exists_and_unchecked(self):
        self.assertFalse(self.trim_tab.trim_enabled_var.get())

    def test_time_entries_exist(self):
        self.assertTrue(hasattr(self.trim_tab, "trim_frame"))
        self.assertTrue(hasattr(self.trim_tab, "trim_start_entry"))
        self.assertTrue(hasattr(self.trim_tab, "trim_end_entry"))

    def test_time_entries_hidden_by_default(self):
        grid_info = self.trim_tab.trim_frame.grid_info()
        self.assertEqual(grid_info, {})

    def test_time_entries_visible_when_checked(self):
        self.trim_tab.trim_enabled_var.set(True)
        self.trim_tab._on_trim_toggle()
        grid_info = self.trim_tab.trim_frame.grid_info()
        self.assertNotEqual(grid_info, {})

    def test_time_entries_hidden_when_unchecked(self):
        self.trim_tab.trim_enabled_var.set(True)
        self.trim_tab._on_trim_toggle()
        self.trim_tab.trim_enabled_var.set(False)
        self.trim_tab._on_trim_toggle()
        self.assertEqual(self.trim_tab.trim_frame.grid_info(), {})


class TestMorphixUITrimHelpers(unittest.TestCase):
    """Trim static helper methods."""

    def setUp(self):
        self.app, _ = _make_app()

    @property
    def trim_tab(self):
        return self.app.tabs[1]

    def test_parse_time_mmss(self):
        self.assertEqual(self.trim_tab._parse_time("0:25"), 25.0)
        self.assertEqual(self.trim_tab._parse_time("1:30"), 90.0)

    def test_parse_time_hhmmss(self):
        self.assertEqual(self.trim_tab._parse_time("1:05:30"), 3930.0)
        self.assertEqual(self.trim_tab._parse_time("0:00:00"), 0.0)

    def test_format_time(self):
        self.assertEqual(self.trim_tab._format_time(0), "00:00:00")
        self.assertEqual(self.trim_tab._format_time(90), "00:01:30")
        self.assertEqual(self.trim_tab._format_time(3661), "01:01:01")


if __name__ == "__main__":
    unittest.main()
