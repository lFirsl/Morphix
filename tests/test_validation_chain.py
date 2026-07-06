"""Unit tests for morphix_ui.validation_chain (Chain of Responsibility with severity)."""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers — minimal param dataclasses matching the real ones
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _TargetParams:
    input_path: str
    output_path: str
    size_mb: float


@dataclass(frozen=True)
class _TrimParams:
    enabled: bool
    start: float | None
    end: float | None


def _params(
    input_path="/video.mp4",
    output_path="/out.mp4",
    size_mb=20.0,
    trim_enabled=False,
    trim_start=None,
    trim_end=None,
    trim_duration=float("inf"),
):
    return {
        "Target": _TargetParams(input_path, output_path, size_mb),
        "Trim": _TrimParams(trim_enabled, trim_start, trim_end),
        "_trim_duration": trim_duration,
    }


# ---------------------------------------------------------------------------
# ValidationResult tests
# ---------------------------------------------------------------------------


class TestValidationResult(unittest.TestCase):
    def test_result_is_frozen(self):
        from morphix_ui.validation_chain import ValidationResult

        r = ValidationResult(severity="error", message="bad")
        with self.assertRaises(Exception):
            r.severity = "warning"  # type: ignore[misc]

    def test_result_fields(self):
        from morphix_ui.validation_chain import ValidationResult

        r = ValidationResult(severity="warning", message="heads up")
        self.assertEqual(r.severity, "warning")
        self.assertEqual(r.message, "heads up")


# ---------------------------------------------------------------------------
# FileSizeHandler tests
# ---------------------------------------------------------------------------


class TestFileSizeHandler(unittest.TestCase):
    def setUp(self):
        from morphix_ui.validation_chain import FileSizeHandler

        self.handler = FileSizeHandler()

    def test_returns_none_when_no_target_key(self):
        self.assertIsNone(self.handler.check({}))

    def test_returns_none_when_check_passes(self):
        with patch(
            "morphix_ui.validation_chain.check_target_exceeds_file_size"
        ):
            result = self.handler.check(_params())
        self.assertIsNone(result)

    def test_returns_error_result_when_check_raises(self):
        from morphix_ui.validation_chain import ValidationResult

        with patch(
            "morphix_ui.validation_chain.check_target_exceeds_file_size",
            side_effect=ValueError("target too large"),
        ):
            result = self.handler.check(_params())
        self.assertIsInstance(result, ValidationResult)
        self.assertEqual(result.severity, "error")
        self.assertEqual(result.message, "target too large")


# ---------------------------------------------------------------------------
# TrimValuesHandler tests
# ---------------------------------------------------------------------------


class TestTrimValuesHandler(unittest.TestCase):
    def setUp(self):
        from morphix_ui.validation_chain import TrimValuesHandler

        self.handler = TrimValuesHandler()

    def test_returns_none_when_trim_disabled(self):
        result = self.handler.check(_params(trim_enabled=False))
        self.assertIsNone(result)

    def test_returns_none_when_no_trim_key(self):
        self.assertIsNone(self.handler.check({}))

    def test_returns_error_when_start_none(self):
        p = _params(trim_enabled=True, trim_start=None, trim_end=30.0)
        result = self.handler.check(p)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, "error")

    def test_returns_error_when_end_lte_start(self):
        p = _params(
            trim_enabled=True,
            trim_start=30.0,
            trim_end=10.0,
            trim_duration=60.0,
        )
        result = self.handler.check(p)
        self.assertIsNotNone(result)
        self.assertEqual(result.severity, "error")

    def test_returns_none_when_trim_valid(self):
        p = _params(
            trim_enabled=True,
            trim_start=5.0,
            trim_end=30.0,
            trim_duration=60.0,
        )
        result = self.handler.check(p)
        self.assertIsNone(result)

    def test_uses_inf_duration_when_key_absent(self):
        p = {
            "Trim": _TrimParams(enabled=True, start=5.0, end=30.0),
        }
        # No _trim_duration key — should default to inf and pass.
        result = self.handler.check(p)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# LowCompressionHandler tests
# ---------------------------------------------------------------------------


