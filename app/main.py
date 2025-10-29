from __future__ import annotations

import json
import os
import csv
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, QThread, Signal, QUrl, QSignalBlocker, QSettings
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QDoubleSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..services import phrase_tools
from ..services import accounts as account_service
from ..services import tasks as task_service
from ..services import importer as importer_service
from ..services import frequency as frequency_service
from ..workers.frequency_runner import execute_task
from ..workers.deep_runner import run_deep_task
from ..core.db import Base, engine, ensure_schema, SessionLocal
from .turbo_tab_qt import TurboParserTab
from .full_pipeline_tab import FullPipelineTab
from .accounts_tab_extended import AccountsTabExtended
from .keys_panel import KeysPanel
from .tabs import ParsingTab  # Новая единая вкладка парсинга
from ..core.models import Task
from ..core.regions import load_regions

LOGS_DIR = Path("results") / "gui_logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
MANUAL_SEEDS_DIR = Path("results") / "manual_inputs"
MANUAL_SEEDS_DIR.mkdir(parents=True, exist_ok=True)


def append_log_line(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        pass


def materialize_seeds(manual_lines: list[str], file_path: Optional[str], prefix: str) -> Path:
    prepared = [line.strip() for line in manual_lines if line.strip()]
    if prepared:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        manual_path = MANUAL_SEEDS_DIR / f"{prefix}_{timestamp}.txt"
        manual_path.write_text("\n".join(prepared), encoding="utf-8")
        return manual_path
    if not file_path:
        raise ValueError("Укажите фразы вручную или выберите файл")
    path = Path(file_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    return path


TASK_KIND_LABELS = {
    "frequency": "Частотность",
    "deep": "Парсинг вглубь",
}

STATUS_LABELS = {
    "ok": "Готов",
    "cooldown": "Пауза",
    "captcha": "Капча",
    "banned": "Бан",
    "disabled": "Отключен",
    "error": "Ошибка",
}


def status_label(code: str) -> str:
    return STATUS_LABELS.get(code, code)


def format_ts(value: Optional[datetime]) -> str:
    if not value:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


def open_local_path(parent: QWidget | None, path: Optional[str]) -> None:
    if not path:
        return
    target = Path(path).expanduser()
    if not target.exists():
        QMessageBox.warning(parent, "Открытие файла", f"Файл не найден: {target}")
        return
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

def fetch_task_summary(task_id: int) -> Optional[dict[str, Any]]:
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None:
            return None
        return {
            "status": task.status,
            "output_path": task.output_path,
            "log_path": task.log_path,
            "error_message": task.error_message,
        }

class AccountDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, data: Optional[dict[str, Any]] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Аккаунт")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Логин Яндекса (например: dsmismirnov)")
        
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Пароль от аккаунта")
        
        self.secret_edit = QLineEdit()
        self.secret_edit.setPlaceholderText("Ответ на секретный вопрос (если есть)")
        
        self.profile_edit = QLineEdit()
        self.profile_edit.setPlaceholderText("Оставьте пустым для автоматического создания")
        
        self.proxy_edit = QLineEdit()
        self.proxy_edit.setPlaceholderText("Формат: ip:port@user:pass или ip:port")
        
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText("Дополнительные заметки")
        self.notes_edit.setMaximumHeight(60)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        form = QFormLayout(self)
        form.addRow("Логин:", self.name_edit)
        form.addRow("Пароль:", self.password_edit)
        form.addRow("Секретный ответ:", self.secret_edit)
        form.addRow("Путь к профилю:", self.profile_edit)
        form.addRow("Прокси:", self.proxy_edit)
        form.addRow("Заметки:", self.notes_edit)
        form.addRow(buttons)

        if data:
            self.name_edit.setText(data.get("name", ""))
            self.password_edit.setText(data.get("password", ""))
            self.secret_edit.setText(data.get("secret_answer", ""))
            self.profile_edit.setText(data.get("profile_path", ""))
            self.proxy_edit.setText(data.get("proxy") or "")
            self.notes_edit.setPlainText(data.get("notes") or "")

        self._result: Optional[dict[str, Any]] = None

    def accept(self) -> None:  # type: ignore[override]
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Проверка", "Укажите логин аккаунта")
            return
            
        password = self.password_edit.text().strip()
        if not password:
            QMessageBox.warning(self, "Проверка", "Укажите пароль аккаунта")
            return
            
        profile_path = self.profile_edit.text().strip()
        if not profile_path:
            profile_path = f".profiles/{name}"
            
        secret_answer = self.secret_edit.text().strip() or None
        proxy = self.proxy_edit.text().strip() or None
        notes = self.notes_edit.toPlainText().strip() or None
        
        # Сохраняем в accounts.json
        import json
        from pathlib import Path
        
        accounts_file = Path("C:/AI/yandex/configs/accounts.json")
        accounts_file.parent.mkdir(exist_ok=True)
        
        accounts = []
        if accounts_file.exists():
            with open(accounts_file, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
        
        # Проверяем, не существует ли уже такой аккаунт
        for acc in accounts:
            if acc["login"] == name:
                QMessageBox.warning(self, "Ошибка", f"Аккаунт {name} уже существует!")
                return
        
        # Добавляем новый аккаунт
        accounts.append({
            "login": name,
            "password": password,
            "secret": secret_answer,
            "proxy": proxy
        })
        
        # Сохраняем обратно
        with open(accounts_file, 'w', encoding='utf-8') as f:
            json.dump(accounts, f, ensure_ascii=False, indent=2)
        
        self._result = {
            "name": name,
            "profile_path": profile_path,
            "proxy": proxy,
            "notes": notes,
        }
        super().accept()

    def get_data(self) -> Optional[dict[str, Any]]:
        return self._result


class PhrasePrepTab(QWidget):
    def __init__(self, *, collect_tab: "CollectTab" | None = None, deep_tab: "DeepTab" | None = None) -> None:
        super().__init__()
        self.collect_tab = collect_tab
        self.deep_tab = deep_tab

        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText("Вставьте исходные фразы по одной в строке")

        self.result_edit = QPlainTextEdit()
        self.result_edit.setReadOnly(True)

        self.status_label = QLabel()
        self.status_label.setObjectName("phraseStatus")

        self.lowercase_check = QCheckBox("Привести к нижнему регистру")
        self.lowercase_check.setChecked(True)
        self.strip_punct_check = QCheckBox("Удалить знаки пунктуации")
        self.dedup_check = QCheckBox("Удалить дубликаты")
        self.dedup_check.setChecked(True)

        norm_box = QGroupBox("Нормализация")
        norm_layout = QVBoxLayout(norm_box)
        norm_layout.addWidget(self.lowercase_check)
        norm_layout.addWidget(self.strip_punct_check)
        norm_layout.addWidget(self.dedup_check)
        self.normalize_btn = QPushButton("Нормализовать")
        self.normalize_btn.clicked.connect(self.normalize_phrases)
        norm_layout.addWidget(self.normalize_btn)

        self.min_len_spin = QSpinBox()
        self.min_len_spin.setRange(0, 100)
        self.min_len_spin.setValue(0)
        self.max_len_spin = QSpinBox()
        self.max_len_spin.setRange(0, 200)
        self.max_len_spin.setSpecialValueText("без ограничения")
        self.max_len_spin.setValue(0)
        self.allow_digits_check = QCheckBox("Оставлять фразы с цифрами")
        self.allow_digits_check.setChecked(True)
        self.allow_punct_filter_check = QCheckBox("Оставлять фразы с пунктуацией")
        self.allow_punct_filter_check.setChecked(True)
        self.stopwords_line = QLineEdit()
        self.stopwords_line.setPlaceholderText("стоп-слова через запятую")

        filter_box = QGroupBox("Фильтрация")
        filter_form = QFormLayout(filter_box)
        filter_form.addRow("Мин. длина:", self.min_len_spin)
        filter_form.addRow("Макс. длина:", self.max_len_spin)
        filter_form.addRow("", self.allow_digits_check)
        filter_form.addRow("", self.allow_punct_filter_check)
        filter_form.addRow("Стоп-слова:", self.stopwords_line)
        self.filter_btn = QPushButton("Фильтровать")
        self.filter_btn.clicked.connect(self.filter_phrases)
        filter_form.addRow("", self.filter_btn)

        self.similarity_spin = QDoubleSpinBox()
        self.similarity_spin.setRange(0.0, 1.0)
        self.similarity_spin.setSingleStep(0.05)
        self.similarity_spin.setValue(0.5)

        cluster_box = QGroupBox("Кластеризация")
        cluster_form = QFormLayout(cluster_box)
        cluster_form.addRow("Порог схожести:", self.similarity_spin)
        self.cluster_btn = QPushButton("Сгруппировать")
        self.cluster_btn.clicked.connect(self.cluster_phrases)
        cluster_form.addRow("", self.cluster_btn)

        self.combo_edit = QPlainTextEdit()
        self.combo_edit.setPlaceholderText(
            "    .\n:\n\n\n\n\n"
        )
        self.combo_normalize_check = QCheckBox("Применять нормализацию к комбинациям")
        self.combo_normalize_check.setChecked(True)
        self.combinate_btn = QPushButton("Сгенерировать комбинации")
        self.combinate_btn.clicked.connect(self.generate_combinations)

        combo_box = QGroupBox("Комбинации словарей")
        combo_layout = QVBoxLayout(combo_box)
        combo_layout.addWidget(self.combo_edit)
        combo_layout.addWidget(self.combo_normalize_check)
        combo_layout.addWidget(self.combinate_btn)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("Исходные маски"))
        left_layout.addWidget(self.input_edit)
        left_layout.addWidget(combo_box)
        left_layout.addWidget(norm_box)
        left_layout.addWidget(filter_box)
        left_layout.addWidget(cluster_box)
        left_layout.addStretch(1)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.addWidget(QLabel("Результат"))
        right_layout.addWidget(self.result_edit)
        buttons_row = QHBoxLayout()
        self.copy_btn = QPushButton("Перенести во вход")
        self.copy_btn.clicked.connect(self.copy_to_input)
        self.apply_collect_btn = QPushButton("В частотность")
        self.apply_collect_btn.clicked.connect(self.push_to_collect)
        self.apply_deep_btn = QPushButton("В глубину")
        self.apply_deep_btn.clicked.connect(self.push_to_deep)
        self.save_btn = QPushButton("Сохранить…")
        self.save_btn.clicked.connect(self.save_result)
        self.clear_btn = QPushButton("Очистить")
        self.clear_btn.clicked.connect(self.clear_result)
        buttons_row.addWidget(self.copy_btn)
        buttons_row.addWidget(self.apply_collect_btn)
        buttons_row.addWidget(self.apply_deep_btn)
        buttons_row.addWidget(self.save_btn)
        buttons_row.addWidget(self.clear_btn)
        buttons_row.addStretch(1)
        right_layout.addLayout(buttons_row)
        right_layout.addWidget(self.status_label)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter)

        self.set_collect_tab(collect_tab)
        self.set_deep_tab(deep_tab)

    def set_collect_tab(self, collect_tab: "CollectTab" | None) -> None:
        self.collect_tab = collect_tab
        self.apply_collect_btn.setEnabled(collect_tab is not None)

    def set_deep_tab(self, deep_tab: "DeepTab" | None) -> None:
        self.deep_tab = deep_tab
        self.apply_deep_btn.setEnabled(deep_tab is not None)

    def _get_input_phrases(self) -> list[str]:
        return [line.strip() for line in self.input_edit.toPlainText().splitlines() if line.strip()]

    def _get_result_phrases(self) -> list[str]:
        return [line.strip() for line in self.result_edit.toPlainText().splitlines() if line.strip()]

    def _set_result(self, phrases: list[str]) -> None:
        self.result_edit.setPlainText("\n".join(phrases))

    def _update_status(self, message: str) -> None:
        self.status_label.setText(message)

    def _build_normalizer(self) -> phrase_tools.NormalizationOptions:
        return phrase_tools.NormalizationOptions(
            lowercase=self.lowercase_check.isChecked(),
            collapse_whitespace=True,
            strip_punctuation=self.strip_punct_check.isChecked(),
            deduplicate=self.dedup_check.isChecked(),
        )

    def normalize_phrases(self) -> None:
        phrases = self._get_input_phrases()
        if not phrases:
            self._update_status("Нет исходных фраз")
            return
        options = self._build_normalizer()
        normalized = phrase_tools.normalize_phrases(phrases, options)
        self._set_result(normalized)
        self._update_status(f"Нормализовано: {len(normalized)}")

    def filter_phrases(self) -> None:
        phrases = self._get_result_phrases() or self._get_input_phrases()
        if not phrases:
            self._update_status("Нет данных для фильтрации")
            return
        max_len = self.max_len_spin.value() or None
        stopwords = [w.strip() for w in self.stopwords_line.text().split(',') if w.strip()]
        options = phrase_tools.FilterOptions(
            min_length=self.min_len_spin.value(),
            max_length=max_len,
            allow_digits=self.allow_digits_check.isChecked(),
            allow_punctuation=self.allow_punct_filter_check.isChecked(),
            stopwords=stopwords,
        )
        filtered = phrase_tools.filter_phrases(phrases, options)
        self._set_result(filtered)
        self._update_status(f"Отфильтровано: {len(filtered)}")

    def cluster_phrases(self) -> None:
        phrases = self._get_result_phrases() or self._get_input_phrases()
        if not phrases:
            self._update_status("Нет данных для кластеризации")
            return
        clusters = phrase_tools.cluster_phrases(phrases, similarity=self.similarity_spin.value())
        lines: list[str] = []
        for size, representative, members in phrase_tools.walk_clusters(clusters):
            lines.append(f"[{size}] {representative} -> {'; '.join(members)}")
        self.result_edit.setPlainText("\n".join(lines))
        self._update_status(f"Кластеров: {len(clusters)}")

    def generate_combinations(self) -> None:
        blocks: list[list[str]] = []
        current: list[str] = []
        for line in self.combo_edit.toPlainText().splitlines():
            stripped = line.strip()
            if not stripped:
                if current:
                    blocks.append(current)
                    current = []
                continue
            current.append(stripped)
        if current:
            blocks.append(current)
        if not blocks:
            self._update_status("Словари не заданы")
            return
        normalizer = self._build_normalizer() if self.combo_normalize_check.isChecked() else None
        combos = phrase_tools.generate_combinations(blocks, normalization=normalizer)
        self._set_result(combos)
        self._update_status(f"Комбинаций: {len(combos)}")

    def copy_to_input(self) -> None:
        phrases = self._get_result_phrases()
        if not phrases:
            self._update_status("Нет данных для переноса")
            return
        self.input_edit.setPlainText("\n".join(phrases))
        self._update_status("Фразы перенесены во вход")

    def push_to_collect(self) -> None:
        if not self.collect_tab:
            self._update_status("Вкладка «Частотность» недоступна")
            return
        phrases = self._get_result_phrases() or self._get_input_phrases()
        if not phrases:
            self._update_status("Нет данных для передачи")
            return
        self.collect_tab.set_manual_seeds(phrases)
        self._update_status(f"Передано в частотность: {len(phrases)}")

    def push_to_deep(self) -> None:
        if not self.deep_tab:
            self._update_status("Вкладка «Парсинг вглубь» недоступна")
            return
        phrases = self._get_result_phrases() or self._get_input_phrases()
        if not phrases:
            self._update_status("Нет данных для передачи")
            return
        self.deep_tab.set_manual_seeds(phrases)
        self._update_status(f"Передано в глубину: {len(phrases)}")

    def save_result(self) -> None:
        phrases = self._get_result_phrases()
        if not phrases:
            self._update_status("Нет результатов для сохранения")
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить результат",
            str(Path.cwd() / "phrases.txt"),
            "Текстовые файлы (*.txt);;CSV файлы (*.csv);;Все файлы (*.*)",
        )
        if not filename:
            return
        try:
            Path(filename).write_text("\n".join(phrases), encoding="utf-8")
            self._update_status(f"Сохранено: {filename}")
        except OSError as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось выполнить действие\n{exc}")

    def clear_result(self) -> None:
        self.result_edit.clear()
        self._update_status(" ")

    def clear_input(self) -> None:
        self.input_edit.clear()

