"""Validation chain (Chain of Responsibility) for Morphix UI.

Each handler checks one slice of the compression parameters and returns a
:class:`ValidationResult` (with severity ``"error"`` or ``"warning"``) or
``None`` to pass through.

The chain collects all results:
- **Errors** short-circuit immediately (no further handlers run).
- **Warnings** accumulate — subsequent handlers still run.

Usage::

    chain = build_chain(
        FileSizeHandler(), TrimValuesHandler(), LowCompressionHandler()
    )
    results = chain.handle(params)
    for result in results:
        if result.severity == "error":
            show_error(self, result.message)
            return
        if result.severity == "warning":
            if not messagebox.askokcancel(..., result.message):
                return

The ``params`` dict passed to ``handle()`` should contain:

- ``"Target"``      — :class:`~morphix_ui.tabs.target_tab.TargetParams`
- ``"Trim"``        — :class:`~morphix_ui.tabs.trim_tab.TrimParams`
- ``"Advanced"``    — :class:`~morphix_ui.tabs.advanced_tab.AdvancedParams`
- ``"_trim_duration"`` — ``float``, the probed video duration in seconds
  (used by :class:`TrimValuesHandler` and :class:`LowCompressionHandler`).
  Defaults to ``inf`` if absent.

Adding a new validation rule:
1. Subclass :class:`ValidationHandler` and implement ``check()``.
2. Return ``ValidationResult(severity="error", message=...)`` to block, or
   ``ValidationResult(severity="warning", message=...)`` for a soft warning.
3. Insert an instance into the ``build_chain()`` call in ``main_window.py``.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from morphix_core.validation import check_target_exceeds_file_size, check_trim_values


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of a single validation check."""

    severity: Literal["error", "warning"]
    message: str


class ValidationHandler(ABC):
    """Abstract base for a single link in the validation chain."""

    _next: ValidationHandler | None = None

    def set_next(self, handler: ValidationHandler) -> ValidationHandler:
        """Attach the next handler and return it (enables fluent chaining)."""
        self._next = handler
        return handler

    def handle(self, params: dict) -> list[ValidationResult]:
        """Run this handler then forward to the next.

        - If this handler returns an error, short-circuit (return immediately).
        - If this handler returns a warning, accumulate and continue.
        - If this handler returns None, continue without adding anything.
        """
        results: list[ValidationResult] = []
        result = self.check(params)

        if result is not None:
            results.append(result)
            if result.severity == "error":
                # Short-circuit: do not run further handlers.
                return results

        # Continue to next handler.
        if self._next is not None:
            results.extend(self._next.handle(params))

        return results

    @abstractmethod
    def check(self, params: dict) -> ValidationResult | None:
        """Return a ValidationResult, or ``None`` to pass through."""


class FileSizeHandler(ValidationHandler):
    """Blocks compression if the target size exceeds the source file size."""

    def check(self, params: dict) -> ValidationResult | None:
        target = params.get("Target")
        if target is None:
            return None
        try:
            check_target_exceeds_file_size(target.size_mb, target.input_path)
            return None
        except ValueError as exc:
            return ValidationResult(severity="error", message=str(exc))


class TrimValuesHandler(ValidationHandler):
    """Blocks compression if trim start/end values are invalid."""

    def check(self, params: dict) -> ValidationResult | None:
        trim = params.get("Trim")
        if trim is None or not trim.enabled:
            return None
        if trim.start is None or trim.end is None:
            return ValidationResult(
                severity="error", message="Invalid trim time format."
            )
        duration = params.get("_trim_duration", float("inf"))
        ok, msg = check_trim_values(trim.start, trim.end, duration)
        if ok:
            return None
        return ValidationResult(severity="error", message=msg)


class LowCompressionHandler(ValidationHandler):
    """Warns if the target size is very small relative to the source.

    This is a *soft* warning — the user may proceed if they acknowledge it.
    Checks differ depending on whether trimming is active:

    - **No trim:** warns if target_mb < 5% of input file size.
    - **Trim active:** warns if target_mb < 5% of estimated trimmed clip size.
    """

    def check(self, params: dict) -> ValidationResult | None:
        target = params.get("Target")
        trim = params.get("Trim")
        if target is None:
            return None

        # Cannot check if file doesn't exist.
        if not target.input_path or not os.path.isfile(target.input_path):
            return None

        trim_duration = params.get("_trim_duration", 0.0)

        if trim and trim.enabled and trim.start is not None and trim.end is not None:
            return self._check_trimmed(target, trim, trim_duration)
        return self._check_full(target)

    def _check_full(self, target) -> ValidationResult | None:
        """Non-trimmed: warn if target < 5% of file size."""
        file_size_mb = os.path.getsize(target.input_path) / 1_000_000
        if target.size_mb >= 0.05 * file_size_mb:
            return None
        return ValidationResult(
            severity="warning",
            message=(
                "The target size is less than 5% of the original file size. "
                "The output will very likely look poor.\n\n"
                "Consider using a larger target for a viewable result.\n\n"
                "Do you want to continue anyway?"
            ),
        )

    def _check_trimmed(self, target, trim, trim_duration) -> ValidationResult | None:
        """Trimmed: warn if target < 5% of estimated trimmed clip size."""
        if trim_duration <= 0:
            return None
        file_size_mb = os.path.getsize(target.input_path) / 1_000_000
        segment_duration = trim.end - trim.start
        trim_ratio = segment_duration / trim_duration
        est_trimmed_mb = file_size_mb * trim_ratio
        if target.size_mb >= 0.05 * est_trimmed_mb:
            return None
        min_mb = est_trimmed_mb * 0.05
        return ValidationResult(
            severity="warning",
            message=(
                f"Your trimmed clip is estimated to be about"
                f" {est_trimmed_mb:.1f} MB.\n\n"
                f"The target size ({target.size_mb:.1f} MB) is less than"
                f" 5% of the estimated trimmed clip size. The output will"
                f" very likely look poor.\n\n"
                f"Consider using a target of at least {min_mb:.1f} MB.\n\n"
                "Do you want to continue anyway?"
            ),
        )


def build_chain(*handlers: ValidationHandler) -> ValidationHandler:
    """Wire *handlers* into a chain and return the head.

    Example::

        chain = build_chain(
            FileSizeHandler(), TrimValuesHandler(), LowCompressionHandler()
        )
    """
    if not handlers:
        raise ValueError("build_chain requires at least one handler")
    for i in range(len(handlers) - 1):
        handlers[i].set_next(handlers[i + 1])
    return handlers[0]
