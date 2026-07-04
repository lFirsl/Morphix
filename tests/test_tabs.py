"""Unit tests for morphix_ui tab modules and validation chain."""

from __future__ import annotations

import sys
import types
import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Tkinter headless setup — must happen before any tkinter import.
# ---------------------------------------------------------------------------


class _FakeStringVar:
    def __init__(self, value=""):
        self._value = value
        self._traces: list = []

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


class _FakeBooleanVar:
    def __init__(self, value=False):
        self._value = bool(value)

    def get(self):
        return self._value

    def set(self, value):
        self._value = bool(value)


class _FakeWidget:
    def __init__(self, *args, **kwargs):
        self._state = "normal"
        self._text = kwargs.get("text", "")
        self._grid_info: dict = {}

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

    def mainloop(self):
        pass

    def destroy(self):
        pass


_tk_mod = types.ModuleType("tkinter")
_tk_mod.Tk = _FakeTk
_tk_mod.Frame = _FakeWidget
_tk_mod.StringVar = _FakeStringVar
_tk_mod.BooleanVar = _FakeBooleanVar
_tk_mod.Label = _FakeWidget
_tk_mod.Checkbutton = _FakeWidget
_tk_mod.Entry = _FakeWidget
_tk_mod.Button = _FakeWidget
_tk_mod.OptionMenu = _FakeWidget
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
# Shared fake state
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dc  # noqa: E402
from dataclasses import field as _field


@_dc
class _FakeState:
    is_running: bool = False
    auto_output: bool = True
    suppress_output_trace: bool = False
    trim_duration_seconds: float = 0.0
    openh264_warned: bool = False
    device_label_to_key: dict = _field(default_factory=lambda: {"CPU": "cpu"})
    unavailable_devices: set = _field(default_factory=set)


def _make_state(**kwargs) -> _FakeState:
    s = _FakeState()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# ---------------------------------------------------------------------------
# Task 1: BaseTab contract tests
# ---------------------------------------------------------------------------


class TestBaseTabContract(unittest.TestCase):
    """BaseTab ABC — contract tests via a minimal concrete subclass."""

    def setUp(self):
        from morphix_ui.tabs.base import BaseTab

        @dataclass(frozen=True)
        class _ConcreteResult:
            value: int = 42

        class ConcreteTab(BaseTab):
            label = "Test"

            def build(self):
                pass

            def collect(self):
                return _ConcreteResult()

            def validate(self):
                return None

            def set_enabled(self, enabled):
                pass

        self.ConcreteTab = ConcreteTab
        self.state = _make_state()

    def test_label_exists(self):
        self.assertEqual(self.ConcreteTab.label, "Test")

    def test_instantiation(self):
        tab = self.ConcreteTab(_FakeWidget(), self.state)
        self.assertIsNotNone(tab)

    def test_collect_returns_something(self):
        tab = self.ConcreteTab(_FakeWidget(), self.state)
        result = tab.collect()
        self.assertIsNotNone(result)

    def test_validate_returns_none(self):
        tab = self.ConcreteTab(_FakeWidget(), self.state)
        self.assertIsNone(tab.validate())

    def test_set_enabled_does_not_crash(self):
        tab = self.ConcreteTab(_FakeWidget(), self.state)
        tab.set_enabled(True)
        tab.set_enabled(False)

    def test_shared_state_accessible(self):
        tab = self.ConcreteTab(_FakeWidget(), self.state)
        self.assertIs(tab.shared_state, self.state)


# ---------------------------------------------------------------------------
# Task 2: TargetTab tests
# ---------------------------------------------------------------------------

_FFMPEG_PATCH = patch(
    "morphix_ui.tabs.target_tab.find_ffmpeg_binaries",
    return_value=("/ffmpeg", "/ffprobe", "bundled"),
)


