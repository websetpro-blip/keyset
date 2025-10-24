from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QProcess
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QProgressBar,
)


CONFIG_PATH = Path("yandex/configs/accounts.json")
PARSER_SCRIPT = Path("yandex/multi_account_parser.py")


def load_account_logins(config_path: Path) -> List[str]:
    if not config_path.exists():
        return []
    with config_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        return []
    logins: List[str] = []
    for entry in data:
        login = entry.get("login")
        if login:
            logins.append(login)
    return logins


class ParsingTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._process: Optional[QProcess] = None
        self._total_accounts: int = 0

        self._accounts_list = QListWidget()
        self._accounts_list.setSelectionMode(QListWidget.MultiSelection)
        for login in load_account_logins(CONFIG_PATH):
            item = QListWidgetItem(login)
            self._accounts_list.addItem(item)

        self._phrases_label = QLabel("Файл с фразами: не выбран")
        self._select_phrases_btn = QPushButton("Выбрать файл...")
        self._select_phrases_btn.clicked.connect(self._select_phrases_file)

        self._concurrency_slider = QSlider(Qt.Horizontal)
        self._concurrency_slider.setMinimum(1)
        self._concurrency_slider.setMaximum(10)
        self._concurrency_slider.setValue(5)
        self._concurrency_slider.valueChanged.connect(self._update_concurrency_label)
        self._concurrency_value = QLabel("5")

        self._delay_slider = QSlider(Qt.Horizontal)
        self._delay_slider.setMinimum(1)   # десятые доли секунды
        self._delay_slider.setMaximum(30)  # 0.1 .. 3.0
        self._delay_slider.setValue(3)     # 0.3 s по умолчанию
        self._delay_slider.valueChanged.connect(self._update_delay_label)
        self._delay_value = QLabel("0.3 s")

        self._run_button = QPushButton("Старт парсинга")
        self._run_button.clicked.connect(self._start_parsing)
        self._stop_button = QPushButton("Остановить")
        self._stop_button.setEnabled(False)
        self._stop_button.clicked.connect(self._stop_parsing)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._summary_label = QLabel("")

        self._log_output = QTextEdit()
        self._log_output.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addWidget(self._build_accounts_group())
        layout.addWidget(self._build_settings_group())
        layout.addWidget(self._build_controls_group())
        layout.addWidget(self._summary_label)
        layout.addWidget(self._log_output)
        self.setLayout(layout)

        self._phrases_path: Optional[Path] = None
        if DEFAULT := Path("yandex/test_50.txt"):
            if DEFAULT.exists():
                self._phrases_path = DEFAULT.resolve()
                self._phrases_label.setText(f"Файл с фразами: {self._phrases_path}")

    def _build_accounts_group(self) -> QGroupBox:
        group = QGroupBox("Аккаунты")
        wrapper = QVBoxLayout()
        wrapper.addWidget(QLabel("Выберите аккаунты для запуска:"))
        wrapper.addWidget(self._accounts_list)
        group.setLayout(wrapper)
        return group

    def _build_settings_group(self) -> QGroupBox:
        group = QGroupBox("Настройки")
        grid = QGridLayout()

        grid.addWidget(self._phrases_label, 0, 0, 1, 2)
        grid.addWidget(self._select_phrases_btn, 0, 2)

        grid.addWidget(QLabel("Concurrency:"), 1, 0)
        grid.addWidget(self._concurrency_slider, 1, 1)
        grid.addWidget(self._concurrency_value, 1, 2)

        grid.addWidget(QLabel("Delay (сек):"), 2, 0)
        grid.addWidget(self._delay_slider, 2, 1)
        grid.addWidget(self._delay_value, 2, 2)

        group.setLayout(grid)
        return group

    def _build_controls_group(self) -> QGroupBox:
        group = QGroupBox("Управление")
        layout = QVBoxLayout()
        buttons = QHBoxLayout()
        buttons.addWidget(self._run_button)
        buttons.addWidget(self._stop_button)
        layout.addLayout(buttons)
        layout.addWidget(self._progress_bar)
        group.setLayout(layout)
        return group

    def _update_concurrency_label(self, value: int) -> None:
        self._concurrency_value.setText(str(value))

    def _update_delay_label(self, slider_value: int) -> None:
        delay = slider_value / 10.0
        self._delay_value.setText(f"{delay:.1f} s")

    def _select_phrases_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выбор файла с фразами",
            str(Path.cwd()),
            "Text files (*.txt);;All files (*)",
        )
        if path:
            self._phrases_path = Path(path).resolve()
            self._phrases_label.setText(f"Файл с фразами: {self._phrases_path}")

    def _start_parsing(self) -> None:
        if self._process is not None:
            return

        selected = [item.text() for item in self._accounts_list.selectedItems()]
        if not selected:
            self._append_log("Выберите хотя бы один аккаунт.")
            return

        if self._phrases_path is None:
            self._append_log("Выберите файл с фразами.")
            return

        cmd = [
            sys.executable,
            "-u",
            str(PARSER_SCRIPT),
            "--phrases",
            str(self._phrases_path),
            "--concurrency",
            str(self._concurrency_slider.value()),
            "--extra",
            "--delay",
            str(self._delay_slider.value() / 10.0),
        ]

        cmd.extend(["--logins", *selected])

        self._append_log(f"Запускаю: {' '.join(cmd)}")
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._handle_output)
        self._process.finished.connect(self._handle_finished)
        self._process.start(cmd[0], cmd[1:])

        self._run_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._progress_bar.setValue(0)
        self._summary_label.setText("")
        self._total_accounts = len(selected)

    def _stop_parsing(self) -> None:
        if self._process is not None:
            self._append_log("Останавливаю парсинг...")
            self._process.terminate()

    def _handle_output(self) -> None:
        if self._process is None:
            return
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            self._append_log(line)
            if line.startswith("[") and "] ▸ " in line:
                if "▸ OK" in line:
                    self._increment_progress()

    def _handle_finished(self, exit_code: int, exit_status) -> None:  # pylint: disable=unused-argument
        status = "успешно" if exit_code == 0 else f"с ошибкой (код {exit_code})"
        self._append_log(f"Парсинг завершён {status}.")
        self._process = None
        self._run_button.setEnabled(True)
        self._stop_button.setEnabled(False)

    def _increment_progress(self) -> None:
        if self._total_accounts <= 0:
            return
        current = self._progress_bar.value()
        step = int(100 / max(1, self._total_accounts))
        new_value = min(100, current + step)
        self._progress_bar.setValue(new_value)

    def _append_log(self, text: str) -> None:
        self._log_output.append(text)
        self._log_output.ensureCursorVisible()
