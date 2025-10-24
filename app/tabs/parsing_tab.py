# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QSplitter,
    QPushButton,
    QTextEdit,
    QLabel,
    QSpinBox,
    QCheckBox,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
    QProgressBar,
    QFileDialog,
)

from ..widgets.geo_tree import GeoTree
from ..keys_panel import KeysPanel
try:
    from ...services.accounts import list_profiles, get_profile_ctx, get_account_by_email
    from ...services.wordstat_bridge import collect_frequency, collect_depth, collect_forecast
except ImportError:
    from services.accounts import list_profiles, get_profile_ctx, get_account_by_email
    from services.wordstat_bridge import collect_frequency, collect_depth, collect_forecast

# Импорт turbo_parser_10tabs
TURBO_PARSER_PATH = Path("C:/AI/yandex")
if TURBO_PARSER_PATH.exists() and str(TURBO_PARSER_PATH) not in sys.path:
    sys.path.insert(0, str(TURBO_PARSER_PATH))

try:
    from turbo_parser_10tabs import turbo_parser_10tabs
    TURBO_PARSER_AVAILABLE = True
except ImportError as e:
    print(f"[WARNING] turbo_parser_10tabs not available: {e}")
    turbo_parser_10tabs = None
    TURBO_PARSER_AVAILABLE = False


class ParsingWorker(QThread):
    """Фоновый запуск частотки / вглубь в отдельном потоке."""

    tick = Signal(dict)
    finished = Signal(list)

    def __init__(
        self,
        mode: str,
        phrases: list[str],
        modes: dict,
        depth_cfg: dict,
        geo_ids: list[int],
        profile: Optional[str],
        profile_ctx: Optional[dict],
        parent: QWidget | None,
    ):
        super().__init__(parent)
        self._mode = mode
        self.phrases = phrases
        self.modes = modes
        self.depth_cfg = depth_cfg
        self.geo_ids = geo_ids or [225]
        self.profile = profile
        self.profile_ctx = profile_ctx or {}
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:  # type: ignore[override]
        rows = []
        try:
            if self._mode == "freq":
                # Попробовать использовать turbo_parser_10tabs
                if TURBO_PARSER_AVAILABLE and self.profile:
                    try:
                        rows = self._run_turbo_parser()
                    except Exception as turbo_error:
                        print(f"[ERROR] Turbo parser failed: {turbo_error}")
                        # Fallback к старому методу
                        rows = collect_frequency(
                            self.phrases,
                            modes=self.modes,
                            regions=self.geo_ids,
                            profile=self.profile,
                        )
                else:
                    # Использовать старый метод
                    rows = collect_frequency(
                        self.phrases,
                        modes=self.modes,
                        regions=self.geo_ids,
                        profile=self.profile,
                    )
            elif self._mode in {"depth-left", "depth-right"}:
                rows = collect_depth(
                    self.phrases,
                    column="left" if self._mode.endswith("left") else "right",
                    pages=self.depth_cfg.get("pages", 1),
                    regions=self.geo_ids,
                    profile=self.profile,
                )
            elif self._mode == "forecast":
                rows = collect_forecast(
                    self.phrases,
                    regions=self.geo_ids,
                    profile_ctx=self.profile_ctx,
                )
            else:
                rows = []
        except Exception as e:
            print(f"[ERROR] Parsing failed: {e}")
            import traceback
            traceback.print_exc()
            # Не генерируем Mock данные, возвращаем ошибку
            rows = [
                {
                    "phrase": phrase,
                    "ws": "",
                    "qws": "",
                    "bws": "",
                    "status": f"Error: {str(e)}",
                }
                for phrase in self.phrases
            ]

        self.tick.emit(
            {
                "type": self._mode,
                "phrase": "",
                "current": len(self.phrases),
                "total": len(self.phrases),
                "progress": 100,
            }
        )
        self.finished.emit(rows)

    def _run_turbo_parser(self) -> list[dict]:
        """Запустить turbo_parser_10tabs и преобразовать результаты."""
        # Получить данные аккаунта
        account_data = get_account_by_email(self.profile)
        if not account_data:
            raise ValueError(f"Account {self.profile} not found")

        profile_path = Path(account_data["profile_path"])
        proxy_uri = account_data.get("proxy")

        print(f"[TURBO] Starting turbo parser for {self.profile}")
        print(f"[TURBO] Profile: {profile_path}")
        print(f"[TURBO] Proxy: {proxy_uri or 'None'}")
        print(f"[TURBO] Phrases: {len(self.phrases)}")

        # Запустить async функцию
        results = asyncio.run(
            turbo_parser_10tabs(
                account_name=self.profile,
                profile_path=profile_path,
                phrases=self.phrases,
                headless=False,
                proxy_uri=proxy_uri,
            )
        )

        # Преобразовать результаты из Dict[str, int] в формат таблицы
        rows = []
        for phrase in self.phrases:
            freq = results.get(phrase, 0)
            rows.append(
                {
                    "phrase": phrase,
                    "ws": freq if freq > 0 else "",
                    "qws": "",  # turbo_parser возвращает только базовую частотность
                    "bws": "",  # turbo_parser возвращает только базовую частотность
                    "status": "OK" if freq > 0 else "No data",
                }
            )

        print(f"[TURBO] Completed: {len(results)} results")
        return rows