class TestTargetTab(unittest.TestCase):
    def _make_tab(self, **state_kwargs):
        _FFMPEG_PATCH.start()
        from morphix_ui.tabs.target_tab import TargetTab

        state = _make_state(**state_kwargs)
        app = _FakeTk()
        tab = TargetTab(_FakeWidget(), state, app)
        self.addCleanup(_FFMPEG_PATCH.stop)
        return tab, state

    def test_label(self):
        tab, _ = self._make_tab()
        self.assertEqual(tab.label, "Target")

    def test_validate_returns_error_when_input_empty(self):
        tab, _ = self._make_tab()
        tab.input_var.set("")
        tab.size_var.set("20")
        self.assertIsNotNone(tab.validate())

    def test_validate_returns_error_when_size_empty(self):
        tab, _ = self._make_tab()
        tab.input_var.set("/video.mp4")
        tab.size_var.set("")
        self.assertIsNotNone(tab.validate())

    def test_validate_returns_none_when_valid(self):
        tab, _ = self._make_tab()
        tab.input_var.set("/video.mp4")
        tab.size_var.set("20")
        self.assertIsNone(tab.validate())

    def test_collect_returns_target_params_mb(self):
        from morphix_ui.tabs.target_tab import TargetParams

        tab, _ = self._make_tab()
        tab.input_var.set("/video.mp4")
        tab.output_var.set("/out.mp4")
        tab.size_var.set("20")
        tab.unit_var.set("MB")
        result = tab.collect()
        self.assertIsInstance(result, TargetParams)
        self.assertEqual(result.size_mb, 20.0)

    def test_collect_converts_gb_to_mb(self):
        tab, _ = self._make_tab()
        tab.input_var.set("/video.mp4")
        tab.output_var.set("/out.mp4")
        tab.size_var.set("2")
        tab.unit_var.set("GB")
        result = tab.collect()
        self.assertEqual(result.size_mb, 2000.0)

    def test_set_output_auto_adds_suffix(self):
        tab, _ = self._make_tab()
        tab._set_output_auto("/videos/myclip.mp4")
        self.assertIn("-morphix-compressed", tab.output_var.get())
        self.assertTrue(tab.output_var.get().endswith(".mp4"))

    def test_set_output_auto_preserves_extension(self):
        tab, _ = self._make_tab()
        tab._set_output_auto("/videos/myclip.mkv")
        self.assertTrue(tab.output_var.get().endswith(".mkv"))

    def test_set_output_auto_uses_mp4_when_no_extension(self):
        tab, _ = self._make_tab()
        tab._set_output_auto("/videos/rawvideo")
        self.assertTrue(tab.output_var.get().endswith(".mp4"))

    def test_set_output_manual_marks_auto_false(self):
        tab, state = self._make_tab()
        state.auto_output = True
        tab._set_output_manual("/custom/out.mp4")
        self.assertFalse(state.auto_output)
        self.assertEqual(tab.output_var.get(), "/custom/out.mp4")

    def test_set_enabled_does_not_crash(self):
        tab, _ = self._make_tab()
        tab.set_enabled(False)
        tab.set_enabled(True)

    def test_browse_input_passes_parent_kwarg(self):
        """askopenfilename must receive parent= so the dialog anchors to the window."""
        tab, _ = self._make_tab()
        with patch("morphix_ui.tabs.target_tab.filedialog") as mock_fd, \
             patch("morphix_ui.tabs.target_tab.ffprobe_media", return_value=None):
            mock_fd.askopenfilename.return_value = "/video.mp4"
            tab.browse_input()
        call_kwargs = mock_fd.askopenfilename.call_args.kwargs
        self.assertIn(
            "parent",
            call_kwargs,
            "parent= must be passed to prevent the dialog appearing behind the window",
        )

    def test_browse_input_sets_input_var_and_auto_output(self):
        """Selecting a file via Browse sets input_var and auto-populates output_var."""
        tab, _ = self._make_tab()
        with patch("morphix_ui.tabs.target_tab.filedialog") as mock_fd, \
             patch("morphix_ui.tabs.target_tab.ffprobe_media", return_value=None):
            mock_fd.askopenfilename.return_value = "/videos/clip.mp4"
            tab.browse_input()
        self.assertEqual(tab.input_var.get(), "/videos/clip.mp4")
        self.assertIn("-morphix-compressed", tab.output_var.get())

    def test_browse_input_cancel_is_noop(self):
        """Cancelling the file dialog (empty string return) leaves vars unchanged."""
        tab, _ = self._make_tab()
        tab.input_var.set("/existing.mp4")
        tab.output_var.set("/existing-out.mp4")
        with patch("morphix_ui.tabs.target_tab.filedialog") as mock_fd:
            mock_fd.askopenfilename.return_value = ""
            tab.browse_input()
        self.assertEqual(tab.input_var.get(), "/existing.mp4")
        self.assertEqual(tab.output_var.get(), "/existing-out.mp4")

    def test_browse_output_passes_parent_kwarg(self):
        """asksaveasfilename must receive parent= so the dialog anchors to the window."""
        tab, _ = self._make_tab()
        with patch("morphix_ui.tabs.target_tab.filedialog") as mock_fd:
            mock_fd.asksaveasfilename.return_value = "/out.mp4"
            tab.browse_output()
        call_kwargs = mock_fd.asksaveasfilename.call_args.kwargs
        self.assertIn("parent", call_kwargs)

    def test_browse_output_sets_output_var(self):
        """Selecting an output path via Browse sets output_var."""
        tab, _ = self._make_tab()
        with patch("morphix_ui.tabs.target_tab.filedialog") as mock_fd:
            mock_fd.asksaveasfilename.return_value = "/custom/out.mp4"
            tab.browse_output()
        self.assertEqual(tab.output_var.get(), "/custom/out.mp4")

    def test_browse_output_cancel_is_noop(self):
        """Cancelling the save dialog leaves output_var unchanged."""
        tab, _ = self._make_tab()
        tab.output_var.set("/existing-out.mp4")
        with patch("morphix_ui.tabs.target_tab.filedialog") as mock_fd:
            mock_fd.asksaveasfilename.return_value = ""
            tab.browse_output()
        self.assertEqual(tab.output_var.get(), "/existing-out.mp4")


