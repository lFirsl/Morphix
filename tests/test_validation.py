"""Tests for check_trim_values (Requirements Trim-1 through Trim-4)."""

import pytest
from morphix_core.validation import check_trim_values


class TestCheckTrimValues:
    """Validation of trim start/end values against video duration."""

    def test_no_trimming_requested_is_valid(self):
        ok, msg = check_trim_values(None, None, 100.0)
        assert ok is True
        assert msg is None

    def test_only_start_without_end_returns_error(self):
        ok, msg = check_trim_values(10.0, None, 100.0)
        assert ok is False
        assert "Both Start and End" in msg

    def test_only_end_without_start_returns_error(self):
        ok, msg = check_trim_values(None, 50.0, 100.0)
        assert ok is False
        assert "Both Start and End" in msg

    def test_negative_start_returns_error(self):
        ok, msg = check_trim_values(-1.0, 50.0, 100.0)
        assert ok is False
        assert "Start time must be >= 0" in msg

    def test_negative_end_returns_error(self):
        ok, msg = check_trim_values(10.0, -1.0, 100.0)
        assert ok is False
        assert "End time must be >= 0" in msg

    def test_end_equals_start_returns_error(self):
        ok, msg = check_trim_values(50.0, 50.0, 100.0)
        assert ok is False
        assert "End time must be greater than Start" in msg

    def test_duration_exceeds_video_returns_error(self):
        ok, msg = check_trim_values(10.0, 150.0, 100.0)
        assert ok is False
        assert "exceeds video duration" in msg

    def test_start_plus_duration_exceeds_returns_error(self):
        ok, msg = check_trim_values(95.0, 200.0, 100.0)
        assert ok is False
        assert "exceeds video duration" in msg

    def test_valid_range_within_duration(self):
        ok, msg = check_trim_values(10.0, 50.0, 100.0)
        assert ok is True
        assert msg is None

    def test_zero_start_and_full_duration(self):
        # (end - start) == full_duration — spec allows this (not strictly >).
        ok, msg = check_trim_values(0.0, 100.0, 100.0)
        assert ok is True

    def test_zero_start_zero_end_returns_error(self):
        ok, msg = check_trim_values(0.0, 0.0, 100.0)
        assert ok is False
        assert "End time must be greater than Start" in msg

    def test_exact_duration_boundary_is_valid(self):
        ok, msg = check_trim_values(50.0, 150.0, 100.0)
        assert ok is True
        assert msg is None
