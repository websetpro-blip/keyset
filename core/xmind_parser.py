# -*- coding: utf-8 -*-
"""
XMind Parser - используем xmindparser из интернета
Версия: 6.0 - Официальная библиотека
"""
from __future__ import annotations
from typing import Dict, List
from pathlib import Path
import sys
import io

# ⚠️ КРИТИЧНО: Установить правильную кодировку для вывода
if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    from xmindparser import xmind_to_dict
    XMINDPARSER_AVAILABLE = True
except ImportError:
    XMINDPARSER_AVAILABLE = False


class XMindParser:
    """Парсер XMind файлов - обёртка над xmindparser"""
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        
        if not self.filepath.exists():
            raise FileNotFoundError(f"XMind file not found: {filepath}")
        
        if not XMINDPARSER_AVAILABLE:
            raise ImportError(
                "xmindparser не установлен!\n"
                "Установите: pip install xmindparser"
            )
    
    def parse(self) -> Dict:
        """Парсить XMind файл и вернуть структуру с иерархией"""
        try:
            raw_data = xmind_to_dict(str(self.filepath))
            return self._convert_to_keyset_format(raw_data)
        except Exception as e:
            print(f"❌ Ошибка парсинга: {str(e)}")
            return {'title': f'Error: {str(e)}', 'branches': []}
    
    def _convert_to_keyset_format(self, raw_data: Dict) -> Dict:
        """Конвертировать формат xmindparser в формат KeySet"""
        title = raw_data.get('title', 'XMind Project')
        sheets = raw_data.get('sheets', [])
        
        if not sheets:
            return {'title': title, 'branches': []}
        
        first_sheet = sheets[0]
        
        root_topic = first_sheet.get('rootTopic')
        if not root_topic:
            return {'title': title, 'branches': []}
        
        branches = self._parse_topic(root_topic)
        return {'title': title, 'branches': branches}
    
    def _parse_topic(self, topic: Dict, level: int = 0, parent_id: str | None = None) -> List[Dict]:
        """Парсить топик рекурсивно"""
        if not isinstance(topic, dict):
            return []
        
        title = topic.get('title', 'Untitled')
        topic_id = topic.get('id', f"topic_{id(topic)}")
        
        children_list: List[Dict] = []
        children = topic.get('children', [])
        if children and isinstance(children, list):
            for child in children:
                children_list.extend(self._parse_topic(child, level + 1, topic_id))
        
        branch = {
            'id': topic_id,
            'title': title.strip() if title else 'Untitled',
            'level': level,
            'parent': parent_id,
            'children': children_list,
            'type': 'CORE',
            'weight': 1.0,
            'active': True,
        }
        
        return [branch]


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        parser = XMindParser(filepath)
        data = parser.parse()
        
        print(f"\n✓ Title: {data['title']}")
        print(f"✓ Total branches: {len(data['branches'])}\n")
        print("Tree structure:")
        
        def print_tree(branches, indent=0):
            for b in branches:
                children_count = len(b.get('children', []))
                print("  " * indent + f"├─ {b['title']} (children: {children_count})")
                if b.get('children'):
                    print_tree(b['children'], indent + 1)
        
        print_tree(data['branches'])
    else:
        print("Usage: python xmind_parser.py /path/to/file.xmind")
        print("\nИли используйте в коде:")
        print("  from xmind_parser import XMindParser")
        print("  parser = XMindParser('file.xmind')")
        print("  data = parser.parse()")
