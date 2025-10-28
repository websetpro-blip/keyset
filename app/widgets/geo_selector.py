# -*- coding: utf-8 -*-
"""
Виджет выбора регионов Wordstat с поиском и чекбоксами прямо внутри раскладки.
Повторяет правила фронтенда panel.aitibot.ru:
    • при выборе региона снимаем родителя и всех потомков;
    • чекбокс «Все регионы» возвращает дефолтный GeoID 225.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QCheckBox,
    QListWidget,
    QListWidgetItem,
    QLabel,
)


# ════════════════════════════════════════════════════════════════════════════
# Модели данных
# ════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RegionRow:
    """Строка плоского дерева регионов."""

    id: int
    name: str
    path: str
    parent_id: Optional[int]
    depth: int


@dataclass
class RegionModel:
    """Нормализованное дерево регионов."""

    flat: List[RegionRow]
    by_id: Dict[int, RegionRow]
    children: Dict[int, List[int]]


# ════════════════════════════════════════════════════════════════════════════
# Загрузка и нормализация дерева
# ════════════════════════════════════════════════════════════════════════════


_DEFAULT_TREE = {
    "value": 225,
    "label": "Россия",
    "children": [
        {
            "value": 213,
            "label": "Москва",
            "children": [
                {"value": 216, "label": "Балашиха"},
                {"value": 21622, "label": "Химки"},
            ],
        },
        {
            "value": 2,
            "label": "Санкт-Петербург",
            "children": [
                {"value": 10174, "label": "Всеволожск"},
                {"value": 10176, "label": "Колпино"},
            ],
        },
        {
            "value": 54,
            "label": "Новосибирск",
            "children": [
                {"value": 199, "label": "Бердск"},
                {"value": 201, "label": "Искитим"},
            ],
        },
    ],
}


def _load_raw_tree(dataset_path: Path) -> dict:
    if dataset_path.exists():
        try:
            return json.loads(dataset_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return _DEFAULT_TREE


def normalize_regions_tree(raw_root: dict) -> RegionModel:
    """Преобразовать вложенный JSON в плоское представление с индексами."""

    flat: List[RegionRow] = []
    by_id: Dict[int, RegionRow] = {}
    children: Dict[int, List[int]] = {}

    def walk(node: dict, trail: List[str], depth: int, parent_id: Optional[int]) -> None:
        try:
            node_id = int(node["value"])
        except (KeyError, TypeError, ValueError):
            return
        label = str(node.get("label") or "").strip()
        if not label:
            return

        branch = trail + [label]
        row = RegionRow(
            id=node_id,
            name=label,
            path=" / ".join(branch),
            parent_id=parent_id,
            depth=depth,
        )
        flat.append(row)
        by_id[node_id] = row
        if parent_id is not None:
            children.setdefault(parent_id, []).append(node_id)

        for child in node.get("children") or []:
            walk(child, branch, depth + 1, node_id)

    walk(raw_root, [], 0, None)
    return RegionModel(flat=flat, by_id=by_id, children=children)


def load_region_model(dataset_path: Path) -> RegionModel:
    raw = _load_raw_tree(dataset_path)
    root = raw[0] if isinstance(raw, list) and raw else raw
    model = normalize_regions_tree(root)
    if not model.flat:
        model = normalize_regions_tree(_DEFAULT_TREE)
    return model


def short_path(path: str, limit: int = 3) -> str:
    parts = path.split(" / ")
    return " / ".join(parts[-limit:])


def toggle_region(
    selection: Set[int],
    region_id: int,
    checked: bool,
    model: RegionModel,
) -> Set[int]:
    updated = set(selection)

    def drop_descendants(node_id: int) -> None:
        for child_id in model.children.get(node_id, []):
            updated.discard(child_id)
            drop_descendants(child_id)

    def drop_ancestors(node_id: int) -> None:
        parent = model.by_id.get(node_id).parent_id if node_id in model.by_id else None
        while parent is not None:
            updated.discard(parent)
            parent = model.by_id.get(parent).parent_id if parent in model.by_id else None

    if checked:
        updated.add(region_id)
        drop_descendants(region_id)
        drop_ancestors(region_id)
    else:
        updated.discard(region_id)

    return updated


# ════════════════════════════════════════════════════════════════════════════
# Виджет GeoSelector
# ════════════════════════════════════════════════════════════════════════════


class GeoSelector(QWidget):
    """Компактный блок выбора регионов без дополнительных окон."""

    selectionChanged = Signal(dict)  # Dict[int, RegionRow]

    def __init__(self, model: RegionModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._root_row: RegionRow = model.flat[0]
        self._selected_ids: Set[int] = set()
        self._filtered_rows: List[RegionRow] = []
        self._syncing = False

        self._build_ui()
        self._render_items(self._model.flat[1:] or [])
        self._handle_all_toggle(True)

    # ------------------------------------------------------------------ UI ----
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.search = QLineEdit(placeholderText="Поиск региона…")
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.all_check = QCheckBox("Все регионы")
        self.all_check.setChecked(True)
        self.all_check.toggled.connect(self._handle_all_toggle)
        layout.addWidget(self.all_check)

        self.list = QListWidget()
        self.list.itemChanged.connect(self._handle_item_changed)
        layout.addWidget(self.list, 1)

        self.counter = QLabel("Выбрано: 0")
        self.counter.setVisible(False)
        layout.addWidget(self.counter)

    # --------------------------------------------------------------- helpers ---
    def _apply_filter(self, text: str) -> None:
        term = (text or "").strip().lower()
        if not term:
            rows = self._model.flat[1:]
        else:
            rows = [row for row in self._model.flat[1:] if term in row.path.lower()]
        self._render_items(rows)

    def _render_items(self, rows: Sequence[RegionRow]) -> None:
        self._filtered_rows = list(rows)
        self._syncing = True
        self.list.blockSignals(True)
        self.list.clear()

        for row in self._filtered_rows:
            item = QListWidgetItem(f"{short_path(row.path)} ({row.id})")
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setData(Qt.UserRole, row.id)
            item.setData(Qt.UserRole + 1, row.path)
            state = Qt.Checked if row.id in self._selected_ids else Qt.Unchecked
            item.setCheckState(state)
            self.list.addItem(item)

        self.list.blockSignals(False)
        self._syncing = False

    def _handle_all_toggle(self, checked: bool) -> None:
        self.list.setDisabled(checked)
        if checked:
            self._selected_ids.clear()
            self.counter.setVisible(False)
        else:
            self.counter.setVisible(True)
        self._refresh_checks()
        self._emit_selection()

    def _handle_item_changed(self, item: QListWidgetItem) -> None:
        if self._syncing or self.all_check.isChecked():
            return
        region_id = item.data(Qt.UserRole)
        if region_id is None:
            return
        is_checked = item.checkState() == Qt.Checked
        self._selected_ids = toggle_region(self._selected_ids, int(region_id), is_checked, self._model)
        self._refresh_checks()
        self._emit_selection()

    def _refresh_checks(self) -> None:
        self._syncing = True
        self.list.blockSignals(True)
        for index in range(self.list.count()):
            item = self.list.item(index)
            region_id = item.data(Qt.UserRole)
            if region_id is None:
                continue
            state = Qt.Checked if int(region_id) in self._selected_ids else Qt.Unchecked
            item.setCheckState(state)
        self.list.blockSignals(False)
        self._syncing = False

    def _emit_selection(self) -> None:
        if self.all_check.isChecked() or not self._selected_ids:
            selection = {self._root_row.id: self._root_row}
            self.counter.setVisible(False)
        else:
            selection = {rid: self._model.by_id[rid] for rid in self._selected_ids if rid in self._model.by_id}
            self.counter.setVisible(True)
            self.counter.setText(f"Выбрано: {len(selection)}")
        self.selectionChanged.emit(selection)

    # --------------------------------------------------------------- public API
    def set_selected_ids(self, ids: Iterable[int]) -> None:
        normalized = {int(i) for i in ids if int(i) in self._model.by_id}
        if not normalized or normalized == {self._root_row.id}:
            self.all_check.setChecked(True)
            return
        self._selected_ids = normalized
        if self.all_check.isChecked():
            self.all_check.setChecked(False)
        else:
            self._refresh_checks()
            self._emit_selection()

    def export_selection(self) -> Dict[int, RegionRow]:
        if self.all_check.isChecked() or not self._selected_ids:
            return {self._root_row.id: self._root_row}
        return {rid: self._model.by_id[rid] for rid in self._selected_ids if rid in self._model.by_id}


__all__ = [
    "RegionModel",
    "RegionRow",
    "GeoSelector",
    "load_region_model",
    "normalize_regions_tree",
    "short_path",
    "toggle_region",
]

