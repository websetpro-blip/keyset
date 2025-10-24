# -*- coding: utf-8 -*-
"""Компактное дерево групп для левой панели."""
from __future__ import annotations

from typing import Dict, Iterable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget


class GroupsTreeWidget(QWidget):
    """Левая панель со списком групп (узкий QTreeWidget)."""

    group_selected = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setMaximumWidth(320)
        self._groups: Dict[str, Iterable] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        title = QLabel("Группы")
        title.setStyleSheet("font-weight: bold;")
        layout.addWidget(title)

        self.tree = QTreeWidget(self)
        self.tree.setColumnCount(1)
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.tree, 1)

        self.set_groups({})

    def set_groups(self, groups: Optional[Dict[str, Iterable]]) -> None:
        """Получить свежий набор групп и перерисовать дерево."""
        self._groups = groups or {}
        self.tree.clear()

        all_item = QTreeWidgetItem(["Все группы"])
        all_item.setData(0, Qt.UserRole, "__all__")
        self.tree.addTopLevelItem(all_item)

        trash_item = QTreeWidgetItem(["Корзина"])
        trash_item.setData(0, Qt.UserRole, "__trash__")
        self.tree.addTopLevelItem(trash_item)

        for name, payload in sorted(self._groups.items(), key=lambda item: str(item[0]).lower()):
            phrases = []
            display_name = str(name)
            if isinstance(payload, dict):
                display_name = payload.get("name", display_name)
                phrases = payload.get("phrases", []) or []
            elif isinstance(payload, (list, tuple, set)):
                phrases = list(payload)

            item = QTreeWidgetItem([f"{display_name} ({len(phrases)})"])
            item.setData(0, Qt.UserRole, display_name)
            self.tree.addTopLevelItem(item)

        self.tree.expandAll()
        self.tree.setCurrentItem(all_item)

    def _on_item_clicked(self, item: QTreeWidgetItem) -> None:
        value = item.data(0, Qt.UserRole)
        if value is None:
            text = item.text(0).split("(")[0].strip()
            value = text
        self.group_selected.emit(str(value))


__all__ = ["GroupsTreeWidget"]
