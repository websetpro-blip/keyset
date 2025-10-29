# -*- coding: utf-8 -*-
"""
KeywordMultiplier - умное перемножение масок с морфологией и скорингом
Версия: 2.0 - полная реализация с фильтрами
"""
from __future__ import annotations
from itertools import product
from typing import Dict, List

try:
    from .morphology_filter import normalize_phrase, is_good_phrase
    from .intent_classifier import classify_intent
except ImportError:
    from services.morphology_filter import normalize_phrase, is_good_phrase
    from services.intent_classifier import classify_intent


def multiply(groups: Dict[str, List[str]], max_len_words: int = 7) -> List[dict]:
    """
    Умное перемножение масок из групп
    
    Args:
        groups: Словарь с группами слов (core, products, mods, attrs, geo, brands, exclude)
        max_len_words: Максимальное количество слов в маске (по умолчанию 7 - лимит Яндекс.Директа)
    
    Returns:
        List[dict]: Список масок с информацией о намерении и оценке
    """
    buckets = [
        groups.get("core", [""]),
        groups.get("products", [""]),
        groups.get("mods", [""]),
        groups.get("attrs", [""]),
        groups.get("geo", [""]),
        groups.get("brands", [""]),
    ]
    
    raw = []
    for combo in product(*buckets):
        words = [w for w in combo if w]
        if not words:
            continue
        
        phrase = normalize_phrase(words)
        
        if not phrase or len(phrase.split()) > max_len_words:
            continue
        
        if not is_good_phrase(phrase):
            continue
        
        intent = classify_intent(phrase)
        
        score = 0.4
        if intent == "TRANSACTIONAL":
            score = 1.0
        elif intent == "INFORMATIONAL":
            score = 0.6
        
        length_bonus = min(0.2, 0.04 * max(0, len(phrase.split()) - 2))
        score += length_bonus
        
        raw.append({
            "mask": phrase,
            "intent": intent,
            "score": round(score, 3)
        })
    
    uniq = {}
    for r in raw:
        mask_key = r["mask"]
        if mask_key not in uniq or r["score"] > uniq[mask_key]["score"]:
            uniq[mask_key] = r
    
    out = sorted(uniq.values(), key=lambda x: (-x["score"], x["mask"]))
    
    return out


class KeywordMultiplier:
    """Класс для умного перемножения масок"""
    
    def multiply(self, tree_data: Dict, max_kw: int = 10000) -> List[Dict]:
        """
        Генерировать маски из дерева XMind
        
        Args:
            tree_data: Данные из XMind парсера
            max_kw: Максимальное количество масок
        
        Returns:
            List[Dict]: Список масок с полями keyword, intent, score, original
        """
        groups = self._extract_groups_from_tree(tree_data)
        
        results = multiply(groups, max_len_words=7)
        
        formatted = []
        for r in results[:max_kw]:
            formatted.append({
                'keyword': r['mask'],
                'intent': r['intent'],
                'score': r['score'],
                'original': r['mask']
            })
        
        return formatted
    
    def _extract_groups_from_tree(self, tree_data: Dict) -> Dict[str, List[str]]:
        """
        Извлечь группы слов из дерева XMind по типам
        
        Args:
            tree_data: Данные из XMind парсера
        
        Returns:
            Dict[str, List[str]]: Словарь с группами
        """
        groups = {
            "core": [],
            "products": [],
            "mods": [],
            "attrs": [],
            "geo": [],
            "brands": [],
        }
        
        def walk(branches):
            for b in branches:
                title = b.get('title', '').strip()
                if not title:
                    continue
                
                node_type = b.get('type', 'GEN').upper()
                
                if node_type == 'CORE':
                    groups['core'].append(title)
                elif node_type == 'COMMERCIAL':
                    groups['products'].append(title)
                elif node_type == 'ATTR':
                    groups['attrs'].append(title)
                elif node_type == 'INFO':
                    groups['mods'].append(title)
                else:
                    groups['core'].append(title)
                
                walk(b.get('children', []))
        
        branches = tree_data.get('branches', [])
        walk(branches)
        
        for key in groups:
            if not groups[key]:
                groups[key] = [""]
        
        return groups
