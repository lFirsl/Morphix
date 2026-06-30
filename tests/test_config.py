"""Unit tests for CompressConfig dataclass and parse_resolution utility."""

import dataclasses
from pathlib import Path

import pytest

from morphix_core.config import CompressConfig, parse_resolution


class TestCompressConfigDefaults:
    """Verify default values and required fields."""

    def test_minimal_construction(self):
        cfg = CompressConfig("video.mp4", 15)
        assert cfg.max_mb == 15
        assert cfg.quality == "medium"
        assert cfg.resolution is None
        assert cfg.device_preference == "auto"
        assert cfg.overwrite is True
        assert cfg.disable_logs is True
        assert cfg.progress is True
        assert cfg.progress_cb is None
        assert cfg.start is None
        assert cfg.end is None
        assert cfg.warning_cb is None
        assert cfg.encoder_override is None
        assert cfg.output_path is None

    def test_input_path_coerced_to_absolute_path(self):
        cfg = CompressConfig("video.mp4", 15)
        assert isinstance(cfg.input_path, Path)
        assert cfg.input_path.is_absolute()

    def test_input_path_from_path_object(self):
        cfg = CompressConfig(Path("some/video.mp4"), 15)
        assert isinstance(cfg.input_path, Path)
        assert cfg.input_path.is_absolute()

    def test_output_path_coerced_from_string(self):
        cfg = CompressConfig("video.mp4", 15, output_path="out.mp4")
        assert isinstance(cfg.output_path, Path)

    def test_output_path_none_stays_none(self):
        cfg = CompressConfig("video.mp4", 15, output_path=None)
        assert cfg.output_path is None


class TestCompressConfigFrozen:
    """Verify immutability."""

    def test_cannot_assign_to_field(self):
        cfg = CompressConfig("video.mp4", 15)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.max_mb = 20

    def test_cannot_assign_new_attribute(self):
        cfg = CompressConfig("video.mp4", 15)
        with pytest.raises(dataclasses.FrozenInstanceError):
            cfg.new_field = "nope"


class TestCompressConfigTrimProperties:
    """Verify trimming and trim_duration computed properties."""

    def test_trimming_false_when_no_start_end(self):
        cfg = CompressConfig("video.mp4", 15)
        assert cfg.trimming is False
        assert cfg.trim_duration == 0.0

    def test_trimming_false_when_only_start(self):
        cfg = CompressConfig("video.mp4", 15, start=5.0)
        assert cfg.trimming is False
        assert cfg.trim_duration == 0.0

    def test_trimming_false_when_only_end(self):
        cfg = CompressConfig("video.mp4", 15, end=30.0)
        assert cfg.trimming is False
        assert cfg.trim_duration == 0.0

    def test_trimming_true_when_both_provided(self):
        cfg = CompressConfig("video.mp4", 15, start=10.0, end=60.0)
        assert cfg.trimming is True
        assert cfg.trim_duration == 50.0

    def test_trim_duration_calculation(self):
        cfg = CompressConfig("video.mp4", 15, start=0.0, end=120.5)
        assert cfg.trim_duration == pytest.approx(120.5)


class TestCompressConfigCallbacks:
    """Verify callback fields accept callables."""

    def test_progress_cb_stored(self):
        def cb(pct, phase):
            pass

        cfg = CompressConfig("video.mp4", 15, progress_cb=cb)
        assert cfg.progress_cb is cb

    def test_warning_cb_stored(self):
        def cb(msg):
            pass

        cfg = CompressConfig("video.mp4", 15, warning_cb=cb)
        assert cfg.warning_cb is cb


class TestParseResolution:
    """Verify parse_resolution utility."""

    def test_valid_resolution(self):
        assert parse_resolution("1280x720") == (1280, 720)

    def test_odd_dimensions_clamped_even(self):
        result = parse_resolution("1281x721")
        assert result == (1280, 720)

    def test_case_insensitive(self):
        assert parse_resolution("1920X1080") == (1920, 1080)

    def test_invalid_no_x(self):
        assert parse_resolution("1920") is None

    def test_invalid_non_numeric(self):
        assert parse_resolution("abcxdef") is None

    def test_too_small_dimensions(self):
        assert parse_resolution("1x1") is None

    def test_zero_dimensions(self):
        assert parse_resolution("0x0") is None

    def test_valid_small(self):
        assert parse_resolution("2x2") == (2, 2)
