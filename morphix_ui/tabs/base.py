"""BaseTab — abstract base class for all Morphix UI tabs."""

from __future__ import annotations

import tkinter as tk
from abc import ABC, abstractmethod
from typing import Any


class BaseTab(tk.Frame, ABC):
    """Abstract base for a tab panel.

    Each concrete tab:
    - Sets a class-level ``label`` string (used as the tab button text).
    - Implements ``build()`` to construct its widgets inside *self* (a tk.Frame).
    - Implements ``collect()`` to return a frozen dataclass with its current values.
    - Implements ``validate()`` to return an error message or ``None`` if valid.
    - Implements ``set_enabled()`` to enable/disable its interactive widgets.

    Shared mutable UI state (device map, trim duration, etc.) is available via
    ``self.shared_state`` — a :class:`MorphixState` instance passed at construction.
    """

    label: str  # subclasses set this as a class attribute

    def __init__(self, parent: tk.Misc, shared_state: Any, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self.shared_state = shared_state
        self.build()

    @abstractmethod
    def build(self) -> None:
        """Construct all widgets inside this frame."""

    @abstractmethod
    def collect(self) -> Any:
        """Return a frozen dataclass with this tab's current values."""

    @abstractmethod
    def validate(self) -> str | None:
        """Return an error message string, or None if all inputs are valid."""

    @abstractmethod
    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable all interactive widgets in this tab."""
