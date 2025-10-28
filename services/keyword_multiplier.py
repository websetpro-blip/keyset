# -*- coding: utf-8 -*-
"""Упрощённый KeywordMultiplier для MVP."""
from __future__ import annotations
from typing import List, Dict

class KeywordMultiplier:
    def multiply(self, tree_data: Dict, max_kw: int = 10000) -> List[Dict]:
        # Простая генерация: собираем комбинации core + attributes
        cores = []
        attrs = []
        for b in tree_data.get('branches', []):
            t = (b.get('type') or 'CORE').upper()
            if t == 'CORE':
                cores.append(b.get('title','').strip())
            else:
                attrs.append(b.get('title','').strip())
        combos = []
        for c in cores or ['']:
            if attrs:
                for a in attrs:
                    kw = f"{c} {a}".strip()
                    if kw:
                        combos.append({'keyword': kw, 'intent': 'INFORMATIONAL', 'score': 0.6, 'original': kw})
            else:
                if c:
                    combos.append({'keyword': c, 'intent': 'INFORMATIONAL', 'score': 0.5, 'original': c})
        # дедупликация
        uniq = []
        seen = set()
        for r in combos:
            k = r['keyword']
            if k not in seen:
                uniq.append(r)
                seen.add(k)
        return uniq[:max_kw]
