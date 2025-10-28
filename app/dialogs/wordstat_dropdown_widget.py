# -*- coding: utf-8 -*-
"""
Выпадающий виджет «Частотка» в стиле KeySet.
Блокирует всю логику выбора региона внутри себя (без дополнительных окон)
и повторяет правила отбора из веб-версии (panel.aitibot.ru).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from PySide6.QtCore import Qt, QPoint, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox

from ..widgets.geo_selector import GeoSelector, load_region_model, RegionRow


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
REGIONS_DATASET = DATA_DIR / "regions_tree_full.json"


class WordstatDropdownWidget(QWidget):
    """
    Выпадающее меню настроек Wordstat (под кнопкой «Частотка»).
    Возвращает список выбранных модов и карту регионов {id: path}.
    """

    parsing_requested = Signal(dict)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(420, 360)

        self.setStyleSheet(
            """
            WordstatDropdownWidget {
                background-color: #f8f9fa;
                border: 2px solid #0078d4;
                border-radius: 6px;
            }
            QLabel {
                color: #2d3748;
                font-size: 12px;
            }
            QPushButton {
                background-color: #ffffff;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px 12px;
                color: #374151;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #f3f4f6;
                border-color: #9ca3af;
            }
            QPushButton:pressed {
                background-color: #e5e7eb;
            }
            QPushButton:default {
                background-color: #3b82f6;
                color: white;
                border-color: #3b82f6;
            }
            QPushButton:default:hover {
                background-color: #2563eb;
            }
            QCheckBox {
                color: #374151;
                font-size: 12px;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #d1d5db;
                background-color: white;
                border-radius: 2px;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #3b82f6;
                background-color: #3b82f6;
                border-radius: 2px;
            }
            QLineEdit {
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px 8px;
                background-color: white;
                font-size: 12px;
            }
            QLineEdit:focus {
                border-color: #3b82f6;
            }
            QListWidget {
                border: 1px solid #d1d5db;
                border-radius: 4px;
                background-color: white;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 4px 8px;
                border-bottom: 1px solid #f3f4f6;
            }
            QListWidget::item:hover {
                background-color: #f8f9fa;
            }
            """
        )

        self._region_model = load_region_model(REGIONS_DATASET)
        self._selected_regions: Dict[int, RegionRow] = {}
        self._available_profiles: List[dict] = []

        self._init_ui()
        self._wire_signals()
        self._on_regions_changed(self.geo_selector.export_selection())

    # ------------------------------------------------------------------ UI ----
    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)

        title = QLabel("Настройки частотки Yandex.Wordstat")
        title.setStyleSheet("font-weight: bold; font-size: 12px; padding: 4px;")
        main_layout.addWidget(title)

        # Чекбоксы режимов (в линию)
        modes_row = QHBoxLayout()
        modes_row.addWidget(QLabel("Искать:"))

        self.cb_ws = QCheckBox("слово")
        self.cb_ws.setChecked(True)
        modes_row.addWidget(self.cb_ws)

        self.cb_qws = QCheckBox("\"слово\"")
        modes_row.addWidget(self.cb_qws)

        self.cb_bws = QCheckBox("!слово")
        modes_row.addWidget(self.cb_bws)

        modes_row.addStretch()
        main_layout.addLayout(modes_row)

        main_layout.addSpacing(6)

        # Гео-блок
        main_layout.addWidget(QLabel("📍 Регион охвата:"))
        self.geo_selector = GeoSelector(self._region_model, parent=self)
        main_layout.addWidget(self.geo_selector)

        main_layout.addSpacing(10)

        buttons_layout = QHBoxLayout()
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self._on_cancel)

        btn_start = QPushButton("Получить данные")
        btn_start.setDefault(True)
        btn_start.clicked.connect(self._on_start_parsing)

        buttons_layout.addWidget(btn_cancel)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_start)
        main_layout.addLayout(buttons_layout)

    # --------------------------------------------------------------- signals ---
    def _wire_signals(self) -> None:
        self.geo_selector.selectionChanged.connect(self._on_regions_changed)

    def _on_regions_changed(self, selection: Dict[int, RegionRow]) -> None:
        self._selected_regions = dict(selection)

    # ------------------------------------------------------------- operations ---
    def _collect_modes(self) -> List[str]:
        modes: List[str] = []
        if self.cb_ws.isChecked():
            modes.append("ws")
        if self.cb_qws.isChecked():
            modes.append("qws")
        if self.cb_bws.isChecked():
            modes.append("bws")
        return modes

    def _validate_modes(self) -> bool:
        if any(cb.isChecked() for cb in (self.cb_ws, self.cb_qws, self.cb_bws)):
            return True
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(self, "Выбор частотности", "Отметьте хотя бы один тип запроса (слово, \"слово\" или !слово).")
        return False

    # ------------------------------------------------------------ public API ---
    def set_profiles(self, profiles: Iterable[dict]) -> None:
        self._available_profiles = list(profiles or [])

    def set_initial_settings(self, settings: Dict[str, Any] | None) -> None:
        if not settings:
            self.geo_selector.set_selected_ids([self._region_model.flat[0].id])
            return

        # Моды
        modes_raw = settings.get("modes")
        if isinstance(modes_raw, dict):
            self.cb_ws.setChecked(bool(modes_raw.get("ws")))
            self.cb_qws.setChecked(bool(modes_raw.get("qws")))
            self.cb_bws.setChecked(bool(modes_raw.get("bws")))
        elif isinstance(modes_raw, (list, tuple, set)):
            normalized = {str(item) for item in modes_raw}
            self.cb_ws.setChecked("ws" in normalized or bool(settings.get("ws", False)))
            self.cb_qws.setChecked("qws" in normalized or bool(settings.get("qws", False)))
            self.cb_bws.setChecked("bws" in normalized or bool(settings.get("bws", False)))
        else:
            self.cb_ws.setChecked(bool(settings.get("ws", True)))
            self.cb_qws.setChecked(bool(settings.get("qws", False)))
            self.cb_bws.setChecked(bool(settings.get("bws", False)))

        if not any(cb.isChecked() for cb in (self.cb_ws, self.cb_qws, self.cb_bws)):
            self.cb_ws.setChecked(True)

        # Регионы
        if isinstance(settings.get("regions_map"), dict) and settings["regions_map"]:
            region_ids = [int(rid) for rid in settings["regions_map"].keys()]
        elif isinstance(settings.get("regions"), Iterable):
            region_ids = [int(rid) for rid in settings["regions"]]
        elif settings.get("region"):
            region_ids = [int(settings["region"])]
        else:
            region_ids = [self._region_model.flat[0].id]

        self.geo_selector.set_selected_ids(region_ids)

    def get_settings(self) -> Dict[str, Any]:
        modes = self._collect_modes()
        region_map = {rid: row.path for rid, row in self._selected_regions.items()}
        if not region_map:
            root = self._region_model.flat[0]
            region_map = {root.id: root.path}

        settings = {
            "collect_wordstat": True,
            "modes": modes or ["ws"],
            "regions_map": region_map,
            "regions": list(region_map.keys()),
            "region_names": list(region_map.values()),
            "profiles": [],
            "profile_emails": [],
        }
        # Флаги для обратной совместимости
        settings["ws"] = "ws" in settings["modes"]
        settings["qws"] = "qws" in settings["modes"]
        settings["bws"] = "bws" in settings["modes"]
        return settings

    # -------------------------------------------------------------- callbacks ---
    def _on_start_parsing(self) -> None:
        if not self._validate_modes():
            return
        self.parsing_requested.emit(self.get_settings())
        self.hide()

    def _on_cancel(self) -> None:
        self.hide()
        self.closed.emit()

    # ----------------------------------------------------------------- helpers -
    def show_at_button(self, button: QPushButton) -> None:
        button_global_pos = button.mapToGlobal(QPoint(0, 0))
        popup_x = button_global_pos.x()
        popup_y = button_global_pos.y() + button.height() + 2

        screen = self.screen()
        if screen:
            screen_rect = screen.availableGeometry()
            if popup_x + self.width() > screen_rect.right():
                popup_x = screen_rect.right() - self.width()
            if popup_y + self.height() > screen_rect.bottom():
                popup_y = button_global_pos.y() - self.height() - 2

        self.move(popup_x, popup_y)
        self.show()
        self.raise_()
        self.activateWindow()

    # ---------------------------------------------------------------- overrides
    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._on_cancel()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):  # noqa: N802
        super().focusOutEvent(event)
