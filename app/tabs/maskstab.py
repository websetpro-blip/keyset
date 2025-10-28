# -*- coding: utf-8 -*-
"""
MasksTab - Инструмент для работы с масками ключевых слов
Версия: 4.0 с поддержкой XMind и Smart Multiplier
(скопировано из новое/КЕЙСЕТ/Маски/MASKSTAB_FULL_CODE.md)
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QTableWidget, QTableWidgetItem, QSpinBox, QComboBox,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox,
    QGroupBox, QCheckBox, QListWidget, QListWidgetItem, QProgressBar
)
from PySide6.QtCore import Qt
from pathlib import Path
import json
import pyperclip

# Попытка импортировать core/services, иначе заглушки
try:
    from keyset.core.xmind_parser import XMindParser
except Exception:
    try:
        from core.xmind_parser import XMindParser  # на случай другого PYTHONPATH
    except Exception:
        class XMindParser:
            def __init__(self, path: str) -> None:
                self.path = path
            def parse(self) -> dict:
                # Простейший заглушечный парсер
                return {
                    'title': Path(self.path).stem,
                    'branches': [
                        {'title': 'купить', 'type': 'CORE', 'weight': 1.0, 'active': True, 'children': []}
                    ],
                }

try:
    from keyset.services.keyword_multiplier import KeywordMultiplier
except Exception:
    try:
        from services.keyword_multiplier import KeywordMultiplier
    except Exception:
        class KeywordMultiplier:
            def multiply(self, tree_data: dict, max_kw: int = 1000):
                # Простая генерация на основе узлов CORE
                results = []
                def walk(nodes):
                    for n in nodes:
                        kw = n.get('title', '').strip()
                        if kw:
                            results.append({'keyword': kw, 'intent': 'INFORMATIONAL', 'score': 0.5, 'original': kw})
                        walk(n.get('children', []))
                walk(tree_data.get('branches', []))
                # дедупликация и обрезание
                uniq = []
                seen = set()
                for r in results:
                    k = r['keyword']
                    if k not in seen:
                        uniq.append(r)
                        seen.add(k)
                return uniq[:max_kw]


class MasksTab(QWidget):
    """Главная вкладка для работы с масками ключевых слов"""

    def __init__(self, parent=None, send_to_parsing_callback=None):
        super().__init__(parent)
        self.parent = parent
        self._send_cb = send_to_parsing_callback

        self.xmind_data = None
        self.multiplier_results = None

        self.masks_table = None
        self.groups_list = None

        self.init_ui()

    def init_ui(self):
        main_layout = QHBoxLayout()

        # Левая часть с подвкладками
        left_widget = QWidget()
        left_layout = QVBoxLayout()

        self.masks_subtabs = QTabWidget()
        tab_standard = self._create_standard_masks_tab()
        self.masks_subtabs.addTab(tab_standard, "📋 Обычный ввод")

        tab_xmind = self._create_xmind_reader_tab()
        self.masks_subtabs.addTab(tab_xmind, "🌳 XMind Reader")

        tab_multiplier = self._create_multiplier_tab()
        self.masks_subtabs.addTab(tab_multiplier, "🧬 Multiplier")

        left_layout.addWidget(self.masks_subtabs)
        left_widget.setLayout(left_layout)

        # Правая часть (Группы) — заглушка, не трогаем
        right_widget = QWidget()
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("<b>Управление группами</b>"))
        self.groups_list = QListWidget()
        self.groups_list.addItem("Группа 1")
        right_layout.addWidget(self.groups_list)
        right_widget.setLayout(right_layout)
        right_widget.setMaximumWidth(250)

        center_splitter = QHBoxLayout()
        center_splitter.addWidget(left_widget, 4)
        center_splitter.addWidget(right_widget, 1)
        main_layout.addLayout(center_splitter)

        self.setLayout(main_layout)

    # TAB 1: Обычный ввод
    def _create_standard_masks_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("<b>Исходные маски</b>"))
        self.masks_input = QTextEdit()
        self.masks_input.setPlaceholderText("Введите маски ключевых слов, по одной на строку…")
        self.masks_input.setMinimumHeight(80)
        layout.addWidget(self.masks_input)

        buttons_layout = QHBoxLayout()
        btn_normalize = QPushButton("Нормализовать")
        btn_normalize.clicked.connect(self.on_normalize)
        buttons_layout.addWidget(btn_normalize)
        btn_intersect = QPushButton("Пересечение (ценовик)")
        btn_intersect.clicked.connect(self.on_intersect)
        buttons_layout.addWidget(btn_intersect)
        btn_to_parsing = QPushButton("Пересечь в Парсинг")
        btn_to_parsing.clicked.connect(self.on_send_to_parsing)
        buttons_layout.addWidget(btn_to_parsing)
        layout.addLayout(buttons_layout)

        layout.addWidget(QLabel("<b>Результат</b>"))
        self.masks_table = QTableWidget()
        self.masks_table.setColumnCount(3)
        self.masks_table.setHorizontalHeaderLabels([
            "Стоп-слова, через запятую", "Нормализовать", "Пересечение в Парсинг"
        ])
        self.masks_table.setMaximumHeight(200)
        layout.addWidget(self.masks_table)

        result_buttons = QHBoxLayout()
        result_buttons.addWidget(QPushButton("Очистить"))
        result_buttons.addWidget(QPushButton("Копировать все"))
        result_buttons.addWidget(QPushButton("Сохранить"))
        result_buttons.addWidget(QPushButton("Пауза автоскролла"))
        layout.addLayout(result_buttons)

        layout.addStretch()
        widget.setLayout(layout)
        return widget

    def on_normalize(self):
        text = self.masks_input.toPlainText()
        if not text:
            QMessageBox.warning(self, "⚠️", "Введите маски")
            return
        lines = [ln.strip() for ln in text.strip().split('\n') if ln.strip()]
        self.masks_table.setRowCount(len(lines))
        for i, line in enumerate(lines):
            self.masks_table.setItem(i, 0, QTableWidgetItem(line))
            self.masks_table.setItem(i, 1, QTableWidgetItem("✓"))
            self.masks_table.setItem(i, 2, QTableWidgetItem(""))

    def on_intersect(self):
        if self.masks_table.rowCount() == 0:
            QMessageBox.warning(self, "⚠️", "Сначала добавьте маски")
            return
        QMessageBox.information(self, "✅", "Пересечение выполнено (демо)")

    def on_send_to_parsing(self):
        if self.masks_table.rowCount() == 0:
            QMessageBox.warning(self, "⚠️", "Нет масок для отправки")
            return
        # Демонстрация — копируем первую колонку в буфер
        phrases = []
        for r in range(self.masks_table.rowCount()):
            item = self.masks_table.item(r, 0)
            if item and item.text().strip():
                phrases.append(item.text().strip())
        if phrases and callable(self._send_cb):
            self._send_cb(phrases)
            QMessageBox.information(self, "✅", f"Маски отправлены в Парсинг: {len(phrases)}")

    # TAB 2: XMind Reader
    def _create_xmind_reader_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        btn_load = QPushButton("📂 Загрузить XMind")
        btn_load.clicked.connect(self.on_load_xmind)
        layout.addWidget(btn_load)
        self.xmind_info = QLabel("🔄 Файл не загружен")
        self.xmind_info.setStyleSheet("background:#f0f0f0;padding:5px;border-radius:3px;")
        layout.addWidget(self.xmind_info)
        self.xmind_tree = QTreeWidget()
        self.xmind_tree.setHeaderLabels(["📌 Элемент", "🔷 Тип", "⚖️ Вес"])
        self.xmind_tree.setColumnCount(3)
        layout.addWidget(self.xmind_tree)
        ctrl = QHBoxLayout()
        btn_send = QPushButton("➡️ Передать во множитель")
        btn_send.clicked.connect(self.on_xmind_to_multiplier)
        ctrl.addWidget(btn_send)
        btn_save = QPushButton("💾 Сохранить конфиг")
        btn_save.clicked.connect(self.on_save_xmind_config)
        ctrl.addWidget(btn_save)
        layout.addLayout(ctrl)
        widget.setLayout(layout)
        return widget

    def on_load_xmind(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать XMind файл", "", "XMind (*.xmind)")
        if not path:
            return
        try:
            parser = XMindParser(path)
            self.xmind_data = parser.parse()
            self._display_xmind_tree()
            self.xmind_info.setText(f"✅ Загружено: <b>{self.xmind_data['title']}</b>")
            self.xmind_info.setStyleSheet("background:#c8e6c9;padding:5px;border-radius:3px;")
        except Exception as e:
            QMessageBox.critical(self, "❌ Ошибка парсинга", f"Ошибка: {e}")

    def _display_xmind_tree(self):
        """Отобразить XMind дерево с иерархией (рекурсивное построение)"""
        self.xmind_tree.clear()
        if not self.xmind_data:
            return
        branches = self.xmind_data.get('branches', [])
        if not branches:
            item = QTreeWidgetItem(self.xmind_tree)
            item.setText(0, "⚠️ Нет данных")
            return
        def add_branch_recursive(parent_item, branch_list):
            for branch in branch_list:
                type_name = branch.get('type', 'CORE')
                # иконки можно добавить позже через self._get_type_icon
                tree_item = QTreeWidgetItem(parent_item) if parent_item else QTreeWidgetItem(self.xmind_tree)
                tree_item.setText(0, f"{branch.get('title','')}")
                tree_item.setText(1, type_name)
                weight_percent = int(branch.get('weight', 1.0) * 100)
                tree_item.setText(2, f"{weight_percent}%")
                children = branch.get('children', [])
                if children:
                    add_branch_recursive(tree_item, children)
        add_branch_recursive(None, branches)
        self.xmind_tree.expandAll()

    def _count_tree_items(self, branches):
        count = len(branches)
        for b in branches:
            count += self._count_tree_items(b.get('children', []))
        return count

    def on_xmind_to_multiplier(self):
        if not self.xmind_data:
            QMessageBox.warning(self, "⚠️", "Загрузите XMind файл")
            return
        self.masks_subtabs.setCurrentIndex(2)

    def on_save_xmind_config(self):
        if not self.xmind_data:
            QMessageBox.warning(self, "⚠️", "Нет данных для сохранения")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить конфиг", "", "JSON (*.json)")
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(self.xmind_data, f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "✅", f"Сохранено в {path}")

    # TAB 3: Multiplier
    def _create_multiplier_tab(self):
        widget = QWidget()
        layout = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>⚙️ Параметры:</b>"))
        left.addWidget(QLabel("Макс. масок:"))
        self.multiplier_max_kw = QSpinBox()
        self.multiplier_max_kw.setRange(100, 500000)
        self.multiplier_max_kw.setValue(10000)
        self.multiplier_max_kw.setSingleStep(1000)
        left.addWidget(self.multiplier_max_kw)
        btn_generate = QPushButton("🚀 Генерировать маски")
        btn_generate.clicked.connect(self.on_multiplier_generate)
        left.addWidget(btn_generate)
        left.addStretch()
        center = QVBoxLayout()
        center.addWidget(QLabel("<b>📋 Результаты перемножения:</b>"))
        self.multiplier_table = QTableWidget()
        self.multiplier_table.setColumnCount(4)
        self.multiplier_table.setHorizontalHeaderLabels(["🔑 Маска", "🎯 Намерение", "⭐ Score", "📝 Оригинал"])
        center.addWidget(self.multiplier_table)
        export = QHBoxLayout()
        btn_copy = QPushButton("📋 Копировать в буфер")
        btn_copy.clicked.connect(self.on_multiplier_copy)
        export.addWidget(btn_copy)
        btn_export_txt = QPushButton("💾 Экспорт TXT")
        btn_export_txt.clicked.connect(self.on_multiplier_export_txt)
        export.addWidget(btn_export_txt)
        center.addLayout(export)
        layout.addLayout(left, 1)
        layout.addLayout(center, 3)
        widget.setLayout(layout)
        return widget

    def on_multiplier_generate(self):
        if not self.xmind_data:
            QMessageBox.warning(self, "⚠️", "Сначала загрузите XMind файл в 'XMind Reader'")
            return
        multiplier = KeywordMultiplier()
        results = multiplier.multiply(self.xmind_data, max_kw=self.multiplier_max_kw.value())
        self.multiplier_results = results
        self.multiplier_table.setRowCount(len(results))
        for i, r in enumerate(results):
            self.multiplier_table.setItem(i, 0, QTableWidgetItem(r.get('keyword','')))
            self.multiplier_table.setItem(i, 1, QTableWidgetItem(r.get('intent','')))
            self.multiplier_table.setItem(i, 2, QTableWidgetItem(f"{r.get('score',0):.2f}"))
            self.multiplier_table.setItem(i, 3, QTableWidgetItem(r.get('original','')))

    def on_multiplier_copy(self):
        if not self.multiplier_results:
            QMessageBox.warning(self, "⚠️", "Нет результатов для копирования")
            return
        text = '\n'.join([r['keyword'] for r in self.multiplier_results])
        pyperclip.copy(text)
        QMessageBox.information(self, "✅", f"Скопировано {len(self.multiplier_results)} масок")

    def on_multiplier_export_txt(self):
        if not self.multiplier_results:
            QMessageBox.warning(self, "⚠️", "Нет результатов для экспорта")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить маски", "", "Text (*.txt)")
        if path:
            with open(path, 'w', encoding='utf-8') as f:
                for r in self.multiplier_results:
                    f.write(r['keyword'] + '\n')
            QMessageBox.information(self, "✅", f"Сохранено {len(self.multiplier_results)} масок")

    # Вспомогательная интеграция
    def log_message(self, message: str):
        if hasattr(self.parent, 'log_message'):
            self.parent.log_message(message)

    def send_to_parsing(self, phrases: list[str]):
        if callable(self._send_cb):
            self._send_cb(phrases)
