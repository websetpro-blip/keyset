# -*- coding: utf-8 -*-
"""
Вкладка "Данные" - просмотр всех собранных данных из БД.
Аналог вкладки "Данные" в Key Collector.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QTableWidget,
    QTableWidgetItem, QGroupBox, QPushButton, 
    QComboBox, QLabel, QLineEdit, QCheckBox
)
from PySide6.QtCore import Qt, Signal


class DataTab(QWidget):
    """
    Вкладка "Данные" - просмотр всех собранных данных из БД.
    Аналог вкладки "Данные" в Key Collector.
    
    Структура:
    - Центр: таблица всех собранных фраз
    - Справа: панель управления группами + фильтры
    """
    
    def __init__(self):
        super().__init__()
        self.setup_ui()
    
    def setup_ui(self):
        """Настройка интерфейса."""
        layout = QHBoxLayout()
        
        # === ЦЕНТР: Таблица данных ===
        center_panel = self.create_center_panel()
        layout.addWidget(center_panel, stretch=3)
        
        # === ПРАВАЯ ПАНЕЛЬ: Группы + Фильтры ===
        right_panel = self.create_right_panel()
        layout.addWidget(right_panel, stretch=1)
        
        self.setLayout(layout)
    
    def create_center_panel(self):
        """Центральная панель - таблица данных."""
        group = QGroupBox("Собранные данные")
        layout = QVBoxLayout()
        
        # Таблица данных
        self.data_table = QTableWidget()
        self.data_table.setColumnCount(8)
        self.data_table.setHorizontalHeaderLabels([
            "Фраза", "WS", '"WS"', "!WS", "Группа", "Регион", "Дата", "Источник"
        ])
        self.data_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.data_table.setAlternatingRowColors(True)
        self.data_table.setSortingEnabled(True)
        
        # Загрузка данных из БД (заглушка)
        self.load_data()
        
        layout.addWidget(self.data_table)
        
        # Кнопки под таблицей
        btn_layout = QHBoxLayout()
        
        btn_export = QPushButton("📤 Экспорт выборки")
        btn_export.clicked.connect(self.on_export_selection)
        btn_layout.addWidget(btn_export)
        
        btn_delete = QPushButton("🗑️ Удалить выбранное")
        btn_delete.clicked.connect(self.on_delete_selected)
        btn_layout.addWidget(btn_delete)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        group.setLayout(layout)
        return group
    
    def create_right_panel(self):
        """Правая панель - управление группами и фильтры."""
        group = QGroupBox("Управление и фильтры")
        layout = QVBoxLayout()
        
        # === Управление группами ===
        lbl_groups = QLabel("Управление группами:")
        lbl_groups.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_groups)
        
        self.cmb_group = QComboBox()
        self.cmb_group.addItems(["Все", "косметические", "черновые", "окрасочные"])
        self.cmb_group.currentTextChanged.connect(self.on_group_filter_changed)
        layout.addWidget(self.cmb_group)
        
        btn_create_group = QPushButton("📁 Создать группу")
        btn_create_group.clicked.connect(self.on_create_group)
        layout.addWidget(btn_create_group)
        
        btn_rename_group = QPushButton("✏️ Переименовать")
        btn_rename_group.clicked.connect(self.on_rename_group)
        layout.addWidget(btn_rename_group)
        
        btn_delete_group = QPushButton("🗑️ Удалить группу")
        btn_delete_group.clicked.connect(self.on_delete_group)
        layout.addWidget(btn_delete_group)
        
        layout.addSpacing(20)
        
        # === Фильтры ===
        lbl_filters = QLabel("Фильтры:")
        lbl_filters.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_filters)
        
        # Поиск по фразе
        lbl_search = QLabel("Поиск:")
        layout.addWidget(lbl_search)
        
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Введите фразу...")
        self.txt_search.textChanged.connect(self.on_search_changed)
        layout.addWidget(self.txt_search)
        
        # Фильтр по частотности
        self.chk_no_freq = QCheckBox("Без частотности (WS = 0)")
        self.chk_no_freq.toggled.connect(self.apply_filters)
        layout.addWidget(self.chk_no_freq)
        
        self.chk_low_freq = QCheckBox("Низкочастотные (WS < 100)")
        self.chk_low_freq.toggled.connect(self.apply_filters)
        layout.addWidget(self.chk_low_freq)
        
        self.chk_high_freq = QCheckBox("Высокочастотные (WS > 1000)")
        self.chk_high_freq.toggled.connect(self.apply_filters)
        layout.addWidget(self.chk_high_freq)
        
        # Кнопка сброса фильтров
        btn_reset = QPushButton("🔄 Сбросить фильтры")
        btn_reset.clicked.connect(self.reset_filters)
        layout.addWidget(btn_reset)
        
        layout.addStretch()
        
        # === Экспорт структуры групп ===
        btn_export_structure = QPushButton("📊 Экспорт структуры")
        btn_export_structure.clicked.connect(self.on_export_structure)
        layout.addWidget(btn_export_structure)
        
        btn_import_structure = QPushButton("📥 Импорт структуры")
        btn_import_structure.clicked.connect(self.on_import_structure)
        layout.addWidget(btn_import_structure)
        
        group.setLayout(layout)
        return group
    
    def load_data(self):
        """Загрузка данных из БД (заглушка)."""
        # TODO: Загрузить из freq_results
        sample_data = [
            ["отделочные финишные", "245", "-", "-", "окрасочные", "Москва (213)", "23.10.2025", "Wordstat"],
            ["финишные черновые", "2", "-", "-", "финишные", "Москва (213)", "23.10.2025", "Wordstat"],
            ["отделка окрасочные", "349", "-", "-", "окрасочные", "Москва (213)", "23.10.2025", "Wordstat"],
        ]
        
        self.data_table.setRowCount(len(sample_data))
        for row, row_data in enumerate(sample_data):
            for col, value in enumerate(row_data):
                self.data_table.setItem(row, col, QTableWidgetItem(value))
    
    def on_group_filter_changed(self, group_name: str):
        """Фильтрация по группе."""
        print(f"[Данные] Фильтр по группе: {group_name}")
        self.apply_filters()
    
    def on_search_changed(self, text: str):
        """Поиск по фразе."""
        print(f"[Данные] Поиск: {text}")
        self.apply_filters()
    
    def apply_filters(self):
        """Применение всех фильтров."""
        # TODO: Фильтрация таблицы по критериям
        print("[Данные] Применение фильтров")
    
    def reset_filters(self):
        """Сброс всех фильтров."""
        self.cmb_group.setCurrentIndex(0)
        self.txt_search.clear()
        self.chk_no_freq.setChecked(False)
        self.chk_low_freq.setChecked(False)
        self.chk_high_freq.setChecked(False)
        self.apply_filters()
    
    def on_create_group(self):
        """Создание группы."""
        # TODO: Диалог создания
        print("[Данные] Создать группу")
    
    def on_rename_group(self):
        """Переименование группы."""
        # TODO: Диалог переименования
        print("[Данные] Переименовать группу")
    
    def on_delete_group(self):
        """Удаление группы."""
        # TODO: Подтверждение удаления
        print("[Данные] Удалить группу")
    
    def on_export_selection(self):
        """Экспорт выбранных данных."""
        # TODO: Диалог экспорта
        print("[Данные] Экспорт выборки")
    
    def on_delete_selected(self):
        """Удаление выбранных строк."""
        # TODO: Подтверждение удаления
        print("[Данные] Удалить выбранное")
    
    def on_export_structure(self):
        """Экспорт структуры групп."""
        # TODO: Экспорт в JSON
        print("[Данные] Экспорт структуры")
    
    def on_import_structure(self):
        """Импорт структуры групп."""
        # TODO: Импорт из JSON
        print("[Данные] Импорт структуры")