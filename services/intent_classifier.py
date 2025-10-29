# -*- coding: utf-8 -*-
"""
IntentClassifier - классификация намерений пользователя
Версия: 2.0 - расширенная rule-based классификация
"""
from __future__ import annotations
from enum import Enum
from typing import Tuple


class Intent(Enum):
    """Типы намерений пользователя"""
    TRANSACTIONAL = "TRANSACTIONAL"
    COMMERCIAL = "COMMERCIAL"
    INFORMATIONAL = "INFORMATIONAL"
    GENERAL = "GENERAL"


def classify_intent(phrase: str) -> str:
    """
    Классифицировать намерение пользователя по фразе
    
    Returns:
        str: Тип намерения (TRANSACTIONAL, INFORMATIONAL, GENERAL)
    """
    p = phrase.lower()
    
    if any(w in p for w in ["купить", "заказать", "цена", "стоимость", "в наличии", "доставка", "оплата", "скидка"]):
        return "TRANSACTIONAL"
    
    if any(w in p for w in ["отзывы", "обзор", "как", "инструкция", "что это", "сравнение", "рейтинг"]):
        return "INFORMATIONAL"
    
    return "GENERAL"


class IntentClassifier:
    """Классификатор намерений на основе правил"""
    
    def classify(self, phrase: str) -> Tuple[Intent, float]:
        """
        Классифицировать намерение с оценкой уверенности
        
        Args:
            phrase: Фраза для классификации
            
        Returns:
            Tuple[Intent, float]: Тип намерения и уверенность (0-1)
        """
        p = (phrase or '').lower()
        
        if any(w in p for w in ("купить", "заказать", "цена", "стоимость", "в наличии", "доставка")):
            return Intent.TRANSACTIONAL, 0.9
        
        if any(w in p for w in ("лучший", "топ", "рейтинги", "сравнить")):
            return Intent.COMMERCIAL, 0.75
        
        if any(w in p for w in ("как", "что", "почему", "инструкция", "обзор")):
            return Intent.INFORMATIONAL, 0.7
        
        return Intent.GENERAL, 0.5
    
    def classify_simple(self, phrase: str) -> str:
        """
        Простая классификация, возвращает только строку
        
        Args:
            phrase: Фраза для классификации
            
        Returns:
            str: Тип намерения
        """
        return classify_intent(phrase)