class FrequencyWorkerThread(QThread):
    """Ворк-поток для задач частотности."""

    log_message = Signal(str)
    completed = Signal(bool, str)
    refresh_requested = Signal()

    def __init__(self, task_id: int) -> None:
        super().__init__()
        self.task_id = task_id

    def run(self) -> None:  # type: ignore[override]
        self.log_message.emit(f"[freq] Старт задачи #{self.task_id}")
        try:
            execute_task(self.task_id)
            summary = fetch_task_summary(self.task_id)
            message = "Задача выполнена"
            if summary:
                output_path = summary.get("output_path")
                log_path = summary.get("log_path")
                if output_path:
                    message = f"Результат: {output_path}"
                elif log_path:
                    message = f"Лог: {log_path}"
            self.log_message.emit(f"[freq] Завершение задачи #{self.task_id}")
            self.completed.emit(True, message)
        except Exception as exc:  # pragma: no cover - GUI
            self.log_message.emit(f"[freq] Ошибка #{self.task_id}: {exc}")
            self.completed.emit(False, str(exc))
        finally:
            self.refresh_requested.emit()



class FrequencyProcessThread(QThread):
    log_message = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, args: list[str]) -> None:
        super().__init__()
        self._args = args

    def run(self) -> None:  # type: ignore[override]
        try:
            process = subprocess.Popen(
                self._args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
        except OSError as exc:
            self.finished.emit(False, f"Ошибка запуска процесса: {exc}")
            return

        assert process.stdout is not None
        for line in process.stdout:
            self.log_message.emit(line.rstrip())
        process.wait()
        success = process.returncode == 0
        msg = f"процесс завершён с кодом {process.returncode}"
        self.finished.emit(success, msg)


class DeepWorkerThread(QThread):
    """Ворк-поток для задач парсинга вглубь."""

    log_message = Signal(str)
    completed = Signal(bool, str)
    refresh_requested = Signal()

    def __init__(
        self,
        *,
        task_id: int,
        seeds_file: str,
        depth: int,
        min_shows: int,
        expand_min: int,
        topk: int,
        region: Optional[int],
        timestamp: str,
        log_path: Path,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.seeds_file = seeds_file
        self.depth = depth
        self.min_shows = min_shows
        self.expand_min = expand_min
        self.topk = topk
        self.region = region
        self.timestamp = timestamp
        self.log_path = log_path

    def run(self) -> None:  # type: ignore[override]
        append_log_line(self.log_path, "Старт парсинга вглубь")
        self.log_message.emit(f"[deep] Старт задачи #{self.task_id}")
        started = datetime.utcnow()
        task_service.update_task_status(
            self.task_id,
            "running",
            started_at=started,
            log_path=str(self.log_path),
        )
        try:
            output_path = run_deep_task(
                seeds_file=self.seeds_file,
                depth=self.depth,
                min_shows=self.min_shows,
                expand_min=self.expand_min,
                topk=self.topk,
                region=self.region,
                timestamp=self.timestamp,
            )
            finished = datetime.utcnow()
            task_service.update_task_status(
                self.task_id,
                "completed",
                finished_at=finished,
                output_path=output_path,
            )
            append_log_line(self.log_path, f"Завершено успешно: {output_path}")
            self.log_message.emit(f"[deep] Завершение задачи #{self.task_id}")
            self.completed.emit(True, f"Результат: {output_path}")
        except Exception as exc:  # pragma: no cover - GUI
            append_log_line(self.log_path, f"Ошибка: {exc}")
            self.log_message.emit(f"[deep] Ошибка #{self.task_id}: {exc}")
            self.completed.emit(False, str(exc))
            task_service.update_task_status(self.task_id, "failed", error_message=str(exc))
        finally:
            self.refresh_requested.emit()
class AccountsTab(QWidget):
    accounts_changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Аккаунт",
            "Статус",
            "Профиль",
            "Прокси",
            "Последнее использование",
            "Заметки",
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.table.itemDoubleClicked.connect(lambda *_: self.edit_account())

        self.add_btn = QPushButton("Добавить")
        self.add_btn.clicked.connect(self.add_account)
        self.edit_btn = QPushButton("Изменить")
        self.edit_btn.clicked.connect(self.edit_account)
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.clicked.connect(self.delete_account)
        self.import_btn = QPushButton("Импорт…")
        self.import_btn.clicked.connect(self.import_accounts)
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh)

        buttons = QHBoxLayout()
        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.edit_btn)
        buttons.addWidget(self.delete_btn)
        buttons.addWidget(self.import_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.refresh_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.table)

        self._accounts: list[Any] = []
        self.refresh()

    def _selected_row(self) -> int:
        selection = self.table.selectionModel()
        if not selection:
            return -1
        indexes = selection.selectedRows()
        return indexes[0].row() if indexes else -1

    def _current_account(self) -> Any | None:
        row = self._selected_row()
        if row < 0 or row >= len(self._accounts):
            return None
        return self._accounts[row]

    def _update_buttons(self) -> None:
        has_selection = self._current_account() is not None
        self.edit_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)

    def refresh(self) -> None:
        self._accounts = account_service.list_accounts()
        self.table.setRowCount(len(self._accounts))
        for row, account in enumerate(self._accounts):
            items = [
                QTableWidgetItem(account.name),
                QTableWidgetItem(status_label(account.status)),
                QTableWidgetItem(account.profile_path),
                QTableWidgetItem(account.proxy or ""),
                QTableWidgetItem(format_ts(account.last_used_at)),
                QTableWidgetItem(account.notes or ""),
            ]
            items[0].setData(Qt.UserRole, account.id)
            for col, item in enumerate(items):
                if col in (0, 1, 3, 4):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
        self._update_buttons()

    def add_account(self) -> None:
        dialog = AccountDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if data:
                try:
                    account_service.create_account(**data)
                except Exception as exc:
                    QMessageBox.warning(self, "Ошибка", str(exc))
                    return
                self.refresh()
                self.accounts_changed.emit()

    def edit_account(self) -> None:
        account = self._current_account()
        if not account:
            return
        dialog = AccountDialog(self, data={
            "name": account.name,
            "profile_path": account.profile_path,
            "proxy": account.proxy,
            "notes": account.notes,
        })
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if data:
                try:
                    account_service.update_account(account.id, **data)
                except Exception as exc:
                    QMessageBox.warning(self, "Ошибка", str(exc))
                    return
                self.refresh()
                self.accounts_changed.emit()

    def delete_account(self) -> None:
        account = self._current_account()
        if not account:
            return
        if QMessageBox.question(
            self,
            "Удаление аккаунта",
            f"Удалить аккаунт {account.name}?",
        ) != QMessageBox.Yes:
            return
        account_service.delete_account(account.id)
        self.refresh()
        self.accounts_changed.emit()

    def import_accounts(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Импорт аккаунтов",
            str(Path.cwd()),
            "Текстовые файлы (*.txt);;Все файлы (*.*)",
        )
        if not path:
            return
        try:
            imported = importer_service.import_accounts_from_file(path)
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось выполнить действие\n{exc}")
            return
        QMessageBox.information(self, "Импорт аккаунтов", f"Импортировано записей: {imported}")
        self.refresh()
        self.accounts_changed.emit()

