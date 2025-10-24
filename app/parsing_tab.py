"""Thin alias for the advanced parsing tab implementation.

This keeps backward compatibility with code that imports
`keyset.app.parsing_tab` while delegating the actual logic to the
feature-rich widget under `keyset.app.tabs.parsing_tab`.
"""
from __future__ import annotations

from .tabs.parsing_tab import ParsingTab

__all__ = ["ParsingTab"]
