# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple, Iterable, Sequence

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication, QTextCursor
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QPushButton,
    QToolButton,
    QTextEdit,
    QLabel,
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QProgressBar,
    QFileDialog,
    QAbstractItemView,
    QMessageBox,
    QMenu,
    QDialog,
)

from threading import Event

from ..dialogs.wordstat_settings_dialog import WordstatSettingsDialog
from ..dialogs.wordstat_dropdown_widget import WordstatDropdownWidget
from ..keys_panel import KeysPanel
from ..widgets.activity_log import ActivityLogWidget
from ...core.icons import icon

try:
    from ...services.accounts import list_accounts
except ImportError:
    from services.accounts import list_accounts

try:
    from ...services import multiparser_manager
except ImportError:  # pragma: no cover - fallback for scripts
    try:
        import multiparser_manager  # type: ignore
    except ImportError:
        multiparser_manager = None

# Импорт turbo_parser_10tabs
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

BASE_DIR = PROJECT_ROOT
SESSION_FILE = BASE_DIR / "keyset/logs/parsing_session.json"


def _probe_profile_cookies(profile_record: Dict[str, Any]) -> Tuple[int, Optional[str]]:
    """
    Quickly read cookies from the Chrome profile on disk to report how many are available.

    Returns:
        (cookie_count, error_message)
    """
    path_value = profile_record.get("profile_path")
    if not path_value:
        return -1, "Путь профиля не указан"

    try:
        path_obj = Path(path_value)
    except TypeError:
        return -1, f"Неверный тип пути профиля: {path_value!r}"

    if multiparser_manager is None:
        return -1, "multiparser_manager не доступен"
        
    log_obj = getattr(multiparser_manager, "logger", None)
    if log_obj is None:
        return -1, "Логгер multiparser_manager не доступен"

    try:
        if hasattr(multiparser_manager, '_extract_profile_cookies'):
            cookies = multiparser_manager._extract_profile_cookies(  # type: ignore[attr-defined]
                path_obj,
                log_obj,
            )
        else:
            return -1, "Метод _extract_profile_cookies не найден"
    except Exception as exc:  # pragma: no cover - диагностический путь
        return -1, str(exc)

    if cookies is None:
        return -1, "Не удалось извлечь куки"

    return len(cookies), None

try:
    from turbo_parser_improved import turbo_parser_10tabs  # type: ignore
    TURBO_PARSER_AVAILABLE = True
except ImportError as improved_error:  # pragma: no cover - optional dependency
    try:
        from turbo_parser_10tabs import turbo_parser_10tabs  # type: ignore
        TURBO_PARSER_AVAILABLE = True
    except ImportError as e:
        print(f"[WARNING] turbo_parser_10tabs not available: {e}")
        turbo_parser_10tabs = None
        TURBO_PARSER_AVAILABLE = False


