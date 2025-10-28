# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Iterable, List, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QGroupBox,
)

from ..widgets.geo_tree import GeoTree


class RegionSelectDialog(QDialog):
    """Compact region selector based on GeoTree."""

    def __init__(self, initial_region_ids: Sequence[int] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select region")
        self.setMinimumSize(420, 360)

        layout = QVBoxLayout(self)

        self._geo_tree = GeoTree(parent=self)
        layout.addWidget(self._geo_tree)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._apply_initial_selection(initial_region_ids or [225])

    def _apply_initial_selection(self, region_ids: Iterable[int]) -> None:
        ids = set(region_ids or [])
        if not ids:
            return

        tree = self._geo_tree.tree

        def visit(item):
            node_id = item.data(0, Qt.UserRole)
            if node_id in ids:
                item.setCheckState(0, Qt.Checked)
            for idx in range(item.childCount()):
                visit(item.child(idx))

        for index in range(tree.topLevelItemCount()):
            visit(tree.topLevelItem(index))

    def _collect_selection(self) -> tuple[list[int], list[str]]:
        tree = self._geo_tree.tree
        selected_ids: list[int] = []
        selected_labels: list[str] = []

        def visit(item):
            if item.checkState(0) == Qt.Checked:
                node_id = item.data(0, Qt.UserRole)
                if node_id:
                    selected_ids.append(int(node_id))
                    selected_labels.append(item.text(0))
            for idx in range(item.childCount()):
                visit(item.child(idx))

        for index in range(tree.topLevelItemCount()):
            visit(tree.topLevelItem(index))

        return selected_ids, selected_labels

    def _on_accept(self) -> None:
        ids, _ = self._collect_selection()
        if not ids:
            QMessageBox.warning(self, "Select region", "Choose at least one region.")
            return
        self.accept()

    def get_selection(self) -> tuple[list[int], list[str]]:
        """Return selected region ids and their labels."""
        ids, labels = self._collect_selection()
        if not ids:
            ids = [225]
            labels = ["Russia (225)"]
        return ids, labels


class WordstatSettingsDialog(QDialog):
    """⚙️ Настройки сбора частотности (по спецификации Claude UI Task)"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("⚙️ Настройки сбора частотности")
        self.setMinimumSize(480, 520)

        self._selected_region_ids: list[int] = [225]
        self._selected_region_labels: list[str] = ["Россия (225)"]

        layout = QVBoxLayout(self)
        
        # Попытаться автоматически загрузить профили из БД, если вызывающая сторона их не передаст
        self._autoload_profiles: list[dict] | None = None

        # Заголовок согласно Claude UI Task
        lbl_title = QLabel("🎯 Целью запуска сбора статистики является заполнение колонок:")
        layout.addWidget(lbl_title)
        
        layout.addSpacing(10)

        # ТИПЫ ЧАСТОТНОСТИ (В СТРОКУ!) - согласно спецификации
        freq_group = QGroupBox("Искать:")
        freq_layout = QHBoxLayout()
        
        self.cb_ws = QCheckBox("слово")
        self.cb_ws.setChecked(True)  # ПО УМОЛЧАНИЮ!
        
        self.cb_qws = QCheckBox('"слово"')
        self.cb_bws = QCheckBox("!слово")
        
        freq_layout.addWidget(self.cb_ws)
        freq_layout.addWidget(self.cb_qws)
        freq_layout.addWidget(self.cb_bws)
        freq_layout.addStretch()
        
        freq_group.setLayout(freq_layout)
        layout.addWidget(freq_group)
        
        layout.addSpacing(10)

        # РЕГИОН - согласно спецификации  
        region_layout = QHBoxLayout()
        lbl_region = QLabel("📍 Регион:")
        
        self.region_field = QLineEdit()
        self.region_field.setPlaceholderText("Выбранный регион...")
        self.region_field.setReadOnly(True)
        self._update_region_field()
        
        btn_region = QPushButton("[Выбрать...]")
        btn_region.clicked.connect(self._on_select_region)
        
        region_layout.addWidget(lbl_region)
        region_layout.addWidget(self.region_field, 1)
        region_layout.addWidget(btn_region)
        layout.addLayout(region_layout)
        
        layout.addSpacing(15)

        # ПРОФИЛИ (АВТОМАТ ИЗ БД!) - согласно спецификации
        profiles_group = QGroupBox("👤 Профили для парсинга:")
        profiles_layout = QVBoxLayout()
        
        self.profiles_list = QListWidget()
        self.profiles_list.setSelectionMode(QAbstractItemView.NoSelection)
        profiles_layout.addWidget(self.profiles_list)
        
        # Кнопки управления профилями
        profiles_buttons = QHBoxLayout()
        btn_select_all_prof = QPushButton("[✓ Выбрать все]")
        btn_deselect_all_prof = QPushButton("[✗ Снять выбор]")
        
        btn_select_all_prof.clicked.connect(self._select_all_profiles)
        btn_deselect_all_prof.clicked.connect(self._deselect_all_profiles)
        
        profiles_buttons.addWidget(btn_select_all_prof)
        profiles_buttons.addWidget(btn_deselect_all_prof)
        profiles_buttons.addStretch()
        
        profiles_layout.addLayout(profiles_buttons)
        profiles_group.setLayout(profiles_layout)
        layout.addWidget(profiles_group)

        # Кнопки OK и Отмена (как в спецификации Claude UI Task)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ----------------------------------------------------------------- helpers
    def _select_all_profiles(self):
        """Выбрать все профили"""
        for i in range(self.profiles_list.count()):
            self.profiles_list.item(i).setCheckState(Qt.Checked)
    
    def _deselect_all_profiles(self):
        """Снять выбор со всех профилей"""
        for i in range(self.profiles_list.count()):
            self.profiles_list.item(i).setCheckState(Qt.Unchecked)

    def _on_select_region(self) -> None:
        dialog = RegionSelectDialog(self._selected_region_ids, parent=self)
        if dialog.exec():
            ids, labels = dialog.get_selection()
            self._selected_region_ids = ids
            self._selected_region_labels = labels
            self._update_region_field()

    def _update_region_field(self) -> None:
        if self._selected_region_labels:
            self.region_field.setText(", ".join(self._selected_region_labels))
        else:
            self.region_field.setText("Россия (225)")

    def _on_accept(self) -> None:
        # Если профили не были переданы извне, пробуем автозагрузить их из БД
        if self.profiles_list.count() == 0:
            try:
                from ..services.accounts import list_accounts
            except Exception:
                try:
                    from services.accounts import list_accounts  # fallback на корень
                except Exception:
                    list_accounts = None
            if list_accounts is not None:
                profiles = []
                try:
                    for acc in list_accounts():
                        raw_path = getattr(acc, "profile_path", "") or ""
                        if not raw_path:
                            continue
                        profiles.append({
                            "email": acc.name,
                            "profile_path": raw_path,
                            "proxy": getattr(acc, "proxy", None),
                        })
                except Exception:
                    profiles = []
                if profiles:
                    self.set_profiles(profiles)
        
        # Проверяем, что выбран хотя бы один режим частотности
        if not any(cb.isChecked() for cb in (self.cb_ws, self.cb_qws, self.cb_bws)):
            QMessageBox.warning(self, "Режимы частотности", "Выберите хотя бы один режим частотности.")
            return
        
        # Проверяем, что выбран хотя бы один профиль
        if not any(self.profiles_list.item(i).checkState() == Qt.Checked for i in range(self.profiles_list.count())):
            QMessageBox.warning(self, "Профили", "Выберите хотя бы один профиль для продолжения.")
            return
        
        self.accept()

    # ---------------------------------------------------------------- public API
    def set_profiles(self, profiles: Iterable[dict]) -> None:
        """Populate list of profiles and select all by default."""
        self.profiles_list.clear()
        for profile in profiles:
            email = profile.get("email") or profile.get("name") or str(profile)
            item = QListWidgetItem(email)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, profile)
            self.profiles_list.addItem(item)

    def set_initial_settings(self, settings: dict | None) -> None:
        """Установить начальные настройки диалога"""
        if not settings:
            return

        # Восстанавливаем регионы
        self._selected_region_ids = list(settings.get("regions") or [225])
        self._selected_region_labels = list(settings.get("region_names") or ["Россия (225)"])
        self._update_region_field()

        # Восстанавливаем режимы частотности
        self.cb_ws.setChecked(bool(settings.get("ws", True)))
        self.cb_qws.setChecked(bool(settings.get("qws", False)))
        self.cb_bws.setChecked(bool(settings.get("bws", False)))

        # Восстанавливаем выбранные профили
        selected_profiles = settings.get("profiles") or []
        selected_emails = {
            prof.get("email") if isinstance(prof, dict) else prof
            for prof in selected_profiles
        }
        if not selected_emails:
            selected_emails = set(settings.get("profile_emails") or [])

        # Применяем выбор к профилям в списке
        for index in range(self.profiles_list.count()):
            item = self.profiles_list.item(index)
            profile = item.data(Qt.UserRole)
            email = profile.get("email") if isinstance(profile, dict) else profile
            # Если нет сохранённых настроек - выбираем все профили по умолчанию
            should_check = email in selected_emails if selected_emails else True
            item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)

    def get_settings(self) -> dict:
        """Получить настройки парсинга (согласно Claude UI Task спецификации)"""
        # Собираем выбранные профили
        chosen_profiles: List[dict] = []
        for index in range(self.profiles_list.count()):
            item = self.profiles_list.item(index)
            if item.checkState() == Qt.Checked:
                profile_data = item.data(Qt.UserRole)
                if isinstance(profile_data, dict):
                    chosen_profiles.append(profile_data)

        # Типы частотности
        modes = {
            'ws': self.cb_ws.isChecked(),
            'qws': self.cb_qws.isChecked(),
            'bws': self.cb_bws.isChecked()
        }
        
        # Регион
        region_id = self._selected_region_ids[0] if self._selected_region_ids else 225

        return {
            'modes': modes,
            'region': region_id,
            'profiles': chosen_profiles,
            # Для совместимости с существующим кодом
            "collect_wordstat": True,
            "regions": list(self._selected_region_ids) or [225],
            "region_names": list(self._selected_region_labels) or ["Россия (225)"],
            "ws": self.cb_ws.isChecked(),
            "qws": self.cb_qws.isChecked(), 
            "bws": self.cb_bws.isChecked(),
            "profile_emails": [prof["email"] for prof in chosen_profiles],
        }