# ---------------------------------------------------------------------------
# Task 3: TrimTab tests
# ---------------------------------------------------------------------------


class TestTrimTab(unittest.TestCase):
    def _make_tab(self, trim_duration=0.0):
        from morphix_ui.tabs.trim_tab import TrimTab

        state = _make_state(trim_duration_seconds=trim_duration)
        app = _FakeTk()
        tab = TrimTab(_FakeWidget(), state, app)
        return tab, state

    def test_label(self):
        tab, _ = self._make_tab()
        self.assertEqual(tab.label, "Trim")

    def test_validate_returns_none_when_disabled(self):
        tab, _ = self._make_tab()
        tab.trim_enabled_var.set(False)
        self.assertIsNone(tab.validate())

    def test_validate_returns_error_on_invalid_time_format(self):
        tab, _ = self._make_tab(trim_duration=60.0)
        tab.trim_enabled_var.set(True)
        tab.trim_start_var.set("notatime")
        tab.trim_end_var.set("00:00:30")
        self.assertIsNotNone(tab.validate())

    def test_validate_returns_error_when_end_before_start(self):
        tab, _ = self._make_tab(trim_duration=60.0)
        tab.trim_enabled_var.set(True)
        tab.trim_start_var.set("00:00:30")
        tab.trim_end_var.set("00:00:10")
        self.assertIsNotNone(tab.validate())

    def test_validate_returns_none_when_trim_valid(self):
        tab, _ = self._make_tab(trim_duration=60.0)
        tab.trim_enabled_var.set(True)
        tab.trim_start_var.set("00:00:05")
        tab.trim_end_var.set("00:00:30")
        self.assertIsNone(tab.validate())

    def test_collect_disabled_returns_none_times(self):
        from morphix_ui.tabs.trim_tab import TrimParams

        tab, _ = self._make_tab()
        tab.trim_enabled_var.set(False)
        result = tab.collect()
        self.assertIsInstance(result, TrimParams)
        self.assertFalse(result.enabled)
        self.assertIsNone(result.start)
        self.assertIsNone(result.end)

    def test_collect_enabled_returns_parsed_times(self):
        tab, _ = self._make_tab(trim_duration=60.0)
        tab.trim_enabled_var.set(True)
        tab.trim_start_var.set("00:00:05")
        tab.trim_end_var.set("00:00:30")
        result = tab.collect()
        self.assertTrue(result.enabled)
        self.assertEqual(result.start, 5.0)
        self.assertEqual(result.end, 30.0)

    def test_collect_enabled_invalid_format_returns_none_times(self):
        tab, _ = self._make_tab()
        tab.trim_enabled_var.set(True)
        tab.trim_start_var.set("bad")
        tab.trim_end_var.set("also_bad")
        result = tab.collect()
        self.assertTrue(result.enabled)
        self.assertIsNone(result.start)
        self.assertIsNone(result.end)

    def test_set_end_time_updates_state_and_var(self):
        tab, state = self._make_tab()
        tab.set_end_time(90.0)
        self.assertEqual(state.trim_duration_seconds, 90.0)
        self.assertEqual(tab.trim_end_var.get(), "00:01:30")

    def test_parse_time_mmss(self):
        from morphix_ui.tabs.trim_tab import TrimTab

        self.assertEqual(TrimTab._parse_time("1:30"), 90.0)
        self.assertEqual(TrimTab._parse_time("0:25"), 25.0)

    def test_parse_time_hhmmss(self):
        from morphix_ui.tabs.trim_tab import TrimTab

        self.assertEqual(TrimTab._parse_time("1:05:30"), 3930.0)

    def test_format_time(self):
        from morphix_ui.tabs.trim_tab import TrimTab

        self.assertEqual(TrimTab._format_time(90), "00:01:30")
        self.assertEqual(TrimTab._format_time(3661), "01:01:01")

    def test_set_enabled_does_not_crash(self):
        tab, _ = self._make_tab()
        tab.set_enabled(False)
        tab.set_enabled(True)

    def test_on_trim_toggle_shows_frame(self):
        tab, _ = self._make_tab()
        tab.trim_enabled_var.set(True)
        tab._on_trim_toggle()
        self.assertNotEqual(tab.trim_frame.grid_info(), {})

    def test_on_trim_toggle_hides_frame(self):
        tab, _ = self._make_tab()
        tab.trim_enabled_var.set(True)
        tab._on_trim_toggle()
        tab.trim_enabled_var.set(False)
        tab._on_trim_toggle()
        self.assertEqual(tab.trim_frame.grid_info(), {})


