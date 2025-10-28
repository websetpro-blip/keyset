# -*- coding: utf-8 -*-
"""Заглушка IntentClassifier для MVP."""
from __future__ import annotations
from enum import Enum
from typing import Tuple

class Intent(Enum):
    TRANSACTIONAL = "TRANSACTIONAL"
    COMMERCIAL = "COMMERCIAL"
    INFORMATIONAL = "INFORMATIONAL"

class IntentClassifier:
    def classify(self, phrase: str) -> Tuple[Intent, float]:
        p = (phrase or '').lower()
        if any(w in p for w in ("купить", "цена", "стоимость")):
            return Intent.TRANSACTIONAL, 0.8
        if any(w in p for w in ("лучший", "топ", "рейтинги")):
            return Intent.COMMERCIAL, 0.7
        return Intent.INFORMATIONAL, 0.6