class SingleParsingTask:
    """Одна задача парсинга для конкретного профиля"""
    
    def __init__(
        self,
        profile_email: str,
        profile_path: str,
        proxy: str,
        phrases: List[str],
        session_id: str,
        region_plan: Sequence[Tuple[int, str]],
        modes: Sequence[str],
        cookie_count: Optional[int] = None,
    ):
        self.profile_email = profile_email
        self.profile_path = Path(profile_path)
        self.proxy = proxy
        self.phrases = list(phrases)
        self.session_id = session_id
        normalized_plan: List[Tuple[int, str]] = []
        for rid, label in region_plan:
            try:
                region_id = int(rid)
            except (TypeError, ValueError):
                continue
            normalized_plan.append((region_id, str(label)))
        if not normalized_plan:
            normalized_plan = [(225, "Россия (225)")]
        self.region_plan = normalized_plan
        self.modes = tuple(str(mode) for mode in modes if str(mode))
        self.cookie_count = cookie_count
        self.results: List[Dict[str, Any]] = []
        self.status = "waiting"
        self.progress = 0
        self.logs = []
        
    def log(self, message: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_line = f"[{timestamp}] [{level}] [{self.profile_email}] {message}"
        self.logs.append(log_line)
        return log_line
        
    async def run(self):
        """Запуск парсинга для этого профиля"""
        self.status = "running"
        self.results = []
        total_phrases = len(self.phrases)
        self.log(f"Запуск парсинга для {total_phrases} фраз", "INFO")
        
        try:
            # Проверка профиля
            if not self.profile_path.exists():
                self.log(f"❌ Профиль не найден: {self.profile_path}", "ERROR")
                self.status = "error"
                return
                
            self.log(f"✓ Профиль: {self.profile_path}", "INFO")
            self.log(f"✓ Прокси: {self.proxy or 'НЕТ'}", "INFO")
            if self.cookie_count is not None:
                self.log(f"✓ Куки (предварительно): {self.cookie_count} шт", "INFO")

            active_modes = set(self.modes) if self.modes else {"ws"}
            unsupported_modes = sorted(active_modes - {"ws"})
            if unsupported_modes:
                modes_str = ", ".join(unsupported_modes)
                self.log(
                    f"⚠️ Режимы {modes_str} пока не поддерживаются турбо-парсером и будут пропущены.",
                    "WARNING",
                )

            processed_regions = 0
            ws_enabled = "ws" in active_modes
            for region_id, region_name in self.region_plan:
                self.log(f"🌍 Регион: {region_name} ({region_id})", "INFO")
                region_records: List[Dict[str, Any]] = []
                if ws_enabled and total_phrases:
                    try:
                        ws_results = await turbo_parser_10tabs(
                            account_name=self.profile_email,
                            profile_path=self.profile_path,
                            phrases=self.phrases,
                            headless=False,
                            proxy_uri=self.proxy,
                            region_id=region_id,
                        )
                    except Exception as exc:  # pragma: no cover - диагностический путь
                        self.log(f"❌ Ошибка парсинга региона {region_id}: {exc}", "ERROR")
                        continue

                    status_map: Dict[str, str] = {}
                    if hasattr(ws_results, "meta"):
                        status_map = ws_results.meta.get("statuses") or {}

                    for phrase, freq in ws_results.items():
                        raw_status = status_map.get(phrase, "OK")
                        status_key = str(raw_status).strip().upper().replace(" ", "_")
                        status_code = "OK" if status_key == "OK" else "NO_DATA"
                        status_display = "No data" if status_code == "NO_DATA" else "OK"
                        try:
                            freq_value = int(freq)
                        except (TypeError, ValueError):
                            freq_value = 0
                        region_records.append(
                            {
                                "phrase": phrase,
                                "ws": freq_value,
                                "qws": 0,
                                "bws": 0,
                                "status": status_display,
                                "profile": self.profile_email,
                                "region_id": region_id,
                                "region_name": region_name,
                            }
                        )
                else:
                    self.log("⚠️ Режим WS отключён — парсинг пропущен.", "WARNING")

                self.results.extend(region_records)
                processed_regions += 1
                if processed_regions:
                    completion = int((processed_regions / len(self.region_plan)) * 100)
                    self.progress = min(100, completion)

            self.log(
                f"✓ Парсинг завершён. Получено записей: {len(self.results)}",
                "SUCCESS",
            )
            self.status = "completed"
            self.progress = 100
            
        except Exception as e:
            self.log(f"❌ Ошибка: {str(e)}", "ERROR")
            self.status = "error"
            self.progress = 0


class MultiParsingWorker(QThread):
    """Многопоточный воркер для запуска парсинга на всех профилях одновременно"""
    
    # Сигналы
    log_signal = Signal(str)  # Общий лог
    profile_log_signal = Signal(str, str)  # Лог конкретного профиля (email, message)
    progress_signal = Signal(dict)  # Прогресс всех профилей
    task_completed = Signal(str, list)  # Профиль завершил работу (email, results)
    all_finished = Signal(list)  # Все задачи завершены
    
    def __init__(
        self,
        phrases: List[str],
        modes: Sequence[str],
        regions_map: Dict[int, str] | None,
        geo_ids: List[int],
        selected_profiles: List[dict],  # Список выбранных профилей
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.phrases = list(phrases)
        normalized_modes = []
        for mode in modes:
            mode_name = str(mode).strip()
            if mode_name and mode_name not in normalized_modes:
                normalized_modes.append(mode_name)
        if not normalized_modes:
            normalized_modes = ["ws"]
        self.modes = normalized_modes
        region_items: List[Tuple[int, str]] = []
        if regions_map:
            for rid, label in regions_map.items():
                try:
                    region_id = int(rid)
                except (TypeError, ValueError):
                    continue
                region_items.append((region_id, str(label)))
        if not region_items:
            fallback_ids = geo_ids or [225]
            for rid in fallback_ids:
                try:
                    region_id = int(rid)
                except (TypeError, ValueError):
                    continue
                region_items.append((region_id, f"{region_id}"))
        if not region_items:
            region_items = [(225, "Россия (225)")]

        self.region_plan = region_items
        self.geo_ids = [rid for rid, _ in self.region_plan]
        self.selected_profiles = selected_profiles
        self._stop_requested = False
        self._paused = False
        self._pause_event = Event()
        self._pause_event.set()
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Распределяем фразы поровну между профилями
        num_profiles = len(selected_profiles)
        if num_profiles == 0:
            raise ValueError("Нет выбранных профилей для запуска парсинга")

        phrases_per_profile = len(self.phrases) // num_profiles
        remainder = len(self.phrases) % num_profiles

        batches = []
        start_idx = 0

        for i in range(num_profiles):
            # Добавляем по одной фразе к последним профилям если есть остаток
            end_idx = start_idx + phrases_per_profile + (1 if i >= num_profiles - remainder else 0)
            batch = self.phrases[start_idx:end_idx]
            batches.append(batch)
            start_idx = end_idx

        # Создаем задачи для каждого профиля с распределёнными фразами
        self.tasks = []
        for profile, batch in zip(selected_profiles, batches):
            task = SingleParsingTask(
                profile_email=profile['email'],
                profile_path=profile['profile_path'],
                proxy=profile.get('proxy'),
                phrases=batch,  # ✅ Каждый профиль получает ТОЛЬКО свой батч фраз
                session_id=self.session_id,
                region_plan=self.region_plan,
                modes=self.modes,
                cookie_count=profile.get("cookie_count"),
            )
            self.tasks.append(task)
            
        # Логирование
        self.log_file = Path("C:/AI/yandex/keyset/logs/multiparser_journal.log")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def stop(self):
        self._stop_requested = True
        self._pause_event.set()
        self._paused = False
        self._write_log("⛔ Запрошена остановка парсинга")

    def pause(self):
        if self._stop_requested or self._paused:
            return
        self._paused = True
        self._pause_event.clear()
        self._write_log("⏸ Парсинг поставлен на паузу")

    def resume(self):
        if not self._paused:
            return
        self._paused = False
        self._pause_event.set()
        self._write_log("▶️ Парсинг продолжен")

    @property
    def is_paused(self) -> bool:
        return self._paused

    def _write_log(self, message: str):
        """Записать в файл и отправить в GUI"""
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception as e:
            print(f"Log write error: {e}")
        
        # Отправляем в GUI
        self.log_signal.emit(message)
    
    def run(self):
        """Основной метод запуска всех парсеров"""
        self._write_log("=" * 70)
        self._write_log(f"🚀 ЗАПУСК МНОГОПОТОЧНОГО ПАРСИНГА")
        self._write_log(f"📊 Профилей: {len(self.selected_profiles)}")
        self._write_log(f"📝 Фраз: {len(self.phrases)}")
        self._write_log(f"🌍 Регионов: {len(self.region_plan)}")
        self._write_log(f"⚙️ Режимы: {', '.join(self.modes)}")
        self._write_log("=" * 70)
        
        # Создаем новый event loop для этого потока
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Запускаем все задачи параллельно
            loop.run_until_complete(self._run_all_parsers())
        finally:
            loop.close()
            
        # Собираем все результаты
        all_results: List[Dict[str, Any]] = []
        for task in self.tasks:
            if task.results:
                all_results.extend(task.results)
                    
        self._write_log("=" * 70)
        self._write_log(f"✅ ВСЕ ЗАДАЧИ ЗАВЕРШЕНЫ")
        self._write_log(f"📊 Всего результатов: {len(all_results)}")
        self._write_log("=" * 70)
        
        self.all_finished.emit(all_results)
    
    async def _run_all_parsers(self):
        """Запуск всех парсеров асинхронно"""
        tasks_coro = []
        
        for task in self.tasks:
            if self._stop_requested:
                break

            await self._wait_if_paused()

            # Создаем корутину для каждого профиля
            tasks_coro.append(self._run_single_parser(task))
            
        # Запускаем все корутины параллельно
        results = await asyncio.gather(*tasks_coro, return_exceptions=True)
        
        # Обрабатываем результаты
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._write_log(f"❌ Ошибка в профиле {self.tasks[i].profile_email}: {str(result)}")

    async def _wait_if_paused(self):
        if self._pause_event.is_set():
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._pause_event.wait)

    async def _run_single_parser(self, task: SingleParsingTask):
        """Запуск одного парсера"""
        self._write_log(f"▶️ Запуск парсера для {task.profile_email}")
        
        # Подписываемся на логи задачи
        def log_callback(msg, level):
            full_msg = task.log(msg, level)
            self._write_log(full_msg)
            self.profile_log_signal.emit(task.profile_email, full_msg)
        
        # Запускаем парсинг
        await self._wait_if_paused()
        if self._stop_requested:
            self._write_log(f"⛔ Остановка {task.profile_email} до запуска")
            return {}

        await task.run()
        
        # Отправляем логи задачи
        for log_line in task.logs:
            self._write_log(log_line)
            self.profile_log_signal.emit(task.profile_email, log_line)
        
        # Уведомляем о завершении
        self.task_completed.emit(task.profile_email, task.results)
        
        return task.results


class ParsingTab(QWidget):
    """Улучшенная вкладка парсинга с поддержкой многопоточности"""
    
    def __init__(self, parent: QWidget | None = None, keys_panel: KeysPanel | None = None, activity_log: ActivityLogWidget | None = None):
        super().__init__(parent)
        self._worker = None
        self._keys_panel = keys_panel
        self.activity_log = activity_log
        self._last_settings = self._normalize_wordstat_settings(None)
        self._active_profiles: List[dict] = []
        self._active_phrases: List[str] = []
        self._active_regions: Dict[int, str] = {225: "Россия (225)"}
        self._region_order: List[int] = []
        self._region_labels: Dict[int, str] = {}
        self._manual_phrases_cache: str = ""
        self._manual_ignore_duplicates: bool = False
        
        # Выпадающий виджет для кнопки "Частотка"
        self._wordstat_dropdown = None
        
        self._init_ui()
        self._wire_signals()
        self._restore_session_state()

    def _normalize_wordstat_settings(self, settings: Dict[str, Any] | None) -> Dict[str, Any]:
        """Привести любые настройки частотки к единообразному виду."""
        allowed_modes = ("ws", "qws", "bws")
        modes_list: List[str] = []
        region_map: Dict[int, str] = {}

        if settings:
            raw_modes = settings.get("modes")
            if isinstance(raw_modes, dict):
                modes_list = [name for name, value in raw_modes.items() if value and name in allowed_modes]
            elif isinstance(raw_modes, (list, tuple, set)):
                modes_list = [str(name) for name in raw_modes if str(name) in allowed_modes]

            if not modes_list:
                for name in allowed_modes:
                    if settings.get(name, False):
                        modes_list.append(name)

            if isinstance(settings.get("regions_map"), dict) and settings["regions_map"]:
                region_map = {int(k): str(v) for k, v in settings["regions_map"].items()}
            elif isinstance(settings.get("region_map"), dict) and settings["region_map"]:
                region_map = {int(k): str(v) for k, v in settings["region_map"].items()}
            else:
                region_ids: List[int] = []
                if isinstance(settings.get("regions"), Iterable):
                    try:
                        region_ids = [int(rid) for rid in settings["regions"]]
                    except (TypeError, ValueError):
                        region_ids = []
                elif settings.get("region"):
                    try:
                        region_ids = [int(settings["region"])]
                    except (TypeError, ValueError):
                        region_ids = []

                if region_ids:
                    labels = list(settings.get("region_names") or [])
                    if labels and len(labels) == len(region_ids):
                        region_map = {rid: str(label) for rid, label in zip(region_ids, labels)}
                    else:
                        region_map = {rid: str(rid) for rid in region_ids}
        else:
            modes_list = ["ws"]

        if not modes_list:
            modes_list = ["ws"]

        if not region_map:
            region_map = {225: "Россия (225)"}

        bool_modes = {name: (name in modes_list) for name in allowed_modes}

        normalized = {
            "collect_wordstat": bool(settings.get("collect_wordstat", True)) if settings else True,
            "modes": modes_list,
            "regions_map": region_map,
            "regions": list(region_map.keys()),
            "region_names": list(region_map.values()),
            "ws": bool_modes["ws"],
            "qws": bool_modes["qws"],
            "bws": bool_modes["bws"],
            "profiles": list(settings.get("profiles") or []) if settings else [],
            "profile_emails": list(settings.get("profile_emails") or []) if settings else [],
        }
        return normalized

    def _status_column_index(self) -> int:
        return 3 + len(self._region_order)

    @staticmethod
    def _short_region_label(label: str, region_id: int) -> str:
        parts = [part.strip() for part in str(label).split("/") if part.strip()]
        if len(parts) >= 3:
            parts = parts[-3:]
        elif not parts:
            parts = [str(region_id)]
        short = " / ".join(parts)
        return f"{short} ({region_id})"

    def _ensure_item(self, row: int, column: int) -> QTableWidgetItem:
        item = self.table.item(row, column)
        if item is None:
            item = QTableWidgetItem("")
            self.table.setItem(row, column, item)
        return item

    def _set_cell_text(self, row: int, column: int, text: Any) -> None:
        item = self._ensure_item(row, column)
        item.setText("" if text is None else str(text))

    def _set_frequency_cell(
        self,
        row: int,
        column: int,
        value: Any,
        *,
        region_id: int | None = None,
        status: str | None = None,
    ) -> None:
        freq = self._coerce_freq(value)
        item = self._ensure_item(row, column)
        item.setText(str(freq))
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        meta = item.data(Qt.UserRole)
        if not isinstance(meta, dict):
            meta = {}
        if region_id is not None:
            meta["region_id"] = region_id
        if status:
            meta["status"] = status
        meta["value"] = freq
        item.setData(Qt.UserRole, meta)

    def _set_status_cell(self, row: int, text: str, *, status_meta: dict | None = None) -> None:
        column = self._status_column_index()
        item = self._ensure_item(row, column)
        item.setText(text)
        item.setTextAlignment(Qt.AlignCenter)
        if status_meta is not None:
            item.setData(Qt.UserRole, status_meta)

    def _configure_table_columns(self, region_map: Dict[int, str] | None) -> None:
        if not hasattr(self, "table"):
            return

        effective_map = region_map or self._active_regions or {225: "Россия (225)"}
        ordered_items: List[Tuple[int, str]] = []
        seen: set[int] = set()
        for key, label in effective_map.items():
            try:
                region_id = int(key)
            except (TypeError, ValueError):
                continue
            if region_id in seen:
                continue
            ordered_items.append((region_id, str(label)))
            seen.add(region_id)
        if not ordered_items:
            ordered_items = [(225, "Россия (225)")]

        self._region_order = [rid for rid, _ in ordered_items]
        self._region_labels = {rid: label for rid, label in ordered_items}

        status_col = self._status_column_index()
        self.table.setColumnCount(status_col + 1)

        headers = ["✓", "№", "Фраза"]
        headers.extend(self._short_region_label(label, rid) for rid, label in ordered_items)
        headers.append("Статус")
        self.table.setHorizontalHeaderLabels(headers)

        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(1, 48)
        self.table.setColumnWidth(2, 420)
        for idx in range(len(self._region_order)):
            self.table.setColumnWidth(3 + idx, 160)
        self.table.setColumnWidth(status_col, 100)

        for row in range(self.table.rowCount()):
            self._ensure_checkbox(row)
            self._ensure_item(row, 1)
            self._ensure_item(row, 2)
            for idx in range(len(self._region_order)):
                self._ensure_item(row, 3 + idx)
            self._ensure_item(row, status_col)

    def _init_ui(self) -> None:
        """Инициализация UI по архитектуре Key Collector"""
        main_layout = QVBoxLayout(self)

        # ═══════════════════════════════════════════════════════════
        # 1️⃣ TOP PANEL - функции вверху
        # ═══════════════════════════════════════════════════════════
        top_panel = QWidget()
        top_layout = QHBoxLayout(top_panel)

        # Кнопки основных функций
        self.btn_add = QToolButton()
        self.btn_add.setText("➕ Добавить")
        self.btn_add.setPopupMode(QToolButton.InstantPopup)
        self.btn_add.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._add_menu = QMenu(self.btn_add)
        self._action_add_phrases = self._add_menu.addAction("Добавить фразы…")
        self._action_add_from_file = self._add_menu.addAction("Загрузить из файла…")
        self._action_add_from_clipboard = self._add_menu.addAction("Импорт из буфера…")
        self._add_menu.addSeparator()
        self._action_clear_phrases = self._add_menu.addAction("Очистить таблицу")
        self.btn_add.setMenu(self._add_menu)
        self.btn_delete = QPushButton("❌ Удалить")
        self.btn_ws = QPushButton(" Частотка")
        self.btn_batch = QPushButton(" Пакет")
        self.btn_forecast = QPushButton(" Прогноз")
        self.btn_clear = QPushButton("🗑️ Очистить")
        self.btn_export = QPushButton("💾 Экспорт")

        top_layout.addWidget(self.btn_add)
        top_layout.addWidget(self.btn_delete)
        top_layout.addWidget(QLabel("  |  "))
        top_layout.addWidget(self.btn_ws)
        top_layout.addWidget(self.btn_batch)
        top_layout.addWidget(self.btn_forecast)
        top_layout.addWidget(QLabel("  |  "))
        top_layout.addWidget(self.btn_clear)
        top_layout.addWidget(self.btn_export)
        top_layout.addStretch()

        # Статус
        self.status_label = QLabel("🟢 Готово")
        self.status_label.setStyleSheet("QLabel { font-weight: bold; padding: 5px; }")
        top_layout.addWidget(self.status_label)

        main_layout.addWidget(top_panel)

        # ═══════════════════════════════════════════════════════════
        # 2️⃣ ГЛАВНАЯ ОБЛАСТЬ - 3 колонки
        # ═══════════════════════════════════════════════════════════
        splitter_main = QSplitter(Qt.Horizontal)

        # ───────────────────────────────────────────────────────────
        # ЛЕВАЯ КОЛОНКА (5-10%) - Управление выбором строк
        # ───────────────────────────────────────────────────────────
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # Кнопки управления выбором
        self.btn_select_all_rows = QPushButton("✓ Выбрать все")
        self.btn_deselect_all_rows = QPushButton("✗ Снять выбор")
        self.btn_invert_selection = QPushButton("🔄 Инвертировать")

        left_layout.addWidget(self.btn_select_all_rows)
        left_layout.addWidget(self.btn_deselect_all_rows)
        left_layout.addWidget(self.btn_invert_selection)
        left_layout.addSpacing(10)

        hint = QLabel("Отмечайте строки чекбоксами,\nчтобы запускать действия по выбранным фразам.")
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        left_layout.addStretch()

        # ───────────────────────────────────────────────────────────
        # ЦЕНТРАЛЬНАЯ КОЛОНКА (80%) - Основная таблица
        # ───────────────────────────────────────────────────────────
        center_panel = QWidget()
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)

        # Кнопки управления парсингом
        control_buttons = QHBoxLayout()
        self.btn_run = QPushButton("🚀 Запустить парсинг")
        self.btn_run.setStyleSheet("QPushButton { font-weight: bold; padding: 8px; }")
        self.btn_stop = QPushButton("⏹ Стоп")
        self.btn_stop.setEnabled(False)
        self.btn_pause = QPushButton("⏸ Пауза")
        self.btn_pause.setEnabled(False)

        control_buttons.addWidget(self.btn_run)
        control_buttons.addWidget(self.btn_pause)
        control_buttons.addWidget(self.btn_stop)
        control_buttons.addStretch()

        # Прогресс
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        control_buttons.addWidget(self.progress)

        center_layout.addLayout(control_buttons)

        # ОСНОВНАЯ ТАБЛИЦА с результатами
        self.table = QTableWidget()
        self._configure_table_columns(self._active_regions)

        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        center_layout.addWidget(self.table)

        # Добавляем колонки в splitter (2 колонки: левая + центральная)
        splitter_main.addWidget(left_panel)
        splitter_main.addWidget(center_panel)

        # Пропорции: Левая панель не растягивается, Центр растягивается
        splitter_main.setStretchFactor(0, 0)
        splitter_main.setStretchFactor(1, 1)
        splitter_main.setSizes([100, 900])

        main_layout.addWidget(splitter_main)
        
    def _wire_signals(self):
        """Подключение сигналов"""
        # TOP PANEL кнопки
        self._action_add_phrases.triggered.connect(self._show_add_phrases_dialog)
        self._action_add_from_file.triggered.connect(self._on_add_from_file)
        self._action_add_from_clipboard.triggered.connect(self._on_add_from_clipboard)
        self._action_clear_phrases.triggered.connect(self._on_clear_results)
        self.btn_delete.clicked.connect(self._on_delete_phrases)
        self.btn_ws.clicked.connect(self._on_wordstat_dropdown)  # Частотка = выпадающее меню настроек частотности
        self.btn_batch.clicked.connect(self._on_batch_parsing)
        self.btn_forecast.clicked.connect(self._on_forecast)
        self.btn_clear.clicked.connect(self._on_clear_results)
        self.btn_export.clicked.connect(self._on_export_clicked)
        
        # Устанавливаем иконки для кнопок
        self.btn_ws.setIcon(icon("frequency"))
        self.btn_batch.setIcon(icon("batch"))
        self.btn_forecast.setIcon(icon("forecast"))

        # Кнопки управления парсингом
        self.btn_run.clicked.connect(self._on_wordstat_dropdown)
        self.btn_stop.clicked.connect(self._on_stop_parsing)
        self.btn_pause.clicked.connect(self._on_pause_parsing)

        # Левая панель - управление выбором строк
        self.btn_select_all_rows.clicked.connect(self._select_all_rows)
        self.btn_deselect_all_rows.clicked.connect(self._deselect_all_rows)
        self.btn_invert_selection.clicked.connect(self._invert_selection)

        # Журнал — дополнительных сигналов не требуется (кнопки внутри виджета)

    def _get_selected_profiles(self) -> List[dict]:
        """Получить все профили из БД (вкладка Аккаунты)"""
        selected = []
        try:
            accounts = list_accounts()
            self._append_log(f"🔍 Загружено аккаунтов из БД: {len(accounts)}")

            skipped = 0
            for account in accounts:
                # Пропускаем служебные аккаунты
                if account.name in ["demo_account", "wordstat_main"]:
                    self._append_log(f"   ⏭ Пропущен служебный аккаунт: {account.name}")
                    skipped += 1
                    continue

                raw_profile_path = getattr(account, "profile_path", "") or ""
                if not raw_profile_path:
                    self._append_log(f"   ⚠️ Пропущен {account.name}: нет profile_path")
                    skipped += 1
                    continue

                profile_path = Path(raw_profile_path)
                if not profile_path.is_absolute():
                    profile_path = (BASE_DIR / profile_path).resolve()
                else:
                    profile_path = profile_path.resolve()

                proxy_value = getattr(account, "proxy", None)

                profile_data = {
                    'email': account.name,
                    'proxy': proxy_value.strip() if isinstance(proxy_value, str) else proxy_value,
                    'profile_path': str(profile_path),
                }

                # Логируем каждый выбранный профиль
                self._append_log(f"   ✓ {account.name} → {str(profile_path)}")
                selected.append(profile_data)

            self._append_log(f"✅ Выбрано профилей для парсинга: {len(selected)}")
            if skipped > 0:
                self._append_log(f"⏭ Пропущено аккаунтов: {skipped}")

        except Exception as e:
            error_msg = f"❌ Ошибка загрузки профилей: {str(e)}"
            self._append_log(error_msg)
            import traceback
            self._append_log(traceback.format_exc())

        return selected

    def _insert_phrase_row(self, phrase: str, ws: str = "", status: str = "—", checked: bool = True) -> None:
        self._configure_table_columns(self._active_regions)
        row_idx = self.table.rowCount()
        self.table.insertRow(row_idx)
        checkbox = QCheckBox()
        checkbox.setChecked(checked)
        self.table.setCellWidget(row_idx, 0, checkbox)
        self._set_cell_text(row_idx, 1, row_idx + 1)
        self._set_cell_text(row_idx, 2, phrase)
        for idx in range(len(self._region_order)):
            self._set_cell_text(row_idx, 3 + idx, ws if idx == 0 else "")
        self._set_cell_text(row_idx, self._status_column_index(), status)

    def _renumber_rows(self) -> None:
        for row in range(self.table.rowCount()):
            self._set_cell_text(row, 1, row + 1)

    def _get_checkbox(self, row: int) -> QCheckBox | None:
        widget = self.table.cellWidget(row, 0)
        return widget if isinstance(widget, QCheckBox) else None

    def _ensure_checkbox(self, row: int, checked: bool | None = None) -> None:
        checkbox = self._get_checkbox(row)
        if checkbox is None:
            checkbox = QCheckBox()
            self.table.setCellWidget(row, 0, checkbox)
        if checked is not None:
            checkbox.setChecked(checked)

    def _get_all_phrases(self) -> List[str]:
        phrases: List[str] = []
        for row in range(self.table.rowCount()):
            phrase_item = self.table.item(row, 2)
            if phrase_item:
                phrase = phrase_item.text().strip()
                if phrase:
                    phrases.append(phrase)
        return phrases

    def _get_selected_phrases(self) -> List[str]:
        selected: List[str] = []
        for row in range(self.table.rowCount()):
            checkbox = self._get_checkbox(row)
            if not checkbox or not checkbox.isChecked():
                continue
            phrase_item = self.table.item(row, 2)
            if phrase_item:
                phrase = phrase_item.text().strip()
                if phrase:
                    selected.append(phrase)
        return selected

    def _mark_phrases_pending(self, phrases: List[str]) -> None:
        pending = set(phrases)
        for row in range(self.table.rowCount()):
            phrase_item = self.table.item(row, 2)
            if not phrase_item:
                continue
            if phrase_item.text().strip() in pending:
                for idx in range(len(self._region_order)):
                    self._set_cell_text(row, 3 + idx, "")
                self._set_cell_text(row, self._status_column_index(), "⏳")

    def save_session_state(self, partial_results: List[Dict[str, Any]] | None = None) -> None:
        """Сохранить состояние парсинга, чтобы восстановить его при следующем запуске."""
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - best effort
            print(f"[ERROR] Failed to prepare session directory: {exc}")
            return

        phrases = self._get_all_phrases()
        state: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "phrases": phrases,
            "settings": self._last_settings,
            "manual_buffer": self._manual_phrases_cache,
        }
        if partial_results is not None:
            state["partial_results"] = partial_results

        try:
            with SESSION_FILE.open("w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[ERROR] Failed to save session: {exc}")

    def load_session_state(self) -> Dict[str, Any] | None:
        """Загрузить сохранённое состояние парсинга, если оно доступно."""
        if not SESSION_FILE.exists():
            return None
        try:
            with SESSION_FILE.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception as exc:
            print(f"[ERROR] Failed to load session: {exc}")
            return None

    def _restore_session_state(self) -> None:
        """Восстановить состояние парсинга после перезапуска приложения."""
        state = self.load_session_state()
        if not state:
            return

        phrases = state.get("phrases") or []
        if phrases:
            self.table.setRowCount(0)
            for phrase in phrases:
                self._insert_phrase_row(phrase, checked=False)
            self._renumber_rows()
            self._manual_phrases_cache = "\n".join(phrases)
        else:
            self._manual_phrases_cache = ""

        buffer_text = state.get("manual_buffer")
        if isinstance(buffer_text, str):
            self._manual_phrases_cache = buffer_text

        partial_results = state.get("partial_results") or []
        if isinstance(partial_results, list):
            self._populate_results(partial_results)

        settings = state.get("settings")
        if isinstance(settings, dict):
            self._last_settings = self._normalize_wordstat_settings(settings)

    @staticmethod
    def _coerce_freq(value: Any) -> int:
        if value is None:
            return 0
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            stripped = value.strip().replace(" ", "")
            if not stripped:
                return 0
            try:
                return int(float(stripped))
            except ValueError:
                return 0
        return 0

    def _aggregate_by_phrase(self, rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
        aggregated: Dict[str, Dict[str, int]] = {}
        for record in rows:
            phrase = str(record.get("phrase", "")).strip()
            if not phrase:
                continue
            entry = aggregated.setdefault(phrase, {"ws": 0, "qws": 0, "bws": 0})
            entry["ws"] = max(entry["ws"], self._coerce_freq(record.get("ws")))
            entry["qws"] = max(entry["qws"], self._coerce_freq(record.get("qws")))
            entry["bws"] = max(entry["bws"], self._coerce_freq(record.get("bws")))
        return aggregated

    def _populate_results(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Обновить результаты в таблице (заполнить частотность и статус)."""
        normalized_rows: List[Dict[str, Any]] = []
        combined_regions = dict(self._active_regions)
        phrase_region_values: Dict[str, Dict[int, int]] = {}
        phrase_statuses: Dict[str, Dict[int, str]] = {}

        for record in rows:
            phrase = str(record.get("phrase", "")).strip()
            if not phrase:
                continue
            region_id_raw = record.get("region_id")
            try:
                region_id = int(region_id_raw) if region_id_raw is not None else 225
            except (TypeError, ValueError):
                region_id = 225
            region_name = str(
                record.get("region_name")
                or combined_regions.get(region_id)
                or record.get("region_label")
                or region_id
            )
            combined_regions.setdefault(region_id, region_name)
            freq_value = self._coerce_freq(record.get("ws"))
            status_raw = str(record.get("status", "OK") or "OK").strip().upper().replace(" ", "_")
            if status_raw in {"FAILED", "ERROR"}:
                status_raw = "NO_DATA"
            if status_raw != "NO_DATA" and status_raw != "OK":
                status_raw = "NO_DATA"

            phrase_region_values.setdefault(phrase, {})[region_id] = freq_value
            phrase_statuses.setdefault(phrase, {})[region_id] = status_raw

        self._configure_table_columns(combined_regions)
        self._active_regions = dict(combined_regions)

        for row in range(self.table.rowCount()):
            self._ensure_checkbox(row)
            phrase_item = self.table.item(row, 2)
            if not phrase_item:
                continue
            phrase = phrase_item.text()
            region_values = phrase_region_values.get(phrase, {})
            region_status_map = phrase_statuses.get(phrase, {})

            if not region_values and not region_status_map:
                self._set_status_cell(row, "⏱")
                continue

            has_alert = False
            status_meta: Dict[int, str] = {}
            for idx, region_id in enumerate(self._region_order):
                status = region_status_map.get(region_id)
                if status is None:
                    status = "NO_DATA" if phrase in phrase_region_values else "OK"
                status = str(status).strip().upper().replace(" ", "_")
                if status in {"FAILED", "ERROR"}:
                    status = "NO_DATA"
                freq_value = region_values.get(region_id, 0)
                if status == "NO_DATA":
                    has_alert = True
                self._set_frequency_cell(row, 3 + idx, freq_value, region_id=region_id, status=status)
                status_meta[region_id] = status

            status_text = "⚠️" if has_alert else "✓"
            self._set_status_cell(row, status_text, status_meta=status_meta)

        for phrase, regions in phrase_region_values.items():
            status_map = phrase_statuses.get(phrase) or {}
            region_ids = set(regions.keys()) | set(status_map.keys())
            for region_id in region_ids:
                freq_value = self._coerce_freq(regions.get(region_id, 0))
                status_value = str(status_map.get(region_id, "OK")).strip().upper().replace(" ", "_")
                if status_value in {"FAILED", "ERROR"}:
                    status_value = "NO_DATA"
                status_display = "No data" if status_value == "NO_DATA" else "OK"
                normalized_rows.append(
                    {
                        "phrase": phrase,
                        "region_id": region_id,
                        "region_name": self._region_labels.get(region_id, str(region_id)),
                        "ws": freq_value,
                        "status": status_display,
                    }
                )

        self._append_log(f"📊 Обновлено результатов: {len(normalized_rows)}")

        if self._keys_panel:
            groups = defaultdict(list)
            aggregated = self._aggregate_by_phrase(normalized_rows)
            for phrase, metrics in aggregated.items():
                group_name = phrase.split()[0] if phrase else "Прочее"
                groups[group_name].append(
                    {
                        "phrase": phrase,
                        "freq_total": metrics["ws"],
                        "freq_quotes": metrics["qws"],
                        "freq_exact": metrics["bws"],
                    }
                )
            self._keys_panel.load_groups(groups)

        return normalized_rows

    # ═══════════════════════════════════════════════════════════
    # Функции управления выбором строк (левая панель)
    # ═══════════════════════════════════════════════════════════

    def _select_all_rows(self):
        """Выбрать все строки в таблице"""
        for row in range(self.table.rowCount()):
            self._ensure_checkbox(row, True)
        self._append_log(f"✓ Отмечено фраз: {self.table.rowCount()}")

    def _deselect_all_rows(self):
        """Снять выбор со всех строк"""
        for row in range(self.table.rowCount()):
            self._ensure_checkbox(row, False)
        self._append_log("✗ Все отметки сняты")

    def _invert_selection(self):
        """Инвертировать выбор строк"""
        for row in range(self.table.rowCount()):
            checkbox = self._get_checkbox(row)
            if checkbox:
                checkbox.setChecked(not checkbox.isChecked())
        selected = len(self._get_selected_phrases())
        self._append_log(f"🔄 Отметки инвертированы ({selected} строк)")

    # ═══════════════════════════════════════════════════════════
    # Функции TOP PANEL (основные действия)
    # ═══════════════════════════════════════════════════════════

    def _show_add_phrases_dialog(self):
        """Показать диалог добавления фраз в стиле Key Collector."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Список фраз")
        dialog.setMinimumWidth(520)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint_label = QLabel("Каждую новую фразу начинайте с новой строки.")
        layout.addWidget(hint_label)

        ignore_checkbox = QCheckBox("Не следить за наличием фразы в других группах")
        ignore_checkbox.setChecked(self._manual_ignore_duplicates)
        layout.addWidget(ignore_checkbox)

        edit = QTextEdit(dialog)
        edit.setPlaceholderText("Введите фразы (каждая с новой строки)")
        edit.setFixedHeight(320)
        if self._manual_phrases_cache:
            edit.setPlainText(self._manual_phrases_cache)
        layout.addWidget(edit, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()

        btn_add = QPushButton("Добавить в таблицу", dialog)
        btn_add.setDefault(True)
        btn_load = QPushButton("Загрузить из файла…", dialog)
        btn_clear = QPushButton("Очистить все списки", dialog)
        btn_close = QPushButton("Закрыть", dialog)

        buttons.addWidget(btn_add)
        buttons.addWidget(btn_load)
        buttons.addWidget(btn_clear)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)

        def _apply_add():
            text = edit.toPlainText().strip()
            phrases = self._extract_phrases_from_text(text)
            if not phrases:
                self._append_log("❌ Нет фраз для добавления")
                return
            self._manual_ignore_duplicates = ignore_checkbox.isChecked()
            self._manual_phrases_cache = ""
            added = self._add_phrases_to_table(phrases, source="фраз", checked=True)
            if added:
                dialog.accept()

        def _apply_load():
            file_path, _ = QFileDialog.getOpenFileName(
                dialog,
                "Выберите файл с фразами",
                "",
                "Text files (*.txt);;All files (*)",
            )
            if not file_path:
                return
            path = Path(file_path)
            try:
                phrases = self._read_phrases_from_file(path)
            except IOError as exc:
                QMessageBox.warning(
                    dialog,
                    "Ошибка чтения файла",
                    f"Не удалось прочитать файл:\n{path}\n\n{exc}",
                )
                self._append_log(f"❌ Не удалось прочитать файл с фразами: {exc}")
                return

            if not phrases:
                QMessageBox.information(
                    dialog,
                    "Импорт фраз",
                    "В выбранном файле не найдено фраз.",
                )
                self._append_log("❌ В выбранном файле нет фраз для добавления")
                return

            existing = edit.toPlainText().strip()
            new_text = "\n".join(phrases)
            if existing:
                edit.setPlainText(f"{existing}\n{new_text}")
            else:
                edit.setPlainText(new_text)
            edit.moveCursor(QTextCursor.End)
            self._manual_phrases_cache = edit.toPlainText()
            self._append_log(f"📂 Загружено фраз из файла: {path.name} ({len(phrases)})")

        def _apply_clear():
            edit.clear()
            self._manual_phrases_cache = ""
            self._append_log("🧹 Буфер ввода фраз очищен")

        btn_add.clicked.connect(_apply_add)
        btn_load.clicked.connect(_apply_load)
        btn_clear.clicked.connect(_apply_clear)
        btn_close.clicked.connect(dialog.reject)

        result = dialog.exec()
        if result != QDialog.Accepted:
            self._manual_phrases_cache = edit.toPlainText()
            self._manual_ignore_duplicates = ignore_checkbox.isChecked()

    @staticmethod
    def _extract_phrases_from_text(text: str) -> List[str]:
        normalized: List[str] = []
        if not text:
            return normalized
        prepared = text.replace("\r\n", "\n").replace("\r", "\n")
        for line in prepared.split("\n"):
            phrase = line.strip()
            if phrase:
                normalized.append(phrase)
        return normalized

    def _read_phrases_from_file(self, path: Path) -> List[str]:
        """Прочитать фразы из текстового файла в кодировке UTF-8 или CP1251."""
        try:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_text(encoding="cp1251")
        except Exception as exc:
            raise IOError(str(exc)) from exc
        return self._extract_phrases_from_text(text)

    def _add_phrases_to_table(
        self,
        phrases: Iterable[str],
        *,
        source: str = "фраз",
        checked: bool = True,
    ) -> int:
        normalized: List[str] = []
        for phrase in phrases:
            phrase_text = str(phrase).strip()
            if not phrase_text:
                continue
            normalized.append(phrase_text)

        if not normalized:
            return 0

        for phrase in normalized:
            self._insert_phrase_row(phrase, checked=checked)

        self._renumber_rows()
        source_label = source or "фраз"
        self._append_log(
            f"➕ Добавлено {source_label}: {len(normalized)} (всего: {self.table.rowCount()})"
        )
        return len(normalized)

    def _on_add_from_clipboard(self) -> None:
        """Добавить фразы из буфера обмена."""
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self._append_log("❌ Буфер обмена недоступен")
            return

        text = clipboard.text() or ""
        phrases = self._extract_phrases_from_text(text)
        if not phrases:
            self._append_log("❌ В буфере обмена нет фраз для добавления")
            return

        self._manual_phrases_cache = "\n".join(phrases)
        self._add_phrases_to_table(phrases, source="фраз из буфера", checked=True)

    def _on_add_from_file(self) -> None:
        """Добавить фразы из текстового файла."""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл с фразами",
            "",
            "Text files (*.txt);;All files (*)",
        )
        if not file_path:
            return

        path = Path(file_path)
        try:
            phrases = self._read_phrases_from_file(path)
        except IOError as exc:
            QMessageBox.warning(
                self,
                "Ошибка чтения файла",
                f"Не удалось прочитать файл:\n{path}\n\n{exc}",
            )
            self._append_log(f"❌ Не удалось прочитать файл с фразами: {exc}")
            return

        if not phrases:
            QMessageBox.information(
                self,
                "Импорт фраз",
                "В выбранном файле не найдено фраз.",
            )
            self._append_log("❌ В выбранном файле нет фраз для добавления")
            return

        self._manual_phrases_cache = "\n".join(phrases)
        self._add_phrases_to_table(
            phrases,
            source=f"фраз из файла {path.name}",
            checked=True,
        )

    def _on_delete_phrases(self):
        """Удалить выбранные фразы из таблицы"""
        rows_to_remove = [
            row for row in range(self.table.rowCount())
            if (checkbox := self._get_checkbox(row)) and checkbox.isChecked()
        ]
        if not rows_to_remove:
            rows_to_remove = [idx.row() for idx in self.table.selectionModel().selectedRows()]

        if not rows_to_remove:
            self._append_log("❌ Нет отмеченных строк для удаления")
            return

        unique_rows = sorted(set(rows_to_remove), reverse=True)
        for row in unique_rows:
            self.table.removeRow(row)

        self._renumber_rows()

        self._append_log(f"🗑️ Удалено строк: {len(unique_rows)} (осталось: {self.table.rowCount()})")

    def _on_clear_results(self):
        """Очистить все результаты из таблицы"""
        row_count = self.table.rowCount()
        self.table.setRowCount(0)
        self._append_log(f"🗑️ Таблица очищена ({row_count} строк удалено)")

    def _on_batch_parsing(self):
        """Пакетный парсинг с выбором регионов"""
        from ..dialogs.batch_collect_dialog import BatchCollectDialog

        dialog = BatchCollectDialog(self)
        dialog.collect_requested.connect(self._on_batch_collect_requested)
        dialog.exec()

    def _on_batch_collect_requested(self, phrases: List[str], settings: dict):
        """Обработка запроса пакетного сбора фраз"""
        self._append_log("=" * 70)
        self._append_log("📦 ПАКЕТНЫЙ СБОР ФРАЗ")
        self._append_log(f"📝 Фраз для сбора: {len(phrases)}")

        # Регионы
        geo_ids = settings.get("geo_ids", [225])
        self._append_log(f"🌍 Регионы: {geo_ids}")

        # Порог показов
        threshold = settings.get("threshold", 20)
        self._append_log(f"📊 Порог показов: {threshold}")

        self._append_log("=" * 70)

        # Добавляем фразы в таблицу
        for phrase in phrases:
            self._insert_phrase_row(phrase, status="⏱", checked=True)
        self._renumber_rows()

        self._append_log(f"✅ Фразы добавлены в таблицу: {len(phrases)}")
        self._append_log("💡 Используйте кнопку '🚀 Запустить парсинг' для начала сбора")

    def _on_forecast(self):
        """Прогноз бюджета - заглушка"""
        self._append_log("💰 Прогноз бюджета (в разработке)")

    # ═══════════════════════════════════════════════════════════
    # Парсинг
    # ═══════════════════════════════════════════════════════════

    def _on_wordstat_dropdown(self):
        """Показать выпадающее меню настроек Wordstat под кнопкой 'Частотка'"""
        # 1. Создаём или показываем выпадающий виджет
        if self._wordstat_dropdown is None:
            self._wordstat_dropdown = WordstatDropdownWidget(self)
            
            # Подключаем сигналы
            self._wordstat_dropdown.parsing_requested.connect(self._on_dropdown_parsing_requested)
            self._wordstat_dropdown.closed.connect(self._on_dropdown_closed)
            
            # Устанавливаем профили
            profiles = self._get_selected_profiles()
            if profiles:
                self._wordstat_dropdown.set_profiles(profiles)
            
            # Устанавливаем настройки
            self._wordstat_dropdown.set_initial_settings(self._last_settings)
        
        # 2. Показываем виджет под кнопкой "Частотка"
        self._wordstat_dropdown.show_at_button(self.btn_ws)
        self._append_log("📊 Выпадающее меню настроек частотности открыто")

    def _on_dropdown_parsing_requested(self, settings: dict):
        """Обработка запроса парсинга из выпадающего меню"""
        # Получаем фразы
        phrases = self._get_selected_phrases()
        if not phrases:
            phrases = self._get_all_phrases()
            if phrases:
                self._append_log("ℹ️ Чекбоксы не выбраны — будут использованы все фразы в таблице.")

        if not phrases:
            self._append_log("❌ Нет фраз для парсинга (добавьте фразы через кнопку '➕ Добавить').")
            return

        # Получаем профили автоматически из БД
        selected_profiles = self._get_selected_profiles()
        if not selected_profiles:
            QMessageBox.warning(self, "Ошибка", "Нет активных аккаунтов в БД!\n\nДобавьте аккаунты на вкладке 'Аккаунты'.")
            return

        normalized = self._normalize_wordstat_settings(settings)
        self._last_settings = normalized

        # Логируем параметры запуска
        self._append_log("=" * 70)
        self._append_log("🚀 ЗАПУСК ПАРСИНГА ЧАСТОТНОСТИ (выпадающее меню)")
        self._append_log(f"📝 Фраз: {len(phrases)}")
        self._append_log(f"📊 Профилей: {len(selected_profiles)}")
        region_labels = normalized.get("region_names", ["Россия (225)"])
        self._append_log(f"🌍 Регионы: {', '.join(region_labels)}")
        
        # Логируем активные режимы
        modes_list = normalized.get("modes", [])
        active_modes = []
        if "ws" in modes_list or normalized.get("ws"):
            active_modes.append("слово")
        if "qws" in modes_list or normalized.get("qws"):
            active_modes.append('"слово"')
        if "bws" in modes_list or normalized.get("bws"):
            active_modes.append("!слово")
        self._append_log(f"⚙️ Режимы: {', '.join(active_modes) if active_modes else 'нет'}")
        
        # Логируем профили
        self._append_log("👥 Профили:")
        for i, prof in enumerate(selected_profiles, 1):
            email = prof.get("email", "unknown")
            proxy = prof.get("proxy", "без прокси")
            self._append_log(f"   {i}. {email} → {proxy}")
        
        self._append_log("=" * 70)

        # Запускаем парсинг
        self._run_parsing_with_settings(phrases, selected_profiles, normalized)

    def _on_dropdown_closed(self):
        """Выпадающее меню закрыто"""
        self._append_log("📊 Выпадающее меню настроек частотности закрыто")

    def _on_wordstat_clicked(self):
        """Открыть диалог настроек частотности Wordstat (как в GPTS-WORDSTAT-TASK)"""
        # 1) Всегда открываем диалог (без предварительных ранних возвратов)
        dialog = WordstatSettingsDialog(self)
        # Подставим профили из БД, если есть (диалог также умеет автозагружать при ОК)
        base_profiles = self._get_selected_profiles()
        if base_profiles:
            dialog.set_profiles(base_profiles)
        dialog.set_initial_settings(self._last_settings)

        if not dialog.exec():
            return

        # 2) Получаем настройки из диалога
        settings = dialog.get_settings()

        # 3) Получаем фразы из таблицы (сначала отмеченные, затем все)
        phrases = self._get_selected_phrases() or self._get_all_phrases()
        if not phrases:
            QMessageBox.warning(self, "Ошибка", "Нет фраз для парсинга.\n\nДобавьте фразы через кнопку '➕ Добавить'.")
            return

        # 4) Проверяем выбранные профили
        selected_profiles = settings.get("profiles", [])
        if not selected_profiles:
            QMessageBox.warning(self, "Ошибка", "Не выбраны профили для парсинга.\n\nВыберите хотя бы один профиль в диалоге.")
            return

        # 5) Сохраняем настройки и запускаем
        normalized = self._normalize_wordstat_settings(settings)
        self._last_settings = normalized
        self._run_parsing_with_settings(phrases, selected_profiles, normalized)

    def _run_parsing_with_settings(
        self,
        phrases: List[str],
        selected_profiles: List[dict],
        settings: dict,
    ) -> None:
        """Подготовить окружение и запустить воркер с выбранными настройками."""
        if not TURBO_PARSER_AVAILABLE:
            self._append_log("❌ turbo_parser_10tabs недоступен — запустить парсинг невозможно.")
            return

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._append_log(f"⏰ Время запуска: {timestamp}")
        self._append_log("🔄 Подготовка профилей и кук...")

        for profile_info in selected_profiles:
            cookie_count, cookie_error = _probe_profile_cookies(profile_info)
            proxy_value = profile_info.get("proxy") or "без прокси"
            if cookie_count >= 0:
                profile_info["cookie_count"] = cookie_count
                self._append_log(
                    f"   • {profile_info.get('email', 'unknown')} → прокси {proxy_value}, куки {cookie_count} шт"
                )
            else:
                profile_info["cookie_count"] = None
                self._append_log(
                    f"   • {profile_info.get('email', 'unknown')} → прокси {proxy_value}, куки не прочитаны ({cookie_error})"
                )

        geo_ids = [int(rid) for rid in settings.get("regions") or [225]]
        region_labels = list(settings.get("region_names") or [str(rid) for rid in geo_ids])
        raw_region_map = settings.get("regions_map") if isinstance(settings.get("regions_map"), dict) else {}
        normalized_region_map: Dict[int, str] = {}
        if raw_region_map:
            for key, value in raw_region_map.items():
                try:
                    region_id = int(key)
                except (TypeError, ValueError):
                    continue
                normalized_region_map[region_id] = str(value)
        if not normalized_region_map:
            for index, region_id in enumerate(geo_ids):
                label = region_labels[index] if index < len(region_labels) else str(region_id)
                normalized_region_map[int(region_id)] = str(label)

        modes_list = [str(mode) for mode in settings.get("modes") or []]
        modes_flags = {
            "ws": ("ws" in modes_list) or bool(settings.get("ws")),
            "qws": ("qws" in modes_list) or bool(settings.get("qws")),
            "bws": ("bws" in modes_list) or bool(settings.get("bws")),
        }
        active_mode_keys = [name for name, enabled in modes_flags.items() if enabled]

        self._active_profiles = selected_profiles
        self._active_phrases = phrases
        self._active_regions = dict(normalized_region_map)
        self._configure_table_columns(self._active_regions)

        self._mark_phrases_pending(phrases)
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.btn_pause.setEnabled(True)
        self.btn_pause.setText("⏸ Пауза")
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.status_label.setText("🟠 В работе")

        self._append_log(f"🌍 Регионы для запуска: {list(normalized_region_map.values())}")
        self._append_log("📋 Детали профилей:")
        for idx, profile in enumerate(selected_profiles, 1):
            self._append_log(f"   {idx}. {profile['email']} → {profile['profile_path']}")

        self._append_log("🔧 Создаю MultiParsingWorker...")
        self._worker = MultiParsingWorker(
            phrases=phrases,
            modes=active_mode_keys,
            regions_map=normalized_region_map,
            geo_ids=geo_ids,
            selected_profiles=selected_profiles,
            parent=self
        )
        self._append_log("✓ MultiParsingWorker создан")

        self._append_log("🔌 Подключаю сигналы worker...")
        self._worker.log_signal.connect(self._append_log)
        self._worker.profile_log_signal.connect(self._on_profile_log)
        self._worker.progress_signal.connect(self._on_progress_update)
        self._worker.task_completed.connect(self._on_task_completed)
        self._worker.all_finished.connect(self._on_all_finished)
        self._append_log("✓ Сигналы подключены")

        self.save_session_state()
        self._append_log("▶️ Запускаю worker.start()...")
        self._worker.start()
        self._append_log("✓ Worker запущен! Ожидайте открытия браузеров...")
        
    def _on_stop_parsing(self):
        """Остановка парсинга пользователем."""
        if self._worker:
            self._worker.stop()
            self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Пауза")
        self.progress.setVisible(False)
        self.status_label.setText("🟥 Остановлено")
        self._append_log("⏹ Парсинг остановлен пользователем")

    def _on_pause_parsing(self):
        """Поставить парсинг на паузу или продолжить работу."""
        if not self._worker:
            return
        if self._worker.is_paused:
            self._worker.resume()
            self.btn_pause.setText("⏸ Пауза")
            self.status_label.setText("🟠 В работе")
            self._append_log("▶️ Парсинг возобновлён")
        else:
            self._worker.pause()
            self.btn_pause.setText("▶️ Продолжить")
            self.status_label.setText("⏸ На паузе")
            self._append_log("⏸ Парсинг поставлен на паузу")
        
    def _append_log(self, message: str):
        """Добавить сообщение в журнал активности."""
        if hasattr(self, "activity_log") and self.activity_log is not None:
            self.activity_log.append_line(message)
        
    def _on_profile_log(self, profile_email: str, message: str):
        """Обработка лога от конкретного профиля."""
        prefix = f"[{profile_email}] " if profile_email else ""
        self._append_log(prefix + message)
        
    def _on_progress_update(self, progress_data: dict):
        """Обновление прогресса"""
        # Вычисляем общий прогресс
        if progress_data:
            total_progress = sum(progress_data.values()) / len(progress_data)
            self.progress.setValue(int(total_progress))
            
    def _on_task_completed(self, profile_email: str, results: List[Dict[str, Any]]):
        """Обработка завершения задачи одного профиля"""
        total = len(results) if results else 0
        self._append_log(f"✅ Профиль {profile_email} завершил парсинг. Результатов: {total}")
        
    def _on_all_finished(self, all_results: List[dict]):
        """Все задачи завершены"""
        self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Пауза")
        self.progress.setVisible(False)
        self.status_label.setText("🟢 Готово")

        normalized_rows = self._populate_results(all_results)
        self._renumber_rows()

        self._append_log("=" * 70)
        self._append_log(f"✅ ПАРСИНГ ЗАВЕРШЕН")
        self._append_log(f"📊 Всего результатов: {len(normalized_rows)}")
        self._append_log("=" * 70)

        self.save_session_state(partial_results=normalized_rows)
        
    def _on_export_clicked(self):
        """Экспорт результатов в CSV с 2 колонками: Фраза и Частотность"""
        if self.table.rowCount() == 0:
            self._append_log("❌ Нет результатов для экспорта")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт результатов",
            f"parsing_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            "CSV Files (*.csv);;All Files (*)"
        )

        if file_path:
            try:
                import csv

                # Собираем данные: фраза + WS (колонки 2 и 3)
                export_data = []
                for row in range(self.table.rowCount()):
                    phrase_item = self.table.item(row, 2)  # Колонка "Фраза"
                    ws_item = self.table.item(row, 3)      # Колонка "WS"

                    if phrase_item and ws_item:
                        phrase = phrase_item.text()
                        ws_text = ws_item.text()

                        # Конвертируем частотность в число
                        try:
                            ws_value = int(float(ws_text)) if ws_text else 0
                        except (ValueError, TypeError):
                            ws_value = 0

                        export_data.append({
                            'phrase': phrase,
                            'frequency': ws_value
                        })

                # Сортируем по частотности (по убыванию - самые популярные сверху)
                export_data.sort(key=lambda x: x['frequency'], reverse=True)

                # Записываем в CSV с TAB разделителем для надёжности
                # TAB предпочтительнее запятой, т.к. в фразах могут быть запятые
                with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f, delimiter='\t', quoting=csv.QUOTE_MINIMAL)

                    # Заголовки (только 2 колонки)
                    writer.writerow(['Фраза', 'Частотность'])

                    # Данные
                    for item in export_data:
                        writer.writerow([item['phrase'], item['frequency']])

                self._append_log(f"✅ Результаты экспортированы: {file_path}")
                self._append_log(f"📊 Экспортировано {len(export_data)} записей")

            except Exception as e:
                self._append_log(f"❌ Ошибка экспорта: {str(e)}")