# ---------------------------------------------------------------------------
# Task 4: AdvancedTab tests
# ---------------------------------------------------------------------------

_ADV_PATCHES = lambda: patch.multiple(  # noqa: E731
    "morphix_ui.tabs.advanced_tab",
    find_ffmpeg_binaries=MagicMock(return_value=("/ffmpeg", "/ffprobe", "bundled")),
    detect_available_encoders=MagicMock(return_value={"libx264", "libopenh264"}),
)


class TestAdvancedTab(unittest.TestCase):
    def _make_tab(self):
        with _ADV_PATCHES():
            from morphix_ui.tabs.advanced_tab import AdvancedTab

            state = _make_state(
                device_label_to_key={"CPU": "cpu"},
                unavailable_devices=set(),
            )
            app = _FakeTk()
            tab = AdvancedTab(_FakeWidget(), state, app)
        return tab, state

    def test_label(self):
        tab, _ = self._make_tab()
        self.assertEqual(tab.label, "Advanced")

    def test_validate_always_returns_none(self):
        tab, _ = self._make_tab()
        self.assertIsNone(tab.validate())

    def test_collect_encoder_override_none_when_auto(self):
        from morphix_ui.tabs.advanced_tab import AdvancedParams

        tab, _ = self._make_tab()
        tab.encoder_var.set("Auto")
        result = tab.collect()
        self.assertIsInstance(result, AdvancedParams)
        self.assertIsNone(result.encoder_override)

    def test_collect_encoder_override_set_when_chosen(self):
        tab, _ = self._make_tab()
        tab.encoder_var.set("libx264")
        result = tab.collect()
        self.assertEqual(result.encoder_override, "libx264")

    def test_collect_device_preference(self):
        tab, _ = self._make_tab()
        tab.device_var.set("CPU")
        result = tab.collect()
        self.assertEqual(result.device_preference, "cpu")

    def test_set_enabled_does_not_crash(self):
        tab, _ = self._make_tab()
        tab.set_enabled(False)
        tab.set_enabled(True)


if __name__ == "__main__":
    unittest.main()
