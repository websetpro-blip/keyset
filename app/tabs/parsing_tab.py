# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

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
    QListWidget,
    QListWidgetItem,
)

from ..widgets.geo_tree import GeoTree
from ..keys_panel import KeysPanel

try:
    from ...services.accounts import list_accounts
except ImportError:
    from services.accounts import list_accounts

# Импорт turbo_parser_10tabs
PACKAGE_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

BASE_DIR = PROJECT_ROOT
SESSION_FILE = BASE_DIR / "keyset/logs/parsing_session.json"

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
    
    def __init__(self, profile_email: str, profile_path: str, proxy: str, phrases: List[str], session_id: str):
        self.profile_email = profile_email
        self.profile_path = Path(profile_path)
        self.proxy = proxy
        self.phrases = phrases
        self.session_id = session_id
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
        
        # Создаем задачи для каждого профиля
        self.tasks = []
        for profile in selected_profiles:
            task = SingleParsingTask(
                profile_email=profile['email'],
                profile_path=profile['profile_path'],
                proxy=profile.get('proxy'),
                phrases=self.phrases,
                session_id=self.session_id
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
        self._refresh_profiles()
        self._restore_session_state()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        
        # Верхняя панель с настройками
        top_panel = QHBoxLayout()
        
        # Группа: Профили
        grp_profiles = QGroupBox("Профили для парсинга")
        profiles_layout = QVBoxLayout()
        
        # Список профилей с чекбоксами
        self.profiles_list = QListWidget()
        self.profiles_list.setMaximumHeight(150)
        profiles_layout.addWidget(QLabel("Выберите профили:"))
        profiles_layout.addWidget(self.profiles_list)
        
        # Кнопки управления
        profiles_buttons = QHBoxLayout()
        self.btn_select_all = QPushButton("Выбрать все")
        self.btn_deselect_all = QPushButton("Снять все")
        self.btn_refresh_profiles = QPushButton("Обновить")
        profiles_buttons.addWidget(self.btn_select_all)
        profiles_buttons.addWidget(self.btn_deselect_all)
        profiles_buttons.addWidget(self.btn_refresh_profiles)
        profiles_layout.addLayout(profiles_buttons)
        
        grp_profiles.setLayout(profiles_layout)
        top_panel.addWidget(grp_profiles)
        
        # Группа: Режимы
        grp_modes = QGroupBox("Режимы частотности")
        modes_layout = QVBoxLayout()
        self.chk_ws = QCheckBox("WS (базовая)")
        self.chk_ws.setChecked(True)
        self.chk_qws = QCheckBox('"WS" (в кавычках)')
        self.chk_bws = QCheckBox("!WS (точная)")
        modes_layout.addWidget(self.chk_ws)
        modes_layout.addWidget(self.chk_qws)
        modes_layout.addWidget(self.chk_bws)
        grp_modes.setLayout(modes_layout)
        top_panel.addWidget(grp_modes)
        
        # Группа: Регионы
        grp_geo = QGroupBox("Регионы")
        geo_layout = QVBoxLayout()
        self.geo_tree = GeoTree()
        self.geo_tree.setMaximumHeight(120)
        geo_layout.addWidget(self.geo_tree)
        grp_geo.setLayout(geo_layout)
        top_panel.addWidget(grp_geo)
        
        layout.addLayout(top_panel)
        
        # Разделитель
        splitter = QSplitter(Qt.Vertical)
        
        # Верхняя часть - фразы и результаты
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        
        # Фразы
        phrases_group = QGroupBox("Фразы для парсинга")
        phrases_layout = QVBoxLayout()
        self.phrases_edit = QTextEdit()
        self.phrases_edit.setPlaceholderText("Введите фразы (каждая с новой строки)")
        phrases_layout.addWidget(self.phrases_edit)
        
        # Кнопки управления
        control_buttons = QHBoxLayout()
        self.btn_run = QPushButton("🚀 Запустить многопоточный парсинг")
        self.btn_run.setStyleSheet("QPushButton { font-weight: bold; padding: 10px; }")
        self.btn_stop = QPushButton("⏹ Остановить")
        self.btn_stop.setEnabled(False)
        self.btn_export = QPushButton("💾 Экспорт результатов")
        
        control_buttons.addWidget(self.btn_run)
        control_buttons.addWidget(self.btn_stop)
        control_buttons.addWidget(self.btn_export)
        phrases_layout.addLayout(control_buttons)
        
        # Прогресс
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        phrases_layout.addWidget(self.progress)
        
        phrases_group.setLayout(phrases_layout)
        top_layout.addWidget(phrases_group)
        
        # Таблица результатов
        results_group = QGroupBox("Результаты парсинга")
        results_layout = QVBoxLayout()
        
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Фраза", "WS", '"WS"', "!WS", "Статус", "Профиль", "Время", "Действия"
        ])
        results_layout.addWidget(self.table)
        
        results_group.setLayout(results_layout)
        top_layout.addWidget(results_group)
        
        splitter.addWidget(top_widget)
        
        # Нижняя часть - журнал активности
        log_group = QGroupBox("📋 Журнал активности (логи всех профилей)")
        log_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(200)
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #00ff00;
                font-family: 'Consolas', 'Monaco', monospace;
                font-size: 10pt;
            }
        """)
        log_layout.addWidget(self.log_text)
        
        # Кнопка очистки логов
        self.btn_clear_log = QPushButton("Очистить журнал")
        log_layout.addWidget(self.btn_clear_log)
        
        log_group.setLayout(log_layout)
        splitter.addWidget(log_group)
        
        # Устанавливаем пропорции разделителя
        splitter.setSizes([400, 200])
        
        layout.addWidget(splitter)
        
    def _wire_signals(self):
        """Подключение сигналов"""
        self.btn_run.clicked.connect(self._on_run_clicked)
        self.btn_stop.clicked.connect(self._on_stop_clicked)
        self.btn_export.clicked.connect(self._on_export_clicked)
        self.btn_select_all.clicked.connect(self._select_all_profiles)
        self.btn_deselect_all.clicked.connect(self._deselect_all_profiles)
        self.btn_refresh_profiles.clicked.connect(self._refresh_profiles)
        self.btn_clear_log.clicked.connect(self.log_text.clear)
        
    def _refresh_profiles(self):
        """Обновить список профилей"""
        self.profiles_list.clear()
        
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

                item = QListWidgetItem(f"📧 {account.name}")
                item.setCheckState(Qt.Unchecked)
                item.setData(Qt.UserRole, {
                    'email': account.name,
                    'proxy': proxy_value.strip() if isinstance(proxy_value, str) else proxy_value,
                    'profile_path': str(profile_path),
                })
                self.profiles_list.addItem(item)
                    
            self._append_log(f"✅ Загружено профилей: {self.profiles_list.count()}")
        except Exception as e:
            self._append_log(f"❌ Ошибка загрузки профилей: {str(e)}")
            
    def _select_all_profiles(self):
        """Выбрать все профили"""
        for i in range(self.profiles_list.count()):
            self.profiles_list.item(i).setCheckState(Qt.Checked)
            
    def _deselect_all_profiles(self):
        """Снять выделение со всех профилей"""
        for i in range(self.profiles_list.count()):
            self.profiles_list.item(i).setCheckState(Qt.Unchecked)
            
    def _get_selected_profiles(self) -> List[dict]:
        """Получить выбранные профили"""
        selected = []
        for i in range(self.profiles_list.count()):
            item = self.profiles_list.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
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
            "selected_profiles": self._get_selected_profiles(),
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

        saved_profiles = state.get("selected_profiles") or []
        saved_emails = {profile.get("email") for profile in saved_profiles if profile.get("email")}
        for i in range(self.profiles_list.count()):
            item = self.profiles_list.item(i)
            data = item.data(Qt.UserRole) or {}
            if data.get("email") in saved_emails:
                item.setCheckState(Qt.Checked)

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
        """Отобразить результаты в таблице, обновить панели и вернуть нормализованные строки."""
        normalized_rows: List[Dict[str, Any]] = []
        self.table.setRowCount(0)

        for record in rows:
            phrase = str(record.get("phrase", ""))
            ws_value = record.get("ws", "")
            qws_value = record.get("qws", "")
            bws_value = record.get("bws", "")
            status_value = record.get("status", "")
            profile_value = record.get("profile", "")
            timestamp_value = record.get("time") or time.strftime("%H:%M:%S")

            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            values = [
                phrase,
                str(ws_value) if ws_value is not None else "",
                str(qws_value) if qws_value is not None else "",
                str(bws_value) if bws_value is not None else "",
                str(status_value),
                str(profile_value),
                str(timestamp_value),
                "⋯",
            ]
            for col, value in enumerate(values):
                self.table.setItem(row_idx, col, QTableWidgetItem(value))

            normalized_rows.append(
                {
                    "phrase": phrase,
                    "ws": values[1],
                    "qws": values[2],
                    "bws": values[3],
                    "status": values[4],
                    "profile": values[5],
                    "time": values[6],
                }
            )

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
        
    def _on_run_clicked(self):
        """Запуск многопоточного парсинга"""
        # Получаем фразы
        phrases = [line.strip() for line in self.phrases_edit.toPlainText().splitlines() if line.strip()]
        if not phrases:
            self._append_log("❌ Нет фраз для парсинга")
            return
            
        # Получаем выбранные профили
        selected_profiles = self._get_selected_profiles()
        if not selected_profiles:
            self._append_log("❌ Не выбраны профили для парсинга")
            return
            
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
        """Экспорт результатов"""
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
                with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    # Заголовки
                    headers = []
                    for col in range(self.table.columnCount()):
                        headers.append(self.table.horizontalHeaderItem(col).text())
                    writer.writerow(headers)
                    
                    # Данные
                    for row in range(self.table.rowCount()):
                        row_data = []
                        for col in range(self.table.columnCount()):
                            item = self.table.item(row, col)
                            row_data.append(item.text() if item else "")
                        writer.writerow(row_data)
                        
                self._append_log(f"✅ Результаты экспортированы: {file_path}")
            except Exception as e:
                self._append_log(f"❌ Ошибка экспорта: {str(e)}")
