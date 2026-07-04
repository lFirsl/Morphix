"""Unit tests for morphix_ui.validation_chain (Chain of Responsibility)."""

from __future__ import annotations

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

    def test_returns_error_string_when_check_raises(self):
        with patch(
            "morphix_ui.validation_chain.check_target_exceeds_file_size",
            side_effect=ValueError("target too large"),
        ):
            result = self.handler.check(_params())
        self.assertEqual(result, "target too large")


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

    def test_returns_error_when_end_lte_start(self):
        p = _params(
            trim_enabled=True,
            trim_start=30.0,
            trim_end=10.0,
            trim_duration=60.0,
        )
        result = self.handler.check(p)
        self.assertIsNotNone(result)

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
# Chain composition tests
# ---------------------------------------------------------------------------


class TestValidationChain(unittest.TestCase):
    def test_build_chain_requires_at_least_one_handler(self):
        from morphix_ui.validation_chain import build_chain

        with self.assertRaises(ValueError):
            build_chain()

    def test_single_handler_chain(self):
        from morphix_ui.validation_chain import FileSizeHandler, build_chain

        chain = build_chain(FileSizeHandler())
        with patch(
            "morphix_ui.validation_chain.check_target_exceeds_file_size"
        ):
            self.assertIsNone(chain.handle(_params()))

    def test_chain_short_circuits_on_first_failure(self):
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
            result = chain.handle(_params())

        self.assertEqual(result, "too large")
        self.assertEqual(second_called, [], "second handler should not have been called")

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
            result = chain.handle(_params())
        self.assertIsNone(result)

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

        # build_chain wires three handlers; head is the first.
        a = FileSizeHandler()
        b = TrimValuesHandler()
        head = build_chain(a, b)
        self.assertIs(head, a)


if __name__ == "__main__":
    unittest.main()
