# -*- coding: utf-8 -*-
"""
MasksTab - Инструмент для работы с масками ключевых слов
Версия: 5.0 с умным генератором, морфологией и визуализацией mind-map
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QTableWidget, QTableWidgetItem, QSpinBox, QComboBox,
    QTabWidget, QTreeWidget, QTreeWidgetItem, QFileDialog, QMessageBox,
    QGroupBox, QCheckBox, QListWidget, QListWidgetItem, QProgressBar,
    QSplitter, QGraphicsView, QGraphicsScene, QGraphicsEllipseItem,
    QGraphicsTextItem, QGraphicsLineItem, QApplication
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QPen
from pathlib import Path
import json
import pyperclip
import csv
import math

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
        self.masks_subtabs.addTab(tab_standard, "Обычный ввод")

        tab_xmind = self._create_xmind_reader_tab()
        self.masks_subtabs.addTab(tab_xmind, "Карта (XMind)")

        tab_multiplier = self._create_multiplier_tab()
        self.masks_subtabs.addTab(tab_multiplier, "Генератор")

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
        
        splitter = QSplitter(Qt.Horizontal)
        
        self.xmind_tree = QTreeWidget()
        self.xmind_tree.setHeaderLabels(["📌 Элемент", "🔷 Тип", "🏷️ Метки"])
        self.xmind_tree.setColumnCount(3)
        splitter.addWidget(self.xmind_tree)
        
        self.xmind_graphics = QGraphicsView()
        self.xmind_graphics.setMinimumWidth(400)
        splitter.addWidget(self.xmind_graphics)
        
        splitter.setSizes([400, 600])
        layout.addWidget(splitter)
        
        ctrl = QHBoxLayout()
        btn_send = QPushButton("➡️ Передать в Генератор")
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
            self._render_mindmap()
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
                type_name = branch.get('type', 'GEN')
                labels = branch.get('labels', [])
                labels_str = ", ".join(labels) if labels else ""
                
                tree_item = QTreeWidgetItem(parent_item) if parent_item else QTreeWidgetItem(self.xmind_tree)
                tree_item.setText(0, f"{branch.get('title','')}")
                tree_item.setText(1, type_name)
                tree_item.setText(2, labels_str)
                
                children = branch.get('children', [])
                if children:
                    add_branch_recursive(tree_item, children)
        add_branch_recursive(None, branches)
        self.xmind_tree.expandAll()

    def _render_mindmap(self):
        """Отобразить XMind карту в режиме 'центр и лучи'"""
        if not self.xmind_data:
            return
        
        scene = QGraphicsScene()
        self.xmind_graphics.setScene(scene)
        
        branches = self.xmind_data.get('branches', [])
        if not branches:
            return
        
        root = branches[0] if branches else None
        if not root:
            return
        
        center_x, center_y = 0, 0
        center_radius = 60
        
        center_ellipse = scene.addEllipse(
            center_x - center_radius, 
            center_y - center_radius,
            center_radius * 2, 
            center_radius * 2,
            QPen(QColor("#3498db"), 2),
            QBrush(QColor("#ecf0f1"))
        )
        
        root_title = root.get('title', 'Root')
        center_text = scene.addText(root_title[:20])
        center_text.setPos(
            center_x - center_text.boundingRect().width() / 2,
            center_y - center_text.boundingRect().height() / 2
        )
        
        children = root.get('children', [])
        if not children:
            return
        
        radius = 300
        n = max(1, len(children))
        
        for i, child in enumerate(children):
            angle = 2 * math.pi * i / n
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            
            node_width = 140
            node_height = 50
            
            node_type = child.get('type', 'GEN')
            color_map = {
                'CORE': '#e74c3c',
                'COMMERCIAL': '#f39c12',
                'INFO': '#3498db',
                'ATTR': '#9b59b6',
                'EXCLUDE': '#7f8c8d',
                'GEN': '#95a5a6'
            }
            color = color_map.get(node_type, '#95a5a6')
            
            node_rect = scene.addRect(
                x - node_width / 2,
                y - node_height / 2,
                node_width,
                node_height,
                QPen(QColor(color), 2),
                QBrush(QColor("#ffffff"))
            )
            
            line = scene.addLine(
                center_x, center_y, x, y,
                QPen(QColor("#bdc3c7"), 1)
            )
            line.setZValue(-1)
            
            child_title = child.get('title', '')[:25]
            child_text = scene.addText(child_title)
            child_text.setPos(
                x - child_text.boundingRect().width() / 2,
                y - child_text.boundingRect().height() / 2
            )
        
        self.xmind_graphics.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
    
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
        btn_copy = QPushButton("📋 Копировать")
        btn_copy.clicked.connect(self.on_multiplier_copy)
        export.addWidget(btn_copy)
        btn_export_csv = QPushButton("💾 Экспорт CSV")
        btn_export_csv.clicked.connect(self.on_multiplier_export_csv)
        export.addWidget(btn_export_csv)
        btn_to_parsing = QPushButton("➡️ Передать в Парсинг")
        btn_to_parsing.clicked.connect(self.on_multiplier_to_parsing)
        export.addWidget(btn_to_parsing)
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

    def on_multiplier_export_csv(self):
        """Экспортировать результаты в CSV файл"""
        if not self.multiplier_results:
            QMessageBox.warning(self, "⚠️", "Нет результатов для экспорта")
            return
        
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить CSV", "", "CSV (*.csv)")
        if not path:
            return
        
        try:
            with open(path, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(["mask", "intent", "score"])
                for r in self.multiplier_results:
                    writer.writerow([
                        r.get('keyword', ''),
                        r.get('intent', ''),
                        r.get('score', 0)
                    ])
            QMessageBox.information(self, "✅", f"Экспортировано {len(self.multiplier_results)} масок в {path}")
        except Exception as e:
            QMessageBox.critical(self, "❌ Ошибка", f"Не удалось сохранить файл: {e}")
    
    def on_multiplier_to_parsing(self):
        """Передать маски в вкладку Парсинг"""
        if not self.multiplier_results:
            QMessageBox.warning(self, "⚠️", "Нет результатов для передачи")
            return
        
        masks = [r['keyword'] for r in self.multiplier_results]
        
        if callable(self._send_cb):
            self._send_cb(masks)
            QMessageBox.information(self, "✅", f"Передано {len(masks)} масок в Парсинг")
        else:
            QMessageBox.warning(self, "⚠️", "Функция передачи не настроена")

    # Вспомогательная интеграция
    def log_message(self, message: str):
        if hasattr(self.parent, 'log_message'):
            self.parent.log_message(message)

    def send_to_parsing(self, phrases: list[str]):
        if callable(self._send_cb):
            self._send_cb(phrases)
