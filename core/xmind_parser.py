# -*- coding: utf-8 -*-
"""
XMind Parser - поддержка XMind 8 и XMind 2020/Zen
Версия: 7.0 - с MindNode и типизацией по меткам
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from pathlib import Path
import sys
import io

if sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    from xmindparser import xmind_to_dict
    XMINDPARSER_AVAILABLE = True
except ImportError:
    XMINDPARSER_AVAILABLE = False


@dataclass
class MindNode:
    """Узел XMind карты с иерархией"""
    title: str
    notes: Optional[str] = None
    labels: List[str] = field(default_factory=list)
    node_type: str = "GEN"  # CORE | COMMERCIAL | INFO | ATTR | EXCLUDE | GEN
    children: List["MindNode"] = field(default_factory=list)


TYPE_BY_LABEL = {
    "CORE": "CORE",
    "COMMERCIAL": "COMMERCIAL",
    "INFO": "INFO",
    "ATTR": "ATTR",
    "EXCLUDE": "EXCLUDE",
}


class XMindParser:
    """Парсер XMind файлов с поддержкой иерархии и типов по меткам"""
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        
        if not self.filepath.exists():
            raise FileNotFoundError(f"XMind file not found: {filepath}")
        
        if not XMINDPARSER_AVAILABLE:
            raise ImportError(
                "xmindparser не установлен!\n"
                "Установите: pip install xmindparser"
            )
    
    def load(self, path: str = None) -> MindNode:
        """Загрузить XMind файл и вернуть корневой MindNode"""
        if path:
            self.filepath = Path(path)
        
        try:
            sheets = xmind_to_dict(str(self.filepath))
            if not sheets:
                return MindNode(title="Empty")
            
            sheet = sheets[0]
            root_topic = sheet.get("topic", {})
            return self._topic_to_node(root_topic)
        except Exception as e:
            print(f"❌ Ошибка парсинга XMind: {str(e)}")
            return MindNode(title=f"Error: {str(e)}")
    
    def parse(self) -> Dict:
        """Парсить XMind файл и вернуть структуру для совместимости с MasksTab"""
        root_node = self.load()
        return self._node_to_legacy_format(root_node)
    
    def _topic_to_node(self, topic: dict) -> MindNode:
        """Конвертировать топик из xmindparser в MindNode"""
        if not isinstance(topic, dict):
            return MindNode(title="Invalid")
        
        title = topic.get("title") or topic.get("topic") or ""
        labels = topic.get("labels") or []
        
        notes = None
        if "notes" in topic:
            n = topic["notes"]
            notes = n.get("plain") if isinstance(n, dict) else str(n)
        
        node_type = "GEN"
        for lb in labels:
            lb_upper = lb.upper()
            if lb_upper in TYPE_BY_LABEL:
                node_type = TYPE_BY_LABEL[lb_upper]
                break
        
        node = MindNode(
            title=title.strip() if title else "",
            notes=notes,
            labels=labels,
            node_type=node_type
        )
        
        for child in topic.get("topics", []):
            node.children.append(self._topic_to_node(child))
        
        return node
    
    def _node_to_legacy_format(self, node: MindNode) -> Dict:
        """Конвертировать MindNode в старый формат для совместимости"""
        branches = self._node_to_branches(node)
        return {
            'title': node.title or 'XMind Project',
            'branches': branches
        }
    
    def _node_to_branches(self, node: MindNode, level: int = 0, parent_id: str = None) -> List[Dict]:
        """Рекурсивно конвертировать MindNode в список веток"""
        node_id = f"node_{id(node)}"
        
        children_list = []
        for child in node.children:
            children_list.extend(self._node_to_branches(child, level + 1, node_id))
        
        branch = {
            'id': node_id,
            'title': node.title,
            'level': level,
            'parent': parent_id,
            'children': children_list,
            'type': node.node_type,
            'weight': 1.0,
            'active': True,
            'labels': node.labels,
            'notes': node.notes,
        }
        
        return [branch]


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        parser = XMindParser(filepath)
        root = parser.load()
        
        print(f"\n✓ Title: {root.title}")
        print(f"✓ Type: {root.node_type}")
        print(f"✓ Children: {len(root.children)}\n")
        print("Tree structure:")
        
        def print_tree(node: MindNode, indent=0):
            children_count = len(node.children)
            type_str = f"[{node.node_type}]" if node.node_type != "GEN" else ""
            print("  " * indent + f"├─ {node.title} {type_str} (children: {children_count})")
            for child in node.children:
                print_tree(child, indent + 1)
        
        print_tree(root)
    else:
        print("Usage: python xmind_parser.py /path/to/file.xmind")
        print("\nИли используйте в коде:")
        print("  from core.xmind_parser import XMindParser")
        print("  parser = XMindParser('file.xmind')")
        print("  root = parser.load()")