class ParsingTab(QWidget):
    """Упрощённая вкладка «Парсинг»: частотность + подготовка данных."""

    def __init__(self, parent: QWidget | None = None, keys_panel: KeysPanel | None = None) -> None:
        super().__init__(parent)
        self._worker: Optional[ParsingWorker] = None
        self._keys_panel = keys_panel
        self._current_profile: Optional[str] = None
        self._profile_context: Optional[dict] = None

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        # Левая панель: режимы, глубина, регионы, профиль
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        modes_box = QGroupBox("Режимы частотности (Wordstat)")
        self.chk_ws = QCheckBox("WS (базовая)")
        self.chk_ws.setChecked(True)
        self.chk_qws = QCheckBox('"WS" (в кавычках)')
        self.chk_bws = QCheckBox("!WS (точная)")
        modes_layout = QVBoxLayout(modes_box)
        modes_layout.addWidget(self.chk_ws)
        modes_layout.addWidget(self.chk_qws)
        modes_layout.addWidget(self.chk_bws)

        depth_box = QGroupBox("Парсинг вглубь")
        self.chk_depth = QCheckBox("Включить")
        self.spn_pages = QSpinBox()
        self.spn_pages.setRange(1, 40)
        self.spn_pages.setValue(10)
        self.chk_left = QCheckBox("Левая колонка")
        self.chk_right = QCheckBox("Правая колонка")
        depth_layout = QHBoxLayout(depth_box)
        depth_layout.addWidget(self.chk_depth)
        depth_layout.addWidget(QLabel("Страниц:"))
        depth_layout.addWidget(self.spn_pages)
        depth_layout.addWidget(self.chk_left)
        depth_layout.addWidget(self.chk_right)

        geo_box = QGroupBox("Регионы (дерево)")
        self.geo_tree = GeoTree()
        geo_layout = QVBoxLayout(geo_box)
        geo_layout.addWidget(self.geo_tree)

        profile_box = QGroupBox("Аккаунт / профиль")
        self.cmb_profile = QComboBox()
        self.cmb_profile.addItems(["Текущий", "Все по очереди"])
        profile_layout = QVBoxLayout(profile_box)
        profile_layout.addWidget(self.cmb_profile)

        left_layout.addWidget(modes_box)
        left_layout.addWidget(depth_box)
        left_layout.addWidget(geo_box, 1)
        left_layout.addWidget(profile_box)

        # Центр: ввод фраз + таблица результатов
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)

        self.phrases_edit = QTextEdit()
        self.phrases_edit.setPlaceholderText("Введите ключевые фразы (по одной на строку)…")
        self.phrases_edit.setMaximumHeight(150)

        controls = QHBoxLayout()
        self.btn_run = QPushButton("▶ Запустить парсинг")
        self.btn_stop = QPushButton("■ Остановить")
        self.btn_stop.setEnabled(False)
        self.btn_export = QPushButton("💾 Экспорт в CSV")
        controls.addWidget(self.btn_run)
        controls.addWidget(self.btn_stop)
        controls.addWidget(self.btn_export)
        controls.addStretch()

        self.progress = QProgressBar()
        self.progress.setVisible(False)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Фраза", "WS", '"WS"', "!WS", "Статус", "Время", "Действия"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)

        center_layout.addWidget(QLabel("Ключевые фразы для парсинга:"))
        center_layout.addWidget(self.phrases_edit)
        center_layout.addLayout(controls)
        center_layout.addWidget(self.progress)
        center_layout.addWidget(QLabel("Результаты:"))
        center_layout.addWidget(self.table, 1)

        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self._wire_signals()
        self.refresh_profiles()

    # ------------------------------------------------------------------ API
    def set_keys_panel(self, panel: KeysPanel) -> None:
        self._keys_panel = panel

    def append_phrases(self, phrases: list[str]) -> None:
        existing = self.phrases_edit.toPlainText().splitlines()
        merged = existing + [phrase for phrase in phrases if phrase.strip()]
        self.phrases_edit.setPlainText("\n".join(sorted(set(phrase.strip() for phrase in merged if phrase.strip()))))

    def refresh_profiles(self) -> None:
        profiles = list_profiles()
        previous = self._current_profile
        self.cmb_profile.blockSignals(True)
        self.cmb_profile.clear()
        if profiles:
            self.cmb_profile.addItems(profiles)
            if previous and previous in profiles:
                index = profiles.index(previous)
            else:
                index = 0
            self.cmb_profile.setCurrentIndex(index)
            self._current_profile = profiles[index]
        else:
            self.cmb_profile.addItem("Текущий")
            self._current_profile = None
        self.cmb_profile.blockSignals(False)
        self._update_profile_context()

    # ------------------------------------------------------------------ slots
    def _wire_signals(self) -> None:
        self.btn_run.clicked.connect(self._on_run_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        self.btn_export.clicked.connect(self._on_export_clicked)
        self.cmb_profile.currentTextChanged.connect(self._on_profile_changed)

    def _on_profile_changed(self, value: str) -> None:
        self._current_profile = value or None
        self._update_profile_context()

    def _update_profile_context(self) -> None:
        context = get_profile_ctx(self._current_profile) if self._current_profile else get_profile_ctx(None)
        self._profile_context = context or {"storage_state": None, "proxy": None}

    def _on_run_clicked(self) -> None:
        phrases = [line.strip() for line in self.phrases_edit.toPlainText().splitlines() if line.strip()]
        if not phrases:
            return

        modes = {
            "ws": self.chk_ws.isChecked(),
            "qws": self.chk_qws.isChecked(),
            "bws": self.chk_bws.isChecked(),
        }
        depth_cfg = {
            "enabled": self.chk_depth.isChecked(),
            "pages": self.spn_pages.value(),
            "left": self.chk_left.isChecked(),
            "right": self.chk_right.isChecked(),
        }
        geo_ids = self.geo_tree.selected_geo_ids()

        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.table.setRowCount(0)

        mode = "freq"
        self._worker = ParsingWorker(
            mode,
            phrases,
            modes,
            depth_cfg,
            geo_ids,
            self._current_profile,
            self._profile_context,
            self,
        )
        self._worker.tick.connect(self._on_worker_tick)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_stop_clicked(self) -> None:
        if self._worker:
            self._worker.stop()
            self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)

    def _on_worker_tick(self, data: dict) -> None:
        self.progress.setValue(data.get("progress", 0))

    def _on_worker_finished(self, rows: list[dict]) -> None:
        self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)

        self.table.setRowCount(0)
        for record in rows:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            values = [
                record.get("phrase", ""),
                record.get("ws", ""),
                record.get("qws", ""),
                record.get("bws", ""),
                record.get("status", ""),
                time.strftime("%H:%M:%S"),
                "⋯",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row_idx, col, QTableWidgetItem(str(value)))

        if self._keys_panel:
            groups = defaultdict(list)
            for record in rows:
                phrase = record.get("phrase", "")
                group_name = phrase.split()[0] if phrase else "Прочее"
                groups[group_name].append(
                    {
                        "phrase": phrase,
                        "freq_total": record.get("ws", 0),
                        "freq_quotes": record.get("qws", 0),
                        "freq_exact": record.get("bws", 0),
                    }
                )
            self._keys_panel.load_groups(groups)

    def _on_export_clicked(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, "Экспорт в CSV", "keyset_export.csv", "CSV files (*.csv)")
        if not filename:
            return

        rows = []
        for r in range(self.table.rowCount()):
            row = []
            for c in range(self.table.columnCount() - 1):
                item = self.table.item(r, c)
                row.append(item.text() if item else "")
            rows.append(row)

        import csv

        with open(filename, "w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle, delimiter=";")
            writer.writerow(["Фраза", "WS", '"WS"', "!WS", "Статус", "Время"])
            writer.writerows(rows)


__all__ = ["ParsingTab"]
