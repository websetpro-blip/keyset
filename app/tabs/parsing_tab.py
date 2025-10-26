# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

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
    QCheckBox,
    QTableWidget,
    QTableWidgetItem,
    QProgressBar,
    QFileDialog,
    QAbstractItemView,
)

from ..widgets.geo_tree import GeoTree
from ..keys_panel import KeysPanel

try:
    from ...services.accounts import list_accounts
except ImportError:
    from services.accounts import list_accounts

try:
    from ...services import multiparser_manager
except ImportError:  # pragma: no cover - fallback for scripts
    import multiparser_manager  # type: ignore

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

    log_obj = getattr(multiparser_manager, "logger", None)
    if log_obj is None:
        return -1, "Логгер multiparser_manager не доступен"

    try:
        cookies = multiparser_manager._extract_profile_cookies(  # type: ignore[attr-defined]
            path_obj,
            log_obj,
        )
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
        cookie_count: Optional[int] = None,
    ):
        self.profile_email = profile_email
        self.profile_path = Path(profile_path)
        self.proxy = proxy
        self.phrases = phrases
        self.session_id = session_id
        self.cookie_count = cookie_count
        self.results = {}
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
        self.log(f"Запуск парсинга для {len(self.phrases)} фраз", "INFO")
        
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
            
            # Запуск парсера
            self.results = await turbo_parser_10tabs(
                account_name=self.profile_email,
                profile_path=self.profile_path,
                phrases=self.phrases,
                headless=False,
                proxy_uri=self.proxy,
            )
            
            self.log(f"✓ Парсинг завершён. Получено: {len(self.results)} результатов", "SUCCESS")
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
    task_completed = Signal(str, dict)  # Профиль завершил работу (email, results)
    all_finished = Signal(list)  # Все задачи завершены
    
    def __init__(
        self,
        phrases: List[str],
        modes: dict,
        geo_ids: List[int],
        selected_profiles: List[dict],  # Список выбранных профилей
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.phrases = phrases
        self.modes = modes
        self.geo_ids = geo_ids or [225]
        self.selected_profiles = selected_profiles
        self._stop_requested = False
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Распределяем фразы поровну между профилями
        num_profiles = len(selected_profiles)
        phrases_per_profile = len(phrases) // num_profiles
        remainder = len(phrases) % num_profiles

        batches = []
        start_idx = 0

        for i in range(num_profiles):
            # Добавляем по одной фразе к последним профилям если есть остаток
            end_idx = start_idx + phrases_per_profile + (1 if i >= num_profiles - remainder else 0)
            batch = phrases[start_idx:end_idx]
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
                cookie_count=profile.get("cookie_count"),
            )
            self.tasks.append(task)
            
        # Логирование
        self.log_file = Path("C:/AI/yandex/keyset/logs/multiparser_journal.log")
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
    
    def stop(self):
        self._stop_requested = True
        
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
        all_results = []
        for task in self.tasks:
            if task.results:
                for phrase, freq in task.results.items():
                    all_results.append({
                        "phrase": phrase,
                        "ws": freq if isinstance(freq, (int, str)) else freq.get("ws", 0),
                        "qws": freq.get("qws", 0) if isinstance(freq, dict) else 0,
                        "bws": freq.get("bws", 0) if isinstance(freq, dict) else 0,
                        "status": "OK",
                        "profile": task.profile_email,
                    })
                    
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
                
            # Создаем корутину для каждого профиля
            tasks_coro.append(self._run_single_parser(task))
            
        # Запускаем все корутины параллельно
        results = await asyncio.gather(*tasks_coro, return_exceptions=True)
        
        # Обрабатываем результаты
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._write_log(f"❌ Ошибка в профиле {self.tasks[i].profile_email}: {str(result)}")
    
    async def _run_single_parser(self, task: SingleParsingTask):
        """Запуск одного парсера"""
        self._write_log(f"▶️ Запуск парсера для {task.profile_email}")
        
        # Подписываемся на логи задачи
        def log_callback(msg, level):
            full_msg = task.log(msg, level)
            self._write_log(full_msg)
            self.profile_log_signal.emit(task.profile_email, full_msg)
        
        # Запускаем парсинг
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
    
    def __init__(self, parent: QWidget | None = None, keys_panel: KeysPanel | None = None):
        super().__init__(parent)
        self._worker = None
        self._keys_panel = keys_panel
        self._init_ui()
        self._wire_signals()
        self._restore_session_state()

    def _init_ui(self) -> None:
        """Инициализация UI по архитектуре Key Collector"""
        main_layout = QVBoxLayout(self)

        # ═══════════════════════════════════════════════════════════
        # 1️⃣ TOP PANEL - функции вверху
        # ═══════════════════════════════════════════════════════════
        top_panel = QWidget()
        top_layout = QHBoxLayout(top_panel)

        # Кнопки основных функций
        self.btn_add = QPushButton("➕ Добавить")
        self.btn_delete = QPushButton("❌ Удалить")
        self.btn_ws = QPushButton("📊 Частотка")
        self.btn_batch = QPushButton("📦 Пакет")
        self.btn_forecast = QPushButton("💰 Прогноз")
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

        # Настройки парсинга (компактно)
        settings_group = QGroupBox("Настройки")
        settings_layout = QVBoxLayout(settings_group)

        # Режимы
        self.chk_ws = QCheckBox("WS")
        self.chk_ws.setChecked(True)
        self.chk_qws = QCheckBox('"WS"')
        self.chk_bws = QCheckBox("!WS")
        settings_layout.addWidget(QLabel("Режимы:"))
        settings_layout.addWidget(self.chk_ws)
        settings_layout.addWidget(self.chk_qws)
        settings_layout.addWidget(self.chk_bws)

        # Регионы
        self.geo_tree = GeoTree()
        self.geo_tree.setMaximumHeight(80)
        settings_layout.addWidget(QLabel("Регионы:"))
        settings_layout.addWidget(self.geo_tree)

        left_layout.addWidget(settings_group)
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

        control_buttons.addWidget(self.btn_run)
        control_buttons.addWidget(self.btn_stop)
        control_buttons.addStretch()

        # Прогресс
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        control_buttons.addWidget(self.progress)

        center_layout.addLayout(control_buttons)

        # ОСНОВНАЯ ТАБЛИЦА с результатами
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "№", "Фраза", "Частотность", "Статус"
        ])

        # Размеры колонок - ФРАЗА самая широкая!
        self.table.setColumnWidth(0, 40)    # № - узкая
        self.table.setColumnWidth(1, 500)   # Фраза - ШИРОКАЯ (основная)
        self.table.setColumnWidth(2, 120)   # Частотность
        self.table.setColumnWidth(3, 80)    # Статус

        # Настройки таблицы
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.MultiSelection)
        self.table.setMinimumHeight(400)

        center_layout.addWidget(self.table)

        # Поле ввода фраз (компактное, под таблицей)
        phrases_label = QLabel("Добавить фразы:")
        self.phrases_edit = QTextEdit()
        self.phrases_edit.setMaximumHeight(80)
        self.phrases_edit.setPlaceholderText("Введите фразы (каждая с новой строки)")

        center_layout.addWidget(phrases_label)
        center_layout.addWidget(self.phrases_edit)

        # Добавляем колонки в splitter (2 колонки: левая + центральная)
        splitter_main.addWidget(left_panel)
        splitter_main.addWidget(center_panel)

        # Пропорции: Левая ~100px, Центр ~900px
        splitter_main.setSizes([100, 900])

        main_layout.addWidget(splitter_main)

        # ═══════════════════════════════════════════════════════════
        # 3️⃣ BOTTOM JOURNAL - журнал внизу
        # ═══════════════════════════════════════════════════════════
        journal_group = QGroupBox("📋 Журнал активности")
        journal_layout = QVBoxLayout(journal_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 9pt;
            }
        """)

        journal_layout.addWidget(self.log_text)

        # Кнопка очистки логов
        self.btn_clear_log = QPushButton("Очистить журнал")
        journal_layout.addWidget(self.btn_clear_log)

        main_layout.addWidget(journal_group)
        
    def _wire_signals(self):
        """Подключение сигналов"""
        # TOP PANEL кнопки
        self.btn_add.clicked.connect(self._on_add_phrases)
        self.btn_delete.clicked.connect(self._on_delete_phrases)
        self.btn_ws.clicked.connect(self._on_run_clicked)  # Частотка = запуск парсинга
        self.btn_batch.clicked.connect(self._on_batch_parsing)
        self.btn_forecast.clicked.connect(self._on_forecast)
        self.btn_clear.clicked.connect(self._on_clear_results)
        self.btn_export.clicked.connect(self._on_export_clicked)

        # Кнопки управления парсингом
        self.btn_run.clicked.connect(self._on_run_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)

        # Левая панель - управление выбором строк
        self.btn_select_all_rows.clicked.connect(self._select_all_rows)
        self.btn_deselect_all_rows.clicked.connect(self._deselect_all_rows)
        self.btn_invert_selection.clicked.connect(self._invert_selection)

        # Журнал
        self.btn_clear_log.clicked.connect(self.log_text.clear)
        
    def _get_selected_profiles(self) -> List[dict]:
        """Получить все профили из БД (вкладка Аккаунты)"""
        selected = []
        try:
            accounts = list_accounts()
            for account in accounts:
                raw_profile_path = getattr(account, "profile_path", "") or ""
                if not raw_profile_path:
                    continue
                profile_path = Path(raw_profile_path)
                if not profile_path.is_absolute():
                    profile_path = (BASE_DIR / profile_path).resolve()
                else:
                    profile_path = profile_path.resolve()

                proxy_value = getattr(account, "proxy", None)

                selected.append({
                    'email': account.name,
                    'proxy': proxy_value.strip() if isinstance(proxy_value, str) else proxy_value,
                    'profile_path': str(profile_path),
                })
        except Exception as e:
            print(f"Ошибка загрузки профилей: {str(e)}")

        return selected

    def save_session_state(self, partial_results: List[Dict[str, Any]] | None = None) -> None:
        """Сохранить состояние парсинга, чтобы восстановить его при следующем запуске."""
        try:
            SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - best effort
            print(f"[ERROR] Failed to prepare session directory: {exc}")
            return

        phrases = [line.strip() for line in self.phrases_edit.toPlainText().splitlines() if line.strip()]
        state: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "phrases": phrases,
            "modes": {
                "ws": self.chk_ws.isChecked(),
                "qws": self.chk_qws.isChecked(),
                "bws": self.chk_bws.isChecked(),
            },
            "geo_ids": self.geo_tree.selected_geo_ids(),
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
            self.phrases_edit.setPlainText("\n".join(phrases))

        modes = state.get("modes") or {}
        self.chk_ws.setChecked(bool(modes.get("ws", True)))
        self.chk_qws.setChecked(bool(modes.get("qws", False)))
        self.chk_bws.setChecked(bool(modes.get("bws", False)))

        partial_results = state.get("partial_results") or []
        if isinstance(partial_results, list):
            self._populate_results(partial_results)

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

        # Создаём словарь результатов по фразам для быстрого поиска
        results_map = {}
        for record in rows:
            phrase = str(record.get("phrase", ""))
            ws_value = record.get("ws", "")
            status_value = record.get("status", "")
            results_map[phrase] = {
                "ws": str(ws_value) if ws_value is not None else "",
                "status": str(status_value) if status_value else "OK"
            }

        # Обновляем существующие строки в таблице
        for row in range(self.table.rowCount()):
            phrase_item = self.table.item(row, 1)
            if phrase_item:
                phrase = phrase_item.text()

                # Если для этой фразы есть результат - обновляем
                if phrase in results_map:
                    result = results_map[phrase]

                    # Колонка 2: Частотность
                    self.table.setItem(row, 2, QTableWidgetItem(result["ws"]))

                    # Колонка 3: Статус
                    status_text = "✓" if result["status"] == "OK" and result["ws"] else "⏱"
                    self.table.setItem(row, 3, QTableWidgetItem(status_text))

                    normalized_rows.append({
                        "phrase": phrase,
                        "ws": result["ws"],
                        "status": result["status"],
                    })

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
        self.table.selectAll()
        self._append_log(f"✓ Выбрано строк: {self.table.rowCount()}")

    def _deselect_all_rows(self):
        """Снять выбор со всех строк"""
        self.table.clearSelection()
        self._append_log("✗ Выбор снят")

    def _invert_selection(self):
        """Инвертировать выбор строк"""
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).isSelected():
                self.table.item(row, 0).setSelected(False)
            else:
                self.table.selectRow(row)
        selected_count = len(self.table.selectionModel().selectedRows())
        self._append_log(f"🔄 Выбор инвертирован ({selected_count} строк)")

    # ═══════════════════════════════════════════════════════════
    # Функции TOP PANEL (основные действия)
    # ═══════════════════════════════════════════════════════════

    def _on_add_phrases(self):
        """Добавить фразы из поля ввода в таблицу"""
        text = self.phrases_edit.toPlainText().strip()
        if not text:
            self._append_log("❌ Нет фраз для добавления")
            return

        phrases = [line.strip() for line in text.splitlines() if line.strip()]

        for phrase in phrases:
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)

            # № (номер строки)
            self.table.setItem(row_idx, 0, QTableWidgetItem(str(row_idx + 1)))

            # Фраза
            self.table.setItem(row_idx, 1, QTableWidgetItem(phrase))

            # Частотность (пусто)
            self.table.setItem(row_idx, 2, QTableWidgetItem(""))

            # Статус
            self.table.setItem(row_idx, 3, QTableWidgetItem("—"))

        self.phrases_edit.clear()
        self._append_log(f"➕ Добавлено фраз: {len(phrases)} (всего: {self.table.rowCount()})")

    def _on_delete_phrases(self):
        """Удалить выбранные фразы из таблицы"""
        selected_rows = sorted([idx.row() for idx in self.table.selectionModel().selectedRows()], reverse=True)

        if not selected_rows:
            self._append_log("❌ Нет выбранных строк для удаления")
            return

        for row in selected_rows:
            self.table.removeRow(row)

        # Перенумеровать строки
        for row in range(self.table.rowCount()):
            self.table.setItem(row, 0, QTableWidgetItem(str(row + 1)))

        self._append_log(f"❌ Удалено строк: {len(selected_rows)} (осталось: {self.table.rowCount()})")

    def _on_clear_results(self):
        """Очистить все результаты из таблицы"""
        row_count = self.table.rowCount()
        self.table.setRowCount(0)
        self._append_log(f"🗑️ Таблица очищена ({row_count} строк удалено)")

    def _on_batch_parsing(self):
        """Пакетный парсинг - заглушка"""
        self._append_log("📦 Пакетный парсинг (в разработке)")

    def _on_forecast(self):
        """Прогноз бюджета - заглушка"""
        self._append_log("💰 Прогноз бюджета (в разработке)")

    # ═══════════════════════════════════════════════════════════
    # Парсинг
    # ═══════════════════════════════════════════════════════════

    def _on_run_clicked(self):
        """Запуск многопоточного парсинга"""
        # Получаем фразы из таблицы (колонка 1 - "Фраза")
        phrases = []
        for row in range(self.table.rowCount()):
            phrase_item = self.table.item(row, 1)
            if phrase_item:
                phrase = phrase_item.text().strip()
                if phrase:
                    phrases.append(phrase)

        if not phrases:
            self._append_log("❌ Нет фраз для парсинга (добавьте фразы через кнопку '➕ Добавить')")
            return
            
        # Получаем выбранные профили
        selected_profiles = self._get_selected_profiles()
        if not selected_profiles:
            self._append_log("❌ Не выбраны профили для парсинга")
            return

        # Подробный отчёт перед стартом
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
            
        # Режимы парсинга
        modes = {
            "ws": self.chk_ws.isChecked(),
            "qws": self.chk_qws.isChecked(),
            "bws": self.chk_bws.isChecked(),
        }
        
        # Регионы
        geo_ids = self.geo_tree.selected_geo_ids()
        
        # Обновляем UI
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.table.setRowCount(0)
        
        # Логируем начало
        self._append_log("=" * 70)
        self._append_log(f"🚀 ЗАПУСК МНОГОПОТОЧНОГО ПАРСИНГА")
        self._append_log(f"📊 Профилей: {len(selected_profiles)}")
        self._append_log(f"📝 Фраз: {len(phrases)}")
        self._append_log("=" * 70)
        self._append_log("ℹ️ Загрузка сессионных куки обрабатывается turbo_parser_improved.load_cookies_from_profile_to_context")
        
        # Создаем многопоточный воркер
        self._worker = MultiParsingWorker(
            phrases=phrases,
            modes=modes,
            geo_ids=geo_ids,
            selected_profiles=selected_profiles,
            parent=self
        )
        
        # Подключаем сигналы
        self._worker.log_signal.connect(self._append_log)
        self._worker.profile_log_signal.connect(self._on_profile_log)
        self._worker.progress_signal.connect(self._on_progress_update)
        self._worker.task_completed.connect(self._on_task_completed)
        self._worker.all_finished.connect(self._on_all_finished)
        
        # Запускаем
        self.save_session_state()
        self._worker.start()
        
    def _on_stop_clicked(self):
        """Остановка парсинга"""
        if self._worker:
            self._worker.stop()
            self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        self._append_log("⏹ Парсинг остановлен пользователем")
        
    def _append_log(self, message: str):
        """Добавить сообщение в журнал активности"""
        self.log_text.append(message)
        # Автопрокрутка вниз
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        
    def _on_profile_log(self, profile_email: str, message: str):
        """Обработка лога от конкретного профиля"""
        # Можно добавить цветовое выделение для разных профилей
        pass
        
    def _on_progress_update(self, progress_data: dict):
        """Обновление прогресса"""
        # Вычисляем общий прогресс
        if progress_data:
            total_progress = sum(progress_data.values()) / len(progress_data)
            self.progress.setValue(int(total_progress))
            
    def _on_task_completed(self, profile_email: str, results: dict):
        """Обработка завершения задачи одного профиля"""
        self._append_log(f"✅ Профиль {profile_email} завершил парсинг. Результатов: {len(results)}")
        
    def _on_all_finished(self, all_results: List[dict]):
        """Все задачи завершены"""
        self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)

        normalized_rows = self._populate_results(all_results)

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

                # Собираем данные: фраза + WS (колонка 0 и 1)
                export_data = []
                for row in range(self.table.rowCount()):
                    phrase_item = self.table.item(row, 0)  # Колонка "Фраза"
                    ws_item = self.table.item(row, 1)      # Колонка "WS"

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
