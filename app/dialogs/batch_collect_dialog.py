# -*- coding: utf-8 -*-
"""Диалог пакетного сбора фраз с выбором регионов (как в AitiCollector)"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QCheckBox,
    QSpinBox,
    QTextEdit,
    QPushButton,
    QScrollArea,
    QWidget,
    QSplitter,
)


class RegionNode:
    """Узел дерева регионов"""
    def __init__(self, id: int, name: str, children: Optional[List[RegionNode]] = None, parent: Optional[int] = None):
        self.id = id
        self.name = name
        self.children = children or []
        self.parent = parent


class FlatRegion:
    """Плоское представление региона"""
    def __init__(self, id: int, name: str, path: str, parent: Optional[int], depth: int):
        self.id = id
        self.name = name
        self.path = path
        self.parent = parent
        self.depth = depth


class RegionSelector(QWidget):
    """Виджет выбора регионов с логикой из AitiCollector"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

        self.geo_tree: Optional[RegionNode] = None
        self.flat_regions: List[FlatRegion] = []
        self.region_items: Dict[int, QTreeWidgetItem] = {}
        self.selected_ids: List[int] = []
        self.all_regions_mode = True

        self._init_ui()
        self._load_regions()

    def _init_ui(self):
        """Инициализация UI"""
        from PySide6.QtWidgets import QTreeWidget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Поиск
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск региона...")
        self.search_input.textChanged.connect(self._filter_regions)
        layout.addWidget(self.search_input)

        # Чекбокс "Все регионы"
        self.chk_all_regions = QCheckBox("Все регионы")
        self.chk_all_regions.setChecked(True)
        self.chk_all_regions.stateChanged.connect(self._on_all_regions_changed)
        layout.addWidget(self.chk_all_regions)

        # Дерево регионов
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setMinimumHeight(300)
        self.tree_widget.setMaximumHeight(400)
        self.tree_widget.itemChanged.connect(self._on_tree_item_changed)
        layout.addWidget(self.tree_widget)

        # Счётчик выбранных
        self.selected_label = QLabel("Выбрано: 0")
        self.selected_label.setStyleSheet("font-size: 10pt; color: #888;")
        layout.addWidget(self.selected_label)

    def _load_regions(self):
        """Загрузка дерева регионов"""
        data_file = Path(__file__).resolve().parents[2] / "data" / "regions_tree_full.json"

        if not data_file.exists():
            return

        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Преобразуем JSON в RegionNode
            self.geo_tree = self._json_to_node(data[0]) if data else None

            if self.geo_tree:
                # Создаём плоский список регионов
                self.flat_regions = self._index_geo(self.geo_tree)
                self._render_regions()
        except Exception as e:
            print(f"Ошибка загрузки регионов: {e}")

    def _json_to_node(self, data: Dict[str, Any]) -> RegionNode:
        """Преобразование JSON в RegionNode"""
        node = RegionNode(
            id=int(data["value"]),
            name=data["label"]
        )

        for child_data in data.get("children", []):
            child = self._json_to_node(child_data)
            child.parent = node.id
            node.children.append(child)

        return node

    def _index_geo(self, root: RegionNode) -> List[FlatRegion]:
        """Индексация дерева регионов в плоский список"""
        flat = []

        def walk(node: RegionNode, trail: List[str], depth: int, parent: Optional[int] = None):
            path = trail + [node.name]
            flat_region = FlatRegion(
                id=node.id,
                name=node.name,
                path=" / ".join(path),
                parent=parent,
                depth=depth
            )
            flat.append(flat_region)

            for child in node.children:
                walk(child, path, depth + 1, node.id)

        walk(root, [], 0)
        return flat

    def _render_regions(self):
        """Отрисовка дерева регионов"""
        from PySide6.QtWidgets import QTreeWidgetItem

        self.tree_widget.clear()
        self.region_items.clear()

        if not self.geo_tree:
            return

        # Создаём дерево рекурсивно
        def create_tree_item(node: RegionNode, parent_item: Optional[QTreeWidgetItem] = None):
            if parent_item:
                item = QTreeWidgetItem(parent_item)
            else:
                item = QTreeWidgetItem(self.tree_widget)

            item.setText(0, f"{node.name} ({node.id})")
            item.setCheckState(0, Qt.Unchecked)
            item.setData(0, Qt.UserRole, node.id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)

            self.region_items[node.id] = item

            # Создаём детей
            for child in node.children:
                create_tree_item(child, item)

        create_tree_item(self.geo_tree)
        self.tree_widget.expandAll()

    def _filter_regions(self, query: str):
        """Фильтрация регионов по поисковому запросу"""
        query = query.lower().strip()

        def filter_item(item: 'QTreeWidgetItem') -> bool:
            """Рекурсивная фильтрация элементов дерева"""
            text = item.text(0).lower()
            visible = not query or query in text

            # Проверяем детей
            for i in range(item.childCount()):
                child = item.child(i)
                if filter_item(child):
                    visible = True

            item.setHidden(not visible)
            return visible

        # Применяем фильтр ко всем корневым элементам
        for i in range(self.tree_widget.topLevelItemCount()):
            filter_item(self.tree_widget.topLevelItem(i))

    def _on_all_regions_changed(self, state: int):
        """Обработка изменения чекбокса 'Все регионы'"""
        self.all_regions_mode = (state == Qt.Checked)

        if self.all_regions_mode:
            self.selected_ids.clear()
            # Снимаем все чекбоксы в дереве
            self.tree_widget.blockSignals(True)
            for item in self.region_items.values():
                item.setCheckState(0, Qt.Unchecked)
            self.tree_widget.blockSignals(False)

        self._update_selected_label()

    def _on_tree_item_changed(self, item, column):
        """Обработка изменения чекбокса в дереве"""
        if column != 0:
            return

        region_id = item.data(0, Qt.UserRole)
        checked = item.checkState(0) == Qt.Checked

        # Снимаем режим "Все регионы"
        if checked:
            self.all_regions_mode = False
            self.chk_all_regions.blockSignals(True)
            self.chk_all_regions.setChecked(False)
            self.chk_all_regions.blockSignals(False)

        # Блокируем сигналы чтобы избежать рекурсии
        self.tree_widget.blockSignals(True)

        if checked:
            # Добавляем регион
            if region_id not in self.selected_ids:
                self.selected_ids.append(region_id)

            # Удаляем всех потомков
            self._uncheck_descendants(item)

            # Удаляем всех предков
            self._uncheck_ancestors(item)
        else:
            # Убираем регион из выбранных
            if region_id in self.selected_ids:
                self.selected_ids.remove(region_id)

        self.tree_widget.blockSignals(False)
        self._update_selected_label()

    def _uncheck_descendants(self, item):
        """Снять чекбоксы со всех потомков"""
        for i in range(item.childCount()):
            child = item.child(i)
            child_id = child.data(0, Qt.UserRole)

            if child_id in self.selected_ids:
                self.selected_ids.remove(child_id)
            child.setCheckState(0, Qt.Unchecked)

            # Рекурсивно для потомков
            self._uncheck_descendants(child)

    def _uncheck_ancestors(self, item):
        """Снять чекбоксы со всех предков"""
        parent = item.parent()
        if parent:
            parent_id = parent.data(0, Qt.UserRole)
            if parent_id in self.selected_ids:
                self.selected_ids.remove(parent_id)
            parent.setCheckState(0, Qt.Unchecked)

            # Рекурсивно вверх
            self._uncheck_ancestors(parent)

    def _update_selected_label(self):
        """Обновление метки с количеством выбранных"""
        if self.all_regions_mode:
            self.selected_label.setText("Выбрано: Все регионы")
        else:
            self.selected_label.setText(f"Выбрано: {len(self.selected_ids)}")

    def get_selected_geo_ids(self) -> List[int]:
        """Получение выбранных ID регионов"""
        if self.all_regions_mode or not self.selected_ids:
            # По умолчанию Россия (225)
            return [225]
        return self.selected_ids