class ResultViewerDialog(QDialog):
    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = Path(path)
        self.setWindowTitle(f"Просмотр результата — {self._path.name}")

        self.path_label = QLabel(str(self._path))
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)

        button_box = QDialogButtonBox(QDialogButtonBox.Close)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self.path_label)
        layout.addWidget(self.table)
        layout.addWidget(button_box)

        try:
            self._load_csv()
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть файл:\n{exc}")

    def _load_csv(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(self._path)

        with self._path.open('r', encoding='utf-8-sig', newline='') as handle:
            sample = handle.read(4096)
            handle.seek(0)
            delimiter = ';'
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=';    ,')
                delimiter = dialect.delimiter
            except Exception:
                pass
            reader = csv.reader(handle, delimiter=delimiter)
            rows = list(reader)

        if not rows:
            self.table.setRowCount(0)
            self.table.setColumnCount(0)
            return

        header = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []
        self.table.setColumnCount(len(header))
        self.table.setHorizontalHeaderLabels(header)
        self.table.setRowCount(len(data_rows))

        for row_idx, row in enumerate(data_rows):
            for col_idx, value in enumerate(row):
                item = QTableWidgetItem(value)
                self.table.setItem(row_idx, col_idx, item)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)


class TasksTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.columns = [
            'ID',
            'Тип',
            'Аккаунт',
            'Регион',
            'Статус',
            'Создано',
            'Старт',
            'Завершено',
            'Файл',
            'Лог',
            'Комментарий',
        ]
        self.table = QTableWidget(0, len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)
        header = self.table.horizontalHeader()
        for idx in range(len(self.columns)):
            mode = QHeaderView.ResizeToContents if idx < 5 else QHeaderView.Stretch
            header.setSectionResizeMode(idx, mode)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)

        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        self.open_result_btn = QPushButton("Открыть результат")
        self.open_result_btn.clicked.connect(self.open_result)
        self.open_log_btn = QPushButton("Открыть лог")
        self.open_log_btn.clicked.connect(self.open_log)

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_btn)
        buttons.addWidget(self.open_result_btn)
        buttons.addWidget(self.open_log_btn)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons)
        layout.addWidget(self.table)

        self._tasks: list[dict[str, Any]] = []
        self.refresh()

    def _selected_task(self) -> Optional[dict[str, Any]]:
        selection = self.table.selectionModel()
        if not selection:
            return None
        indexes = selection.selectedRows()
        if not indexes:
            return None
        row = indexes[0].row()
        if row < 0 or row >= len(self._tasks):
            return None
        return self._tasks[row]

    def _update_buttons(self) -> None:
        task = self._selected_task()
        has_output = bool(task and task.get("output_path"))
        has_log = bool(task and task.get("log_path"))
        self.open_result_btn.setEnabled(has_output)
        self.open_log_btn.setEnabled(has_log)

    def refresh(self) -> None:
        self._tasks = task_service.list_recent_tasks()
        self.table.setRowCount(len(self._tasks))
        for row, task in enumerate(self._tasks):
            values = [
                str(task["id"]),
                TASK_KIND_LABELS.get(task["kind"], task["kind"]),
                task.get("account_name") or "",
                str(task.get("region") or 0),
                task.get("status_label") or task.get("status"),
                format_ts(task.get("created_at")),
                format_ts(task.get("started_at")),
                format_ts(task.get("finished_at")),
                task.get("output_path") or "",
                task.get("log_path") or "",
                task.get("error_message") or (task.get("params") or ""),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (0, 3):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
        self._update_buttons()


    def open_result(self) -> None:
        task = self._selected_task()
        if not task:
            return
        path_value = task.get("output_path")
        if not path_value:
            QMessageBox.information(self, "Результат отсутствует", "Путь к файлу результата не задан.")
            return
        result_path = Path(path_value).expanduser()
        if not result_path.exists():
            QMessageBox.warning(self, "Файл не найден", f"Файл отсутствует\n{result_path}")
            return
        if result_path.suffix.lower() in {".csv", ".tsv"}:
            dialog = ResultViewerDialog(result_path, self)
            dialog.exec()
        else:
            open_local_path(self, path_value)


    def open_log(self) -> None:
        task = self._selected_task()
        if task:
            open_local_path(self, task.get("log_path"))



class FrequencyResultsTab(QWidget):
    results_updated = Signal()  # Сигнал при обновлении результатов
    
    def __init__(self) -> None:
        super().__init__()
        self.status_filter = QComboBox()
        self.status_filter.addItem("Все", "all")
        self.status_filter.addItem("В очереди", "queued")
        self.status_filter.addItem("В работе", "running")
        self.status_filter.addItem("Готово", "ok")
        self.status_filter.addItem("Ошибка", "error")
        self.status_filter.currentIndexChanged.connect(self.refresh)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(10, 5000)
        self.limit_spin.setValue(500)
        self.limit_spin.setSingleStep(100)

        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        self.open_csv_btn = QPushButton("Открыть CSV")
        self.open_csv_btn.clicked.connect(self.open_csv)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Статус:"))
        controls.addWidget(self.status_filter)
        controls.addWidget(QLabel("Лимит:"))
        controls.addWidget(self.limit_spin)
        controls.addWidget(self.refresh_btn)
        controls.addWidget(self.open_csv_btn)
        controls.addStretch(1)

        self.stats_label = QLabel()

        self.table = QTableWidget(0, 8)  # Было 7, стало 8 колонок
        self.table.setHorizontalHeaderLabels([
            "Фраза",
            "Регион",
            "Статус",
            "WS",        # Базовая частотность (было "Частотность")
            '"WS"',      # ← НОВАЯ КОЛОНКА: частотность в кавычках
            "!WS",       # Точное соответствие (было "Точная")
            "Попытки",
            "Ошибка",
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # "WS"
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # !WS
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Попытки
        header.setSectionResizeMode(7, QHeaderView.Stretch)           # Ошибка
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)

        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.stats_label)
        layout.addWidget(self.table)

        self.refresh()

    def refresh(self) -> None:
        results = frequency_service.list_results(
            status=self.status_filter.currentData(),
            limit=self.limit_spin.value(),
        )
        stats = frequency_service.counts_by_status()
        stats_text = ", ".join(f"{key}: {value}" for key, value in stats.items())
        self.stats_label.setText(f"Статистика: {stats_text}")

        # Helper function to convert to int with 0 fallback
        def to_int0(val):
            if val is None or val == '' or val == '-':
                return 0
            try:
                return int(val)
            except (ValueError, TypeError):
                return 0

        self.table.setRowCount(len(results))
        for row_idx, row in enumerate(results):
            values = [
                row['mask'],                              # Фраза
                str(row['region']),                       # Регион
                row['status'],                            # Статус
                str(to_int0(row.get('freq_total', 0))),   # WS (базовая)
                str(to_int0(row.get('freq_quotes', 0))),  # "WS" (в кавычках)
                str(to_int0(row.get('freq_exact', 0))),   # !WS (точное)
                str(to_int0(row.get('attempts', 0))),     # Попытки
                row.get('error', ''),                     # Ошибка
            ]
            for col_idx, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col_idx in (1, 3, 4, 5, 6):  # Выравнивание по центру: Регион, WS, "WS", !WS, Попытки
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row_idx, col_idx, item)
        
        # Сигнализируем об обновлении результатов
        self.results_updated.emit()

    def open_csv(self) -> None:
        results_dir = Path('results')
        candidates = sorted(results_dir.glob('freq_*.csv'), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        if candidates:
            csv_path = candidates[0]
        else:
            csv_path = results_dir / 'freq_async.csv'
        if not csv_path.exists():
            QMessageBox.information(self, 'CSV', 'Подходящий CSV файл ещё не создан.')
            return
        open_local_path(self, str(csv_path))


class CollectTab(QWidget):
    def __init__(self, accounts_tab: "AccountsTab", tasks_tab: "TasksTab" | None, log_widget: QTextEdit, results_tab: "FrequencyResultsTab" | None = None) -> None:
        super().__init__()
        self.accounts_tab = accounts_tab
        self.tasks_tab = tasks_tab
        self.results_tab = results_tab
        self.log_widget = log_widget
        self._accounts: list[Any] = []
        self._from_preparation = False

        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText("Путь к файлу с фразами (необязательно)")
        self.seed_edit.textChanged.connect(self._update_source_label)
        self.seed_text = QPlainTextEdit()
        self.seed_text.setPlaceholderText("Вставьте фразы вручную (по одной в строке)")
        self.seed_text.setMaximumHeight(160)
        self.seed_text.textChanged.connect(self._handle_manual_edit)

        self.browse_btn = QPushButton("Обзор...")
        self.browse_btn.clicked.connect(self.choose_file)
        self.accounts_combo = QComboBox()
        self.accounts_combo.setMinimumWidth(220)
        self.region_combo = QComboBox()
        self.region_combo.setEditable(True)
        self.region_combo.lineEdit().setPlaceholderText("Регион (по умолчанию 225)")
        self.headless_check = QCheckBox("Запускать браузер без интерфейса (headless)")
        self.dump_json_check = QCheckBox("Сохранять сырой ответ Wordstat в JSON")
        self.source_label = QLabel("Источник: не выбран")
        self.start_btn = QPushButton("Запустить сбор")
        self.start_btn.clicked.connect(self.start_task)

        accounts_tab.accounts_changed.connect(self.refresh_accounts)

        seeds_layout = QVBoxLayout()
        file_layout = QHBoxLayout()
        file_layout.addWidget(self.seed_edit)
        file_layout.addWidget(self.browse_btn)
        seeds_layout.addLayout(file_layout)
        seeds_layout.addWidget(self.seed_text)

        form = QFormLayout()
        form.addRow("Фразы:", seeds_layout)
        form.addRow("Аккаунт:", self.accounts_combo)
        form.addRow("Регион (GeoID):", self.region_combo)
        form.addRow("", self.headless_check)
        form.addRow("", self.dump_json_check)
        form.addRow("", self.source_label)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.start_btn)
        layout.addStretch(1)

        self.populate_regions()
        self.refresh_accounts()

        self._worker: Optional[FrequencyProcessThread] = None

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_widget.append(f"[{stamp}] {message}")

    def populate_regions(self) -> None:
        self.region_combo.clear()
        self.region_combo.addItem(" (225)", None)
        regions = load_regions()
        for region in regions:
            label = f"{region.name} ({region.id})"
            self.region_combo.addItem(label, region.id)
        default_index = next((i for i, region in enumerate(regions, start=1) if region.id == 225), 0)
        self.region_combo.setCurrentIndex(default_index)

    def refresh_accounts(self) -> None:
        current_id = self.accounts_combo.currentData()
        self._accounts = account_service.list_accounts()
        self.accounts_combo.clear()
        selected_index = 0
        for idx, account in enumerate(self._accounts):
            label = account.name if account.status == "ok" else f"{account.name}  {status_label(account.status)}"
            self.accounts_combo.addItem(label, account.id)
            if current_id == account.id:
                selected_index = idx
        if self._accounts:
            self.accounts_combo.setCurrentIndex(selected_index)

    def set_manual_seeds(self, phrases: list[str]) -> None:
        prepared = [p.strip() for p in phrases if p.strip()]
        with QSignalBlocker(self.seed_text):
            self.seed_text.setPlainText("\n".join(prepared))
        self.seed_edit.clear()
        self._from_preparation = True
        self._update_source_label()
        if prepared:
            self.seed_text.setFocus()

    def _handle_manual_edit(self) -> None:
        if self._from_preparation:
            self._from_preparation = False
        self._update_source_label()

    def _update_source_label(self) -> None:
        manual_count = len([line.strip() for line in self.seed_text.toPlainText().splitlines() if line.strip()])
        if self._from_preparation and manual_count:
            text_value = f"Источник: подготовка ({manual_count})"
        elif self.seed_edit.text().strip():
            text_value = "Источник: файл"
        elif manual_count:
            text_value = f"Источник: ручной ввод ({manual_count})"
        else:
            text_value = "Источник: не выбран"
        self.source_label.setText(text_value)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбор файла с фразами",
            str(Path.cwd()),
            "Текстовые файлы (*.txt);;Все файлы (*.*)",
        )
        if path:
            self.seed_edit.setText(path)
            with QSignalBlocker(self.seed_text):
                self.seed_text.clear()
            self._from_preparation = False
            self._update_source_label()

    def _selected_account(self) -> Any | None:
        account_id = self.accounts_combo.currentData()
        for account in self._accounts:
            if account.id == account_id:
                return account
        return None

    def start_task(self) -> None:
        accounts = account_service.list_accounts()
        active_accounts = [acc for acc in accounts if acc.status == 'ok']
        if not active_accounts:
            QMessageBox.warning(self, "Аккаунты", "Нет активных аккаунтов со статусом 'ok'.")
            return

        manual_lines = [line.strip() for line in self.seed_text.toPlainText().splitlines() if line.strip()]
        seed_file = self.seed_edit.text().strip() or None
        if not manual_lines and not seed_file:
            QMessageBox.warning(self, "Нет данных", "Добавьте фразы вручную или выберите файл с масками.")
            return
        try:
            seeds_path = materialize_seeds(manual_lines, seed_file, "freq_manual")
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return

        combo_data = self.region_combo.currentData()
        region = int(combo_data) if combo_data is not None else 225
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        output_path = Path("results") / f"freq_{timestamp}.csv"

        args = [
            sys.executable,
            '-m',
            'yandex.freq_async',
            '--input',
            str(seeds_path),
            '--output',
            str(output_path),
            '--region',
            str(region),
            '--accounts',
            str(len(active_accounts)),
        ]
        if self.dump_json_check.isChecked():
            args.append('--dump-json')
        if not self.headless_check.isChecked():
            args.append('--show')
            args.append('--manual-login')

        self._log(f"Запуск сбора частотности: {len(active_accounts)} аккаунтов, регион {region}")
        self.start_btn.setEnabled(False)
        self._worker = FrequencyProcessThread(args)
        self._worker.log_message.connect(self._log)
        self._worker.finished.connect(self._process_finished)
        self._worker.start()

    def _process_finished(self, success: bool, message: str) -> None:
        self.start_btn.setEnabled(True)
        self._worker = None
        self._log(message)
        if success:
            QMessageBox.information(self, "Частотность", "Сбор завершён успешно.")
        else:
            QMessageBox.warning(self, "Частотность", message)
        if self.tasks_tab:
            self.tasks_tab.refresh()
        if self.results_tab:
            self.results_tab.refresh()



