# -*- coding: utf-8 -*-
"""Заглушка MorphologyFilter для MVP."""
from __future__ import annotations

class MorphologyFilter:
    def is_valid_phrase(self, phrase: str) -> bool:
        return bool(phrase and len(phrase.split()) >= 1)

    def normalize_phrase(self, phrase: str) -> str:
        return phrase.strip().lower()

    def get_word_order_score(self, phrase: str) -> float:
        # простая оценка по длине
        return max(0.0, min(1.0, len(phrase) / 30.0))