class BatchCollectDialog(QDialog):
    """Диалог пакетного сбора фраз из Wordstat"""

    # Сигнал для передачи результатов
    collect_requested = Signal(list, dict)  # phrases, settings

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Пакетный сбор фраз из Yandex.Wordstat")
        self.setMinimumSize(900, 700)
        self._init_ui()

    def _init_ui(self):
        """Инициализация UI"""
        layout = QHBoxLayout(self)

        # Главный сплиттер: левая панель (настройки) + правая (фразы)
        splitter = QSplitter(Qt.Horizontal)

        # ═══════════════════════════════════════════════════════════
        # ЛЕВАЯ ПАНЕЛЬ - Настройки сбора
        # ═══════════════════════════════════════════════════════════
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # --- Регионы ---
        regions_group = QGroupBox("Регионы")
        regions_layout = QVBoxLayout(regions_group)

        self.region_selector = RegionSelector()
        regions_layout.addWidget(self.region_selector)

        left_layout.addWidget(regions_group)

        # --- Порог показов ---
        threshold_group = QGroupBox("Порог показов")
        threshold_layout = QVBoxLayout(threshold_group)

        self.threshold_spin = QSpinBox()
        self.threshold_spin.setMinimum(0)
        self.threshold_spin.setMaximum(100000)
        self.threshold_spin.setValue(20)
        self.threshold_spin.setSuffix(" показов")

        threshold_layout.addWidget(self.threshold_spin)
        left_layout.addWidget(threshold_group)

        left_layout.addStretch()

        # ═══════════════════════════════════════════════════════════
        # ПРАВАЯ ПАНЕЛЬ - Фразы и действия
        # ═══════════════════════════════════════════════════════════
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Заголовок
        title = QLabel("Пакетный сбор фраз из левой колонки Yandex.Wordstat")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; padding: 10px;")
        right_layout.addWidget(title)

        # Режим добавления
        mode_group = QGroupBox("Режим добавления фраз")
        mode_layout = QHBoxLayout(mode_group)

        self.chk_to_active_group = QCheckBox("в активную группу")
        self.chk_distribute_by_tabs = QCheckBox("распределить по группам")
        self.chk_distribute_by_tabs.setChecked(True)

        mode_layout.addWidget(self.chk_to_active_group)
        mode_layout.addWidget(self.chk_distribute_by_tabs)

        right_layout.addWidget(mode_group)

        # Опции
        options_layout = QHBoxLayout()

        self.chk_skip_existing = QCheckBox("Пропускать фразы, которые уже есть в любой группе")
        self.chk_skip_existing.setChecked(True)

        options_layout.addWidget(self.chk_skip_existing)
        right_layout.addLayout(options_layout)

        # База данных
        db_layout = QHBoxLayout()
        db_layout.addWidget(QLabel("База данных:"))
        self.db_label = QLabel("<b>все</b>")
        db_layout.addWidget(self.db_label)
        db_layout.addStretch()
        right_layout.addLayout(db_layout)

        # Регион (только для отображения)
        region_layout = QHBoxLayout()
        region_layout.addWidget(QLabel("Регион:"))
        self.region_display = QLabel("<i>не задано</i>")
        region_layout.addWidget(self.region_display)

        btn_change_region = QPushButton("Изменить")
        btn_change_region.clicked.connect(self._update_region_display)
        region_layout.addWidget(btn_change_region)
        region_layout.addStretch()
        right_layout.addLayout(region_layout)

        # Режим сбора
        collection_layout = QHBoxLayout()
        collection_layout.addWidget(QLabel("Режим сбора:"))
        self.collection_mode_label = QLabel("<b>левая колонка</b>")
        collection_layout.addWidget(self.collection_mode_label)
        collection_layout.addStretch()
        right_layout.addLayout(collection_layout)

        # Опции интеграции
        integration_layout = QVBoxLayout()
        self.chk_integrate_minus = QCheckBox("Интегрировать минус-слова в запросы")
        self.chk_add_plus = QCheckBox("Добавлять \"+\" оператор к словам из списка")
        integration_layout.addWidget(self.chk_integrate_minus)
        integration_layout.addWidget(self.chk_add_plus)
        right_layout.addLayout(integration_layout)

        # Поле ввода фраз
        phrases_label = QLabel("Список фраз для сбора:")
        phrases_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        right_layout.addWidget(phrases_label)

        self.phrases_edit = QTextEdit()
        self.phrases_edit.setPlaceholderText(
            "Введите фразы для сбора частотности...\n\n"
            "Например:\n"
            "купить телефон\n"
            "ремонт квартиры\n"
            "заказать пиццу"
        )
        self.phrases_edit.setMinimumHeight(250)
        right_layout.addWidget(self.phrases_edit)

        # Кнопки действий
        buttons_layout = QHBoxLayout()

        self.btn_start = QPushButton("▶ Начать сбор")
        self.btn_start.setStyleSheet("QPushButton { font-weight: bold; padding: 10px; background-color: #4CAF50; color: white; }")
        self.btn_start.clicked.connect(self._on_start_collect)

        self.btn_load_file = QPushButton("📂 Загрузить из файла...")
        self.btn_load_file.clicked.connect(self._on_load_from_file)

        self.btn_clear_lists = QPushButton("🗑 Очистить все списки")
        self.btn_clear_lists.clicked.connect(self.phrases_edit.clear)

        buttons_layout.addWidget(self.btn_start)
        buttons_layout.addWidget(self.btn_load_file)
        buttons_layout.addWidget(self.btn_clear_lists)
        buttons_layout.addStretch()

        right_layout.addLayout(buttons_layout)

        # Добавляем панели в сплиттер
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)

        # Пропорции: 30% левая, 70% правая
        splitter.setSizes([300, 600])

        layout.addWidget(splitter)

        # Обновляем дисплей региона
        self._update_region_display()

    def _update_region_display(self):
        """Обновление отображения выбранного региона"""
        selected_ids = self.region_selector.get_selected_geo_ids()

        if not selected_ids or (len(selected_ids) == 1 and selected_ids[0] == 225):
            self.region_display.setText("<i>Все регионы (Россия)</i>")
        else:
            region_names = []
            for region in self.region_selector.flat_regions:
                if region.id in selected_ids:
                    region_names.append(region.name)

            if region_names:
                self.region_display.setText(", ".join(region_names[:3]) + ("..." if len(region_names) > 3 else ""))
            else:
                self.region_display.setText("<i>не задано</i>")

    def _on_start_collect(self):
        """Начать сбор фраз"""
        # Получаем фразы
        text = self.phrases_edit.toPlainText().strip()
        if not text:
            return

        phrases = [line.strip() for line in text.splitlines() if line.strip()]

        if not phrases:
            return

        # Собираем настройки
        settings = {
            "geo_ids": self.region_selector.get_selected_geo_ids(),
            "threshold": self.threshold_spin.value(),
            "mode": {
                "to_active_group": self.chk_to_active_group.isChecked(),
                "distribute_by_tabs": self.chk_distribute_by_tabs.isChecked(),
            },
            "options": {
                "skip_existing": self.chk_skip_existing.isChecked(),
                "integrate_minus": self.chk_integrate_minus.isChecked(),
                "add_plus": self.chk_add_plus.isChecked(),
            }
        }

        # Отправляем сигнал
        self.collect_requested.emit(phrases, settings)

        # Закрываем диалог
        self.accept()

    def _on_load_from_file(self):
        """Загрузить фразы из файла"""
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл с фразами",
            "",
            "Text Files (*.txt);;All Files (*)"
        )

        if file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.phrases_edit.setPlainText(content)
            except Exception as e:
                print(f"Ошибка загрузки файла: {e}")