class DeepTab(QWidget):
    def __init__(self, log_widget: QTextEdit, tasks_tab: "TasksTab" | None) -> None:
        super().__init__()
        self.log_widget = log_widget
        self.tasks_tab = tasks_tab
        self._from_preparation = False

        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText("Путь к файлу с фразами (необязательно)")
        self.seed_edit.textChanged.connect(self._update_source_label)
        self.seed_text = QPlainTextEdit()
        self.seed_text.setPlaceholderText("Вставьте фразы вручную (по одной в строке)")
        self.seed_text.setMaximumHeight(160)
        self.seed_text.textChanged.connect(self._handle_manual_edit)
        self.browse_btn = QPushButton("Обзор...")
        self.browse_btn.clicked.connect(self.choose_file)
        self.depth_spin = QSpinBox()
        self.depth_spin.setRange(1, 5)
        self.depth_spin.setValue(2)
        self.min_shows_spin = QSpinBox()
        self.min_shows_spin.setRange(0, 1_000_000)
        self.min_shows_spin.setValue(100)
        self.expand_min_spin = QSpinBox()
        self.expand_min_spin.setRange(0, 5_000_000)
        self.expand_min_spin.setValue(1000)
        self.topk_spin = QSpinBox()
        self.topk_spin.setRange(1, 1000)
        self.topk_spin.setValue(50)
        self.region_combo = QComboBox()
        self.region_combo.setEditable(True)
        self.region_combo.lineEdit().setPlaceholderText("Регион (GeoID)")
        self.source_label = QLabel(":  ")
        self.start_btn = QPushButton("Запустить парсинг")
        self.start_btn.clicked.connect(self.start_task)

        seeds_layout = QVBoxLayout()
        file_layout = QHBoxLayout()
        file_layout.addWidget(self.seed_edit)
        file_layout.addWidget(self.browse_btn)
        seeds_layout.addLayout(file_layout)
        seeds_layout.addWidget(self.seed_text)

        form = QFormLayout()
        form.addRow(":", seeds_layout)
        form.addRow("Глубина:", self.depth_spin)
        form.addRow("Мин. показы:", self.min_shows_spin)
        form.addRow("Порог расширения:", self.expand_min_spin)
        form.addRow("Макс. запросов в узле:", self.topk_spin)
        form.addRow(" (GeoID):", self.region_combo)
        form.addRow("", self.source_label)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.start_btn)
        layout.addStretch(1)

        self.populate_regions()

        self._worker: Optional[DeepWorkerThread] = None

    def _log(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_widget.append(f"[{stamp}] {message}")

    def set_manual_seeds(self, phrases: list[str]) -> None:
        prepared = [p.strip() for p in phrases if p.strip()]
        with QSignalBlocker(self.seed_text):
            self.seed_text.setPlainText("\n".join(prepared))
        self.seed_edit.clear()
        self._from_preparation = True
        self._update_source_label()
        if prepared:
            self.seed_text.setFocus()

    def _handle_manual_edit(self) -> None:
        if self._from_preparation:
            self._from_preparation = False
        self._update_source_label()



    def _update_source_label(self) -> None:
        manual_count = len([line.strip() for line in self.seed_text.toPlainText().splitlines() if line.strip()])
        if self._from_preparation and manual_count:
            text_value = f"Источник: подготовка ({manual_count})"
        elif self.seed_edit.text().strip():
            text_value = "Источник: файл"
        elif manual_count:
            text_value = f"Источник: ручной ввод ({manual_count})"
        else:
            text_value = "Источник: не выбран"
        self.source_label.setText(text_value)
    def populate_regions(self) -> None:
        self.region_combo.clear()
        self.region_combo.addItem("Регион не выбран", None)
        regions = load_regions()
        for region in regions:
            label = f"{region.name} ({region.id})"
            self.region_combo.addItem(label, region.id)
        default_index = next((i for i, region in enumerate(regions, start=1) if region.id == 225), 0)
        self.region_combo.setCurrentIndex(default_index)

    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбор файла с фразами",
            str(Path.cwd()),
            "Текстовые файлы (*.txt);;Все файлы (*.*)",
        )
        if path:
            self.seed_edit.setText(path)
            with QSignalBlocker(self.seed_text):
                self.seed_text.clear()
            self._from_preparation = False
            self._update_source_label()

    def start_task(self) -> None:
        manual_lines = [line.strip() for line in self.seed_text.toPlainText().splitlines() if line.strip()]
        seed_file = self.seed_edit.text().strip() or None
        if not manual_lines and not seed_file:
            QMessageBox.warning(self, "Нет данных", "Укажите фразы вручную или выберите файл с семенами.")
            return
        try:
            seeds_path = materialize_seeds(manual_lines, seed_file, "deep_manual")
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.warning(self, "Ошибка", str(exc))
            return

        region_data = self.region_combo.currentData()
        region_value = int(region_data) if region_data is not None else None
        params = {
            "depth": self.depth_spin.value(),
            "min_shows": self.min_shows_spin.value(),
            "expand_min": self.expand_min_spin.value(),
            "topk": self.topk_spin.value(),
            "region": region_value,
            "source": "text" if manual_lines else "file",
            "count": len(manual_lines) if manual_lines else 0,
        }
        try:
            task = task_service.enqueue_task(
                account_id=None,
                seed_file=str(seeds_path),
                region=region_value or 0,
                kind="deep",
                params=json.dumps(params, ensure_ascii=False),
            )
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка", f"Не удалось выполнить действие\n{exc}")
            return

        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        log_path = LOGS_DIR / f"deep_{timestamp}.log"
        self._log(f"Парсинг: задача #{task.id} → {len(manual_lines) or 'файл'}")
        self.start_btn.setEnabled(False)
        self._worker = DeepWorkerThread(
            task_id=task.id,
            seeds_file=str(seeds_path),
            depth=self.depth_spin.value(),
            min_shows=self.min_shows_spin.value(),
            expand_min=self.expand_min_spin.value(),
            topk=self.topk_spin.value(),
            region=region_value,
            timestamp=timestamp,
            log_path=log_path,
        )
        self._worker.log_message.connect(self._log)
        self._worker.completed.connect(self._task_completed)
        self._worker.finished.connect(self._on_worker_finished)
        if self.tasks_tab:
            self._worker.refresh_requested.connect(self.tasks_tab.refresh)
        self._worker.start()

    def _process_finished(self, success: bool, message: str) -> None:
        self.start_btn.setEnabled(True)
        self._worker = None
        self._log(message)
        if success:
            QMessageBox.information(self, "Частотность", "Сбор завершён успешно.")
        else:
            QMessageBox.warning(self, "Частотность", message)
        if self.tasks_tab:
            self.tasks_tab.refresh()
        if self.results_tab:
            self.results_tab.refresh()



