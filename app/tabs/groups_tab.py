# -*- coding: utf-8 -*-
"""
Вкладка "Группы" - управление иерархией групп.
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout,
    QTreeWidget, QTreeWidgetItem, QPushButton,
    QLabel, QComboBox, QGroupBox, QMessageBox,
    QInputDialog, QMenu
)
from PySide6.QtCore import Qt, Signal
from pathlib import Path
import json


class GroupsTab(QWidget):
    """
    Вкладка "Группы" - управление иерархией групп.
    """

    groupSelected = Signal(str)  # Сигнал при выборе группы

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        """Настройка интерфейса."""
        layout = QHBoxLayout()
        
        # === ЛЕВАЯ ПАНЕЛЬ: Дерево групп ===
        left_panel = self.create_left_panel()
        layout.addWidget(left_panel, stretch=2)
        
        # === ПРАВАЯ ПАНЕЛЬ: Управление группами ===
        right_panel = self.create_right_panel()
        layout.addWidget(right_panel, stretch=1)
        
        self.setLayout(layout)

    def create_left_panel(self):
        """Левая панель - дерево групп."""
        group = QGroupBox("Дерево групп")
        layout = QVBoxLayout()
        
        # Дерево групп
        self.groups_tree = QTreeWidget()
        self.groups_tree.setHeaderLabel("Группы")
        self.groups_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.groups_tree.customContextMenuRequested.connect(self.show_context_menu)
        self.groups_tree.itemClicked.connect(self.on_item_clicked)
        
        # Начальная структура
        self.create_default_groups()
        
        layout.addWidget(self.groups_tree)
        
        # Кнопки под деревом
        btn_layout = QHBoxLayout()
        
        btn_create = QPushButton("Создать группу")
        btn_create.clicked.connect(self.create_group)
        btn_layout.addWidget(btn_create)
        
        btn_delete = QPushButton("Удалить")
        btn_delete.clicked.connect(self.delete_group)
        btn_layout.addWidget(btn_delete)
        
        layout.addLayout(btn_layout)
        
        group.setLayout(layout)
        return group

    def create_right_panel(self):
        """Правая панель - управление группами."""
        group = QGroupBox("Управление группами")
        layout = QVBoxLayout()
        
        # Выбор группы
        lbl_group = QLabel("Группа:")
        layout.addWidget(lbl_group)
        
        self.cmb_group = QComboBox()
        self.cmb_group.addItems(["Все", "косметические", "черновые", "окрасочные"])
        self.cmb_group.currentTextChanged.connect(self.on_group_selected)
        layout.addWidget(self.cmb_group)
        
        # Кнопки действий
        btn_create = QPushButton("Создать группу")
        btn_create.clicked.connect(self.create_group)
        layout.addWidget(btn_create)
        
        btn_rename = QPushButton("Переименовать")
        btn_rename.clicked.connect(self.rename_group)
        layout.addWidget(btn_rename)
        
        btn_delete = QPushButton("Удалить")
        btn_delete.clicked.connect(self.delete_group)
        layout.addWidget(btn_delete)
        
        layout.addSpacing(20)
        
        # Экспорт/Импорт
        btn_export = QPushButton("Экспорт структуры")
        btn_export.clicked.connect(self.export_structure)
        layout.addWidget(btn_export)
        
        btn_import = QPushButton("Импорт структуры")
        btn_import.clicked.connect(self.import_structure)
        layout.addWidget(btn_import)
        
        layout.addStretch()
        
        group.setLayout(layout)
        return group

    def create_default_groups(self):
        """Создание дефолтных групп."""
        root = QTreeWidgetItem(self.groups_tree, ["Все (0)"])
        root.setData(0, Qt.UserRole, "all")
        root.setExpanded(True)
        
        cosmetics = QTreeWidgetItem(root, ["косметические (0)"])
        cosmetics.setData(0, Qt.UserRole, "cosmetics")
        
        drafts = QTreeWidgetItem(root, ["черновые (0)"])
        drafts.setData(0, Qt.UserRole, "drafts")
        
        painting = QTreeWidgetItem(root, ["окрасочные (0)"])
        painting.setData(0, Qt.UserRole, "painting")

    def show_context_menu(self, position):
        """Контекстное меню для дерева групп."""
        item = self.groups_tree.itemAt(position)
        
        menu = QMenu(self)
        
        if item:
            # Действия для существующей группы
            act_rename = menu.addAction("✏️ Переименовать")
            act_delete = menu.addAction("🗑️ Удалить группу")
            menu.addSeparator()
            act_create_subgroup = menu.addAction("📁 Создать подгруппу")
        else:
            # Действия для пустого пространства
            act_create_group = menu.addAction("📁 Создать группу")
        
        action = menu.exec_(self.groups_tree.mapToGlobal(position))
        
        if action == act_create_subgroup if item else act_create_group:
            self.create_group(item)
        elif item and action == act_delete:
            self.delete_group(item)
        elif item and action == act_rename:
            self.rename_group(item)

    def create_group(self, parent_item=None):
        """Создание новой группы."""
        name, ok = QInputDialog.getText(self, "Новая группа", "Название группы:")
        if ok and name:
            new_item = QTreeWidgetItem([f"{name} (0)"])
            new_item.setData(0, Qt.UserRole, name.lower().replace(" ", "_"))
            
            if parent_item:
                parent_item.addChild(new_item)
                parent_item.setExpanded(True)
            else:
                self.groups_tree.addTopLevelItem(new_item)
            
            # Эмит сигнала для добавления в БД (если нужно)
            parent_id = parent_item.data(0, Qt.UserRole) if parent_item else None
            self.groupSelected.emit(name)
            
            # Обновляем счётчики
            self.update_counters()

    def delete_group(self, item=None):
        """Удаление группы."""
        if not item:
            item = self.groups_tree.currentItem()
        
        if not item:
            return
        
        group_name = item.text(0).split(" (")[0]
        reply = QMessageBox.question(
            self, "Удаление группы",
            f"Удалить группу '{group_name}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            parent = item.parent()
            if parent:
                parent.removeChild(item)
            else:
                index = self.groups_tree.indexOfTopLevelItem(item)
                self.groups_tree.takeTopLevelItem(index)
            
            # Обновляем счётчики
            self.update_counters()

    def rename_group(self, item=None):
        """Переименование группы."""
        if not item:
            item = self.groups_tree.currentItem()
        
        if not item:
            return
        
        current_name = item.text(0).split(" (")[0]
        new_name, ok = QInputDialog.getText(
            self, "Переименовать группу",
            "Новое название:",
            text=current_name
        )
        
        if ok and new_name:
            count = item.text(0).split("(")[1].rstrip(")")
            item.setText(0, f"{new_name} ({count})")
            item.setData(0, Qt.UserRole, new_name.lower().replace(" ", "_"))

    def on_item_clicked(self, item, column):
        """Обработка клика по группе."""
        group_id = item.data(0, Qt.UserRole)
        self.groupSelected.emit(group_id)
        self.cmb_group.setCurrentText(item.text(0).split(" (")[0])

    def on_group_selected(self, group_name):
        """Обработка выбора группы в комбобоксе."""
        # Найти элемент в дереве и выделить его
        for i in range(self.groups_tree.topLevelItemCount()):
            item = self.groups_tree.topLevelItem(i)
            if item.text(0).split(" (")[0] == group_name:
                self.groups_tree.setCurrentItem(item)
                return
            
            # Рекурсивный поиск в дочерних элементах
            if self.find_child_item(item, group_name):
                return

    def find_child_item(self, parent, group_name):
        """Рекурсивный поиск дочернего элемента."""
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.text(0).split(" (")[0] == group_name:
                self.groups_tree.setCurrentItem(child)
                return True
            
            if self.find_child_item(child, group_name):
                return True
        return False

    def update_counters(self):
        """Обновление счётчиков фраз в группах."""
        # TODO: Подсчет фраз из БД
        # Пока просто обновляем отображение
        pass

    def export_structure(self):
        """Экспорт структуры групп в JSON."""
        structure = self.get_structure()
        
        # Диалог выбора файла
        from PySide6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getSaveFileName(
            self, "Экспорт структуры групп",
            "",
            "JSON files (*.json);;All files (*.*)"
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(structure, f, ensure_ascii=False, indent=2)
                QMessageBox.information(self, "Готово", f"Структура экспортирована в {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать: {str(e)}")

    def import_structure(self):
        """Импорт структуры групп из JSON."""
        from PySide6.QtWidgets import QFileDialog
        filename, _ = QFileDialog.getOpenFileName(
            self, "Импорт структуры групп",
            "",
            "JSON files (*.json);;All files (*.*)"
        )
        
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    structure = json.load(f)
                
                # TODO: Применить структуру к дереву
                QMessageBox.information(self, "Готово", f"Структура импортирована из {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось импортировать: {str(e)}")

    def get_structure(self):
        """Получение структуры групп в виде словаря."""
        structure = {}
        
        def process_item(item, parent_key=""):
            item_text = item.text(0)
            name = item_text.split(" (")[0]
            count = item_text.split("(")[1].rstrip(")") if "(" in item_text else "0"
            
            key = parent_key + "/" + name if parent_key else name
            structure[key] = {
                "name": name,
                "count": int(count),
                "children": []
            }
            
            for i in range(item.childCount()):
                child = item.child(i)
                structure[key]["children"].append(process_item(child, key))
            
            return structure
        
        for i in range(self.groups_tree.topLevelItemCount()):
            item = self.groups_tree.topLevelItem(i)
            structure.update(process_item(item))
        
        return structure