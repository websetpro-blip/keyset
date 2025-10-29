# -*- coding: utf-8 -*-
"""
MorphologyFilter - нормализация и фильтрация фраз с использованием pymorphy2
Версия: 2.0 - полная реализация с морфологией
"""
from __future__ import annotations
import re

try:
    import pymorphy2
    _morph = pymorphy2.MorphAnalyzer()
    PYMORPHY_AVAILABLE = True
except (ImportError, AttributeError) as e:
    _morph = None
    PYMORPHY_AVAILABLE = False
    import warnings
    warnings.warn(f"pymorphy2 недоступен: {e}. Морфология будет работать в упрощенном режиме.")

COMM_VERBS = {
    "купить", "заказать", "цена", "стоимость", "доставка", 
    "скидка", "аренда", "продажа", "заказ", "оплата"
}

STOP_WORDS = {
    "и", "в", "на", "с", "к", "у", "о", "от", "по", "для", "за", 
    "без", "до", "из", "при", "про", "через", "под", "над"
}


def normalize_token(tok: str) -> str:
    """Нормализовать токен (приведение к нормальной форме)"""
    tok = tok.strip().lower()
    tok = re.sub(r"[\"''""„]", "", tok)
    
    if not tok:
        return tok
    
    if PYMORPHY_AVAILABLE and _morph:
        parsed = _morph.parse(tok)
        if parsed:
            return parsed[0].normal_form
    
    return tok


def normalize_phrase(words) -> str:
    """
    Нормализовать фразу: привести к нормальной форме и упорядочить слова
    
    Порядок: [коммерческие глаголы] [объекты] [атрибуты]
    """
    if isinstance(words, str):
        words = words.split()
    
    norm = [normalize_token(w) for w in words if w and w.lower() not in STOP_WORDS]
    
    order = []
    comm_words = [w for w in norm if w in COMM_VERBS]
    other_words = [w for w in norm if w not in comm_words]
    
    order.extend(comm_words)
    order.extend(other_words)
    
    phrase = " ".join(order)
    phrase = re.sub(r"\s+", " ", phrase).strip()
    
    return phrase


def is_good_phrase(phrase: str) -> bool:
    """
    Проверить, является ли фраза корректной для Яндекс.Директа
    
    Критерии:
    - Минимум 3 символа
    - Максимум 7 слов (лимит Яндекс.Директа)
    - Нет повторов слов (или максимум 1 повтор)
    """
    if not phrase or len(phrase) < 3:
        return False
    
    words = phrase.split()
    
    if len(words) > 7:
        return False
    
    uniq = set(words)
    if len(uniq) < len(words) - 1:
        return False
    
    return True


class MorphologyFilter:
    """Класс для работы с морфологией и фильтрацией фраз"""
    
    def __init__(self):
        self.morph_available = PYMORPHY_AVAILABLE
    
    def is_valid_phrase(self, phrase: str) -> bool:
        """Проверить валидность фразы"""
        return is_good_phrase(phrase)
    
    def normalize_phrase(self, phrase: str) -> str:
        """Нормализовать фразу"""
        if isinstance(phrase, str):
            words = phrase.split()
        else:
            words = phrase
        return normalize_phrase(words)
    
    def get_word_order_score(self, phrase: str) -> float:
        """
        Оценить порядок слов в фразе
        
        Коммерческие фразы получают более высокий балл
        """
        if not phrase:
            return 0.0
        
        words = phrase.lower().split()
        
        score = 0.5
        
        if any(w in COMM_VERBS for w in words):
            score += 0.3
        
        length_bonus = min(0.2, 0.04 * max(0, len(words) - 2))
        score += length_bonus
        
        return min(1.0, score)