class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("KeySet — парсер Wordstat")
        self.resize(1100, 700)
        
        # Создаем собственную иконку KeySet (буквы KS на темном фоне)
        from PySide6.QtGui import QPixmap, QIcon, QPainter, QFont, QColor
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("#1e1e1e"))  # Темный фон
        
        painter = QPainter(pixmap)
        painter.setPen(QColor("#4CAF50"))  # Зеленый текст
        painter.setFont(QFont("Arial", 26, QFont.Bold))
        painter.drawText(pixmap.rect(), Qt.AlignCenter, "KS")
        painter.end()
        
        self.setWindowIcon(QIcon(pixmap))

        ensure_schema()
        Base.metadata.create_all(engine)

        self.accounts_tab = AccountsTabExtended()
        self.tasks_tab = TasksTab()
        
        # Создаем большой журнал внизу (из файла 42 + 43)
        from PySide6.QtWidgets import QPlainTextEdit, QToolBar, QTextEdit
        from PySide6.QtGui import QFont, QAction
        
        # ЕДИНЫЙ ЖУРНАЛ ЛОГОВ (файл 45 - объединяем все в один блок)
        # Используем QTextEdit для подсветки логов (файл 44)
        self.log_widget = QTextEdit()  # QTextEdit поддерживает HTML для подсветки
        self.log_widget.setReadOnly(True)
        self.log_widget.setObjectName("jobLog")  # ВАЖНО! Для стиля из файла 44
        self.log_widget.setFont(QFont("Cascadia Mono", 9))  # Шрифт из файла 44
        self.log_widget.setLineWrapMode(QTextEdit.NoWrap)  # Без переносов
        self.log_widget.document().setMaximumBlockCount(10000)  # Лимит строк
        
        # Панель кнопок для журнала
        log_toolbar = QToolBar()
        log_toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        
        clear_action = QAction("🗑 Очистить", self)
        clear_action.triggered.connect(self.log_widget.clear)
        log_toolbar.addAction(clear_action)
        
        copy_action = QAction("📋 Копировать всё", self)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(self.log_widget.toPlainText()))
        log_toolbar.addAction(copy_action)
        
        save_action = QAction("💾 Сохранить", self)
        save_action.triggered.connect(self._save_log)
        log_toolbar.addAction(save_action)
        
        self.pause_log_action = QAction("⏸ Пауза автоскролла", self)
        self.pause_log_action.setCheckable(True)
        log_toolbar.addAction(self.pause_log_action)
        
        # ЕДИНЫЙ контейнер с журналом (файл 45 - убрали дублирование)
        log_container = QWidget()
        log_layout = QVBoxLayout(log_container)
        log_layout.setContentsMargins(8, 8, 8, 8)
        log_layout.setSpacing(8)
        
        # Заголовок секции
        section_title = QLabel("📋 Журнал активности")
        section_title.setStyleSheet("font-size: 14px; color: #1F2937; font-weight: 600;")
        log_layout.addWidget(section_title)
        
        # Панель кнопок
        log_layout.addWidget(log_toolbar)
        
        # ОДИН журнал логов с прокруткой
        log_layout.addWidget(self.log_widget)
        
        # ВАЖНО: минимальная высота чтобы не схлопывался (файл 45)
        log_container.setMinimumHeight(120)
        
        self.results_tab = FrequencyResultsTab()
        self.collect_tab = CollectTab(self.accounts_tab, self.tasks_tab, self.log_widget, self.results_tab)
        self.deep_tab = DeepTab(self.log_widget, self.tasks_tab)
        self.prep_tab = PhrasePrepTab(collect_tab=self.collect_tab, deep_tab=self.deep_tab)

        self.turbo_tab = TurboParserTab()
        self.full_pipeline_tab = FullPipelineTab()
        
        # Новая единая вкладка Парсинг (объединяет Турбо/Частотность/Вглубь)
        self.parsing_tab = ParsingTab()
        
        tabs = QTabWidget()
        tabs.setDocumentMode(False)
        tabs.tabBar().setElideMode(Qt.ElideRight)
        tabs.setMovable(False)
        tabs.setTabsClosable(False)
        tabs.addTab(self.accounts_tab, "Аккаунты")
        tabs.addTab(self.parsing_tab, "📊 Парсинг")  # Новая единая вкладка
        tabs.addTab(self.prep_tab, "Подготовка фраз")
        tabs.addTab(self.turbo_tab, "⚡ Турбо Парсер")
        tabs.addTab(self.full_pipeline_tab, "🚀 Full Pipeline")
        tabs.addTab(self.collect_tab, "Сбор частотности")
        tabs.addTab(self.results_tab, "Результаты частотности")
        tabs.addTab(self.deep_tab, "Парсинг вглубь")
        tabs.addTab(self.tasks_tab, "История задач")

        # Создаем правую панель с ключами
        self.keys_panel = KeysPanel()
        
        # ВЕРТИКАЛЬНЫЙ сплиттер для левой части: вкладки сверху, журнал внизу (файл 42!)
        left_splitter = QSplitter(Qt.Vertical)
        left_splitter.setHandleWidth(6)  # Файл 45: 6px чтобы не ехал на DPI>100%
        left_splitter.addWidget(tabs)
        left_splitter.addWidget(log_container)
        left_splitter.setSizes([500, 150])  # Вкладки больше, журнал меньше
        left_splitter.setStretchFactor(0, 3)  # Вкладки растягиваются больше
        left_splitter.setStretchFactor(1, 1)  # Журнал меньше
        
        # ГОРИЗОНТАЛЬНЫЙ сплиттер: левая часть, справа панель ключей
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setHandleWidth(6)  # Файл 45: 6px чтобы не ехал на DPI>100%
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(self.keys_panel)
        main_splitter.setSizes([700, 300])  # 70% слева, 30% справа
        main_splitter.setStretchFactor(0, 7)
        main_splitter.setStretchFactor(1, 3)
        
        # Сохраняем ссылку для QSettings
        self.main_splitter = main_splitter
        self.left_splitter = left_splitter
        
        # Восстанавливаем позицию сплиттеров из QSettings
        settings = QSettings("KeySet", "KeySet")
        if settings.contains("main_splitter_state"):
            main_splitter.restoreState(settings.value("main_splitter_state"))
        if settings.contains("left_splitter_state"):
            left_splitter.restoreState(settings.value("left_splitter_state"))

        self.setCentralWidget(main_splitter)
        
        # Создаем меню
        self._create_menu()
        
        # Подключаем обновление панели ключей при изменении результатов
        self.results_tab.results_updated.connect(self._update_keys_panel)
        
        # Proxy Manager (немодальное окно)
        self.proxy_manager = None
        
        # Инициализация статуса при загрузке (файл 43)
        self._initialize_status()
        
        # Загружаем тестовые группы для демонстрации (убрать потом)
        self._load_test_groups()
    
    def _create_menu(self):
        """Создает главное меню"""
        menubar = self.menuBar()
        
        # Меню "Инструменты"
        tools_menu = menubar.addMenu("&Инструменты")
        
        # Прокси-менеджер
        proxy_action = tools_menu.addAction("🔌 Прокси-менеджер")
        proxy_action.setShortcut("Ctrl+P")
        proxy_action.triggered.connect(self._open_proxy_manager)
        
        # Переключатель темы (файл 43)
        tools_menu.addSeparator()
        theme_action = tools_menu.addAction("🎨 Переключить тему (Светлая/Темная)")
        theme_action.setShortcut("Ctrl+T")
        theme_action.triggered.connect(self._toggle_theme)
        
        # Загружаем сохраненную тему или используем светлую по умолчанию (файл 43)
        self.settings = QSettings("KeySet", "KeySet")
        self.is_dark_theme = self.settings.value("dark_theme", False, type=bool)
        self._apply_theme(self.is_dark_theme)
        
        tools_menu.addSeparator()
        tools_menu.addAction("⚙️ Настройки").setEnabled(False)  # Пока не реализовано
    
    def closeEvent(self, event):
        """Сохранение состояния сплиттеров при закрытии (файл 42)"""
        settings = QSettings("KeySet", "KeySet")
        settings.setValue("main_splitter_state", self.main_splitter.saveState())
        settings.setValue("left_splitter_state", self.left_splitter.saveState())
        super().closeEvent(event)
    
    def _save_log(self):
        """Сохранить журнал в файл"""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить журнал", "keyset.log", "Log (*.log);;Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.log_widget.toPlainText())
    
    def update_status(self, message: str):
        """Обновить статус в журнале (файл 45 - единый журнал)"""
        self.log_message(message, "INFO")
    
    def log_message(self, message: str, level: str = "INFO"):
        """
        Добавить сообщение в журнал с подсветкой уровня (файл 43)
        
        level: INFO (зеленый), ERROR (красный), WARN (оранжевый), DEBUG (серый)
        """
        from datetime import datetime
        
        # Цвета по уровням (файл 43: дизайн-система Orange Light)
        colors = {
            "INFO": "#16A34A",    # зеленый
            "ERROR": "#DC2626",   # красный
            "WARN": "#F59E0B",    # оранжевый
            "DEBUG": "#64748B",   # серый
        }
        
        color = colors.get(level.upper(), "#0F172A")
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # HTML форматирование для подсветки
        html_message = f'<span style="color: {color}; font-weight: 600;">[{level.upper()}]</span> <span style="color: #475569;">[{timestamp}]</span> {message}'
        
        # Добавляем в лог
        self.log_widget.append(html_message)
        
        # Автоскролл если не на паузе
        if not self.pause_log_action.isChecked():
            scrollbar = self.log_widget.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
    
    def _open_proxy_manager(self):
        """Открыть окно Proxy Manager"""
        from .proxy_manager import ProxyManagerDialog
        
        if self.proxy_manager is None or not self.proxy_manager.isVisible():
            self.proxy_manager = ProxyManagerDialog(self)
            self.proxy_manager.show()
        else:
            # Если окно уже открыто - активируем его
            self.proxy_manager.raise_()
            self.proxy_manager.activateWindow()
    
    def _toggle_theme(self):
        """Переключить тему (файл 43)"""
        self.is_dark_theme = not self.is_dark_theme
        self.settings.setValue("dark_theme", self.is_dark_theme)
        self._apply_theme(self.is_dark_theme)
    
    def _apply_theme(self, is_dark: bool):
        """Применить Beige-Gold Light/Dark дизайн-систему через QSS (файл 43 + 44)"""
        from pathlib import Path
        
        app = QApplication.instance()
        app.setStyle("Fusion")
        
        # Путь к QSS файлам
        styles_dir = Path(__file__).parent.parent / "styles"
        
        # Выбор файла в зависимости от темы (файл 43)
        if is_dark:
            qss_file = styles_dir / "orange_dark.qss"  # Темная тема
        else:
            qss_file = styles_dir / "beige_gold.qss"  # Светлая тема (копия orange_light.qss)
        
        # Загружаем QSS стили
        try:
            if qss_file.exists():
                with open(qss_file, 'r', encoding='utf-8') as f:
                    stylesheet = f.read()
                app.setStyleSheet(stylesheet)
                theme_name = "Dark" if is_dark else "Light"
                print(f"[Theme] Загружена Beige-Gold {theme_name} дизайн-система из {qss_file.name}")
                self.log_message(f"Применена тема: Beige-Gold {theme_name}", "INFO")
            else:
                print(f"[Theme] WARN: QSS файл не найден: {qss_file}")
                print(f"[Theme] Используется Fusion без кастомных стилей")
                self.log_message(f"WARN: QSS файл не найден: {qss_file.name}", "WARN")
        except Exception as e:
            print(f"[Theme] ERROR при загрузке QSS: {e}")
            print(f"[Theme] Используется Fusion без кастомных стилей")
            self.log_message(f"ERROR при загрузке темы: {e}", "ERROR")
    
    def _initialize_status(self):
        """Инициализация статуса при загрузке приложения (файл 43)"""
        try:
            from ..services import accounts as account_service
            accounts = account_service.list_accounts()
            
            # Обновляем статус в оранжевом блоке
            count = len(accounts)
            self.update_status(f"Загружено: {count} аккаунтов")
            
            # Логируем успешный запуск
            self.log_message(f"KeySet запущен, загружено {count} аккаунтов", "INFO")
            self.log_message("Orange Light дизайн-система активна", "INFO")
        except Exception as e:
            self.update_status(f"Ошибка загрузки: {str(e)}")
            self.log_message(f"Ошибка инициализации: {str(e)}", "ERROR")
    
    def _update_keys_panel(self):
        """Обновить панель ключей (группы) из результатов"""
        try:
            from ..services import frequency as frequency_service
            results = frequency_service.list_results(status=None, limit=1000)
            
            # Группируем фразы по группам С ЧАСТОТНОСТЯМИ
            groups = {}
            ungrouped = []
            
            for r in results:
                phrase = r['mask']
                group_name = r.get('group', '') or ''
                freq_total = r.get('freq_total', 0)  # Частотность WS
                
                # Создаем объект с фразой и частотностью
                phrase_data = {
                    'phrase': phrase,
                    'freq_total': freq_total
                }
                
                if group_name:
                    if group_name not in groups:
                        groups[group_name] = []
                    groups[group_name].append(phrase_data)
                else:
                    ungrouped.append(phrase_data)
            
            # Добавляем группу "Без группы" если есть несгруппированные
            if ungrouped:
                groups['Без группы'] = ungrouped
            
            # Загружаем группы в панель
            self.keys_panel.load_groups(groups)
            
            self.log_message(f"Обновлены группы: {len(groups)} групп, всего {len(results)} фраз", "INFO")
        except Exception as e:
            print(f"[ERROR] Ошибка обновления панели ключей: {e}")
            self.log_message(f"Ошибка обновления групп: {e}", "ERROR")
    
    def _load_test_groups(self):
        """Загрузить тестовые группы для демонстрации (временно)"""
        test_groups = {
            "Покупка телефонов": [
                {"phrase": "купить телефон", "freq_total": 125678},
                {"phrase": "купить смартфон", "freq_total": 89234}, 
                {"phrase": "заказать телефон", "freq_total": 12456},
                {"phrase": "телефон цена", "freq_total": 234567},
                {"phrase": "смартфон купить недорого", "freq_total": 4567}
            ],
            "Ремонт телефонов": [
                {"phrase": "ремонт телефона", "freq_total": 56789},
                {"phrase": "починить телефон", "freq_total": 23456},
                {"phrase": "замена экрана телефона", "freq_total": 34567},
                {"phrase": "сервис телефонов", "freq_total": 12345}
            ],
            "Аксессуары": [
                {"phrase": "чехол для телефона", "freq_total": 67890},
                {"phrase": "защитное стекло", "freq_total": 45678},
                {"phrase": "наушники", "freq_total": 234567},
                {"phrase": "зарядка для телефона", "freq_total": 34567}
            ]
        }
        
        self.keys_panel.load_groups(test_groups)
        self.log_message(f"Загружены тестовые группы: {len(test_groups)} групп", "INFO")


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # Применяем темную тему из файла 46
    qss_file = Path(__file__).parent.parent / "styles" / "keyset_dark.qss"
    if qss_file.exists():
        with open(qss_file, 'r', encoding='utf-8') as f:
            app.setStyleSheet(f.read())
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()