class TestLowCompressionHandler(unittest.TestCase):
    def setUp(self):
        from morphix_ui.validation_chain import LowCompressionHandler

        self.handler = LowCompressionHandler()

    def test_returns_none_when_no_target(self):
        self.assertIsNone(self.handler.check({}))

    def test_returns_none_when_file_missing(self):
        p = _params(input_path="/nonexistent/file.mp4", size_mb=1.0)
        self.assertIsNone(self.handler.check(p))

    def test_returns_none_when_ratio_acceptable(self, tmp_path=None):
        """No warning when target >= 5% of file size."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x" * 1_000_000)  # 1 MB file
            path = f.name
        try:
            # target 0.1 MB = 10% of 1 MB → no warning
            p = _params(input_path=path, size_mb=0.1)
            result = self.handler.check(p)
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_returns_warning_when_ratio_too_low(self):
        """Warning when target < 5% of file size."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x" * 10_000_000)  # 10 MB file
            path = f.name
        try:
            # target 0.1 MB = 1% of 10 MB → warning
            p = _params(input_path=path, size_mb=0.1)
            result = self.handler.check(p)
            self.assertIsNotNone(result)
            self.assertEqual(result.severity, "warning")
            self.assertIn("5%", result.message)
        finally:
            os.unlink(path)

    def test_trimmed_returns_none_when_ratio_acceptable(self):
        """No warning when trim target >= 5% of estimated trimmed size."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x" * 10_000_000)  # 10 MB file
            path = f.name
        try:
            # trim 30s of 60s video → estimated 5 MB trimmed
            # target 1.0 MB = 20% of 5 MB → no warning
            p = _params(
                input_path=path,
                size_mb=1.0,
                trim_enabled=True,
                trim_start=0.0,
                trim_end=30.0,
                trim_duration=60.0,
            )
            result = self.handler.check(p)
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_trimmed_returns_warning_when_ratio_too_low(self):
        """Warning when trim target < 5% of estimated trimmed size."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x" * 10_000_000)  # 10 MB file
            path = f.name
        try:
            # trim 30s of 60s video → estimated 5 MB trimmed
            # target 0.1 MB = 2% of 5 MB → warning
            p = _params(
                input_path=path,
                size_mb=0.1,
                trim_enabled=True,
                trim_start=0.0,
                trim_end=30.0,
                trim_duration=60.0,
            )
            result = self.handler.check(p)
            self.assertIsNotNone(result)
            self.assertEqual(result.severity, "warning")
            self.assertIn("trimmed clip", result.message)
        finally:
            os.unlink(path)

    def test_trimmed_returns_none_when_duration_zero(self):
        """No warning when trim_duration is zero (avoids division by zero)."""
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"x" * 10_000_000)
            path = f.name
        try:
            p = _params(
                input_path=path,
                size_mb=0.1,
                trim_enabled=True,
                trim_start=0.0,
                trim_end=30.0,
                trim_duration=0.0,
            )
            result = self.handler.check(p)
            self.assertIsNone(result)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Chain composition tests
# ---------------------------------------------------------------------------


class TestValidationChain(unittest.TestCase):
    def test_build_chain_requires_at_least_one_handler(self):
        from morphix_ui.validation_chain import build_chain

        with self.assertRaises(ValueError):
            build_chain()

    def test_single_handler_chain_returns_empty_list_when_valid(self):
        from morphix_ui.validation_chain import FileSizeHandler, build_chain

        chain = build_chain(FileSizeHandler())
        with patch(
            "morphix_ui.validation_chain.check_target_exceeds_file_size"
        ):
            results = chain.handle(_params())
        self.assertEqual(results, [])

    def test_chain_short_circuits_on_error(self):
        from morphix_ui.validation_chain import (
            FileSizeHandler,
            TrimValuesHandler,
            build_chain,
        )

        second = TrimValuesHandler()
        second_called = []
        original_check = second.check

        def spy_check(params):
            second_called.append(True)
            return original_check(params)

        second.check = spy_check

        chain = build_chain(FileSizeHandler(), second)
        with patch(
            "morphix_ui.validation_chain.check_target_exceeds_file_size",
            side_effect=ValueError("too large"),
        ):
            results = chain.handle(_params())

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].severity, "error")
        self.assertEqual(results[0].message, "too large")
        self.assertEqual(second_called, [], "second handler should not have been called")

    def test_warnings_accumulate_and_do_not_short_circuit(self):
        """Warnings don't prevent subsequent handlers from running."""
        from morphix_ui.validation_chain import (
            LowCompressionHandler,
            ValidationHandler,
            ValidationResult,
            build_chain,
        )

        class FakeWarningHandler(ValidationHandler):
            def check(self, params):
                return ValidationResult(severity="warning", message="warn 1")

        class FakeWarningHandler2(ValidationHandler):
            def check(self, params):
                return ValidationResult(severity="warning", message="warn 2")

        chain = build_chain(FakeWarningHandler(), FakeWarningHandler2())
        results = chain.handle(_params())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].message, "warn 1")
        self.assertEqual(results[1].message, "warn 2")

    def test_error_after_warning_stops_chain(self):
        """An error after a warning short-circuits but keeps accumulated warnings."""
        from morphix_ui.validation_chain import (
            ValidationHandler,
            ValidationResult,
            build_chain,
        )

        class WarnHandler(ValidationHandler):
            def check(self, params):
                return ValidationResult(severity="warning", message="heads up")

        class ErrorHandler(ValidationHandler):
            def check(self, params):
                return ValidationResult(severity="error", message="blocked")

        class NeverReachedHandler(ValidationHandler):
            def check(self, params):
                raise AssertionError("should not be called")

        chain = build_chain(WarnHandler(), ErrorHandler(), NeverReachedHandler())
        results = chain.handle(_params())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].severity, "warning")
        self.assertEqual(results[1].severity, "error")

    def test_chain_passes_through_when_all_valid(self):
        from morphix_ui.validation_chain import (
            FileSizeHandler,
            TrimValuesHandler,
            build_chain,
        )

        chain = build_chain(FileSizeHandler(), TrimValuesHandler())
        with patch(
            "morphix_ui.validation_chain.check_target_exceeds_file_size"
        ):
            results = chain.handle(_params())
        self.assertEqual(results, [])

    def test_set_next_returns_next_handler(self):
        from morphix_ui.validation_chain import FileSizeHandler, TrimValuesHandler

        a = FileSizeHandler()
        b = TrimValuesHandler()
        returned = a.set_next(b)
        self.assertIs(returned, b)

    def test_fluent_chaining(self):
        from morphix_ui.validation_chain import (
            FileSizeHandler,
            TrimValuesHandler,
            build_chain,
        )

        a = FileSizeHandler()
        b = TrimValuesHandler()
        head = build_chain(a, b)
        self.assertIs(head, a)


if __name__ == "__main__":
    unittest.main()
