"""Validation chain (Chain of Responsibility) for Morphix UI.

Each handler checks one slice of the compression parameters and either returns
an error message (short-circuiting the chain) or passes through to the next
handler by returning ``None``.

Usage::

    chain = build_chain(FileSizeHandler(), TrimValuesHandler())
    error = chain.handle(params)
    if error:
        show_error(self, error)
        return

The ``params`` dict passed to ``handle()`` should contain:

- ``"Target"``      — :class:`~morphix_ui.tabs.target_tab.TargetParams`
- ``"Trim"``        — :class:`~morphix_ui.tabs.trim_tab.TrimParams`
- ``"Advanced"``    — :class:`~morphix_ui.tabs.advanced_tab.AdvancedParams`
- ``"_trim_duration"`` — ``float``, the probed video duration in seconds
  (used by :class:`TrimValuesHandler`). Defaults to ``inf`` if absent.

Adding a new validation rule:
1. Subclass :class:`ValidationHandler` and implement ``check()``.
2. Insert an instance into the ``build_chain()`` call in ``main_window.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from morphix_core.validation import check_target_exceeds_file_size, check_trim_values


class ValidationHandler(ABC):
    """Abstract base for a single link in the validation chain."""

    _next: ValidationHandler | None = None

    def set_next(self, handler: ValidationHandler) -> ValidationHandler:
        """Attach the next handler and return it (enables fluent chaining)."""
        self._next = handler
        return handler

    def handle(self, params: dict) -> str | None:
        """Run this handler then forward to the next if no error is found."""
        result = self.check(params)
        if result is not None:
            return result
        if self._next is not None:
            return self._next.handle(params)
        return None

    @abstractmethod
    def check(self, params: dict) -> str | None:
        """Return an error message string, or ``None`` to pass through."""


class FileSizeHandler(ValidationHandler):
    """Blocks compression if the target size exceeds the source file size."""

    def check(self, params: dict) -> str | None:
        target = params.get("Target")
        if target is None:
            return None
        try:
            check_target_exceeds_file_size(target.size_mb, target.input_path)
            return None
        except ValueError as exc:
            return str(exc)


class TrimValuesHandler(ValidationHandler):
    """Blocks compression if trim start/end values are invalid."""

    def check(self, params: dict) -> str | None:
        trim = params.get("Trim")
        if trim is None or not trim.enabled:
            return None
        if trim.start is None or trim.end is None:
            return "Invalid trim time format."
        duration = params.get("_trim_duration", float("inf"))
        ok, msg = check_trim_values(trim.start, trim.end, duration)
        return None if ok else msg


def build_chain(*handlers: ValidationHandler) -> ValidationHandler:
    """Wire *handlers* into a chain and return the head.

    Example::

        chain = build_chain(FileSizeHandler(), TrimValuesHandler())
    """
    if not handlers:
        raise ValueError("build_chain requires at least one handler")
    for i in range(len(handlers) - 1):
        handlers[i].set_next(handlers[i + 1])
    return handlers[0]
