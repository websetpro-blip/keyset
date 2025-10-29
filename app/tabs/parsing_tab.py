# app/tabs/parsing_tab.py
from __future__ import annotations
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QSplitter, QPushButton,
                               QTextEdit, QLabel, QSpinBox, QCheckBox, QComboBox, QTableWidget, 
                               QTableWidgetItem, QProgressBar, QInputDialog, QFileDialog, QApplication)
from PySide6.QtCore import Qt, QThread, Signal, QPoint
from ..widgets.geo_tree import GeoTree
from ..keys_panel import KeysPanel  # Используем существующий KeysPanel
from ..widgets.add_actions_popup import AddActionsPopup
import time


def _to_int0(value):
    """Convert value to int, return 0 for empty/None values"""
    if value is None or value == '' or value == '-':
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


class ParsingWorker(QThread):
    """Воркер для парсинга в отдельном потоке"""
    tick = Signal(dict)      # события для UI
    done = Signal(list)      # финальный результат
    
    def __init__(self, phrases: list[str], modes: dict, depth_cfg: dict, geo_ids: list[int], parent=None):
        super().__init__(parent)
        self.phrases = phrases
        self.modes = modes
        self.depth_cfg = depth_cfg
        self.geo_ids = geo_ids
        self._stop = False
    
    def stop(self):
        self._stop = True
    
    def run(self):
        """Основной цикл парсинга"""
        # Здесь вызываем существующие сервисы
        try:
            from ...services import frequency as freq_service
        except ImportError:
            # Фоллбэк для тестирования
            freq_service = None
        
        rows = []
        total = len(self.phrases)
        
        for i, phrase in enumerate(self.phrases, start=1):
            if self._stop:
                break
            
            rec = {"phrase": phrase}
            
            # Собираем частотности
            if freq_service:
                if self.modes.get("ws"):
                    # Базовая частотность
                    try:
                        result = freq_service.parse_frequency([phrase], self.geo_ids[0] if self.geo_ids else 225)
                        rec["ws"] = _to_int0(result[0].get("freq_total", 0) if result else 0)
                    except Exception:
                        rec["ws"] = 0
                
                if self.modes.get("qws"):
                    # В кавычках
                    try:
                        result = freq_service.parse_frequency([f'"{phrase}"'], self.geo_ids[0] if self.geo_ids else 225)
                        rec["qws"] = _to_int0(result[0].get("freq_quotes", 0) if result else 0)
                    except Exception:
                        rec["qws"] = 0
                
                if self.modes.get("bws"):
                    # Точная
                    try:
                        words = phrase.split()
                        exact_phrase = " ".join([f"!{w}" for w in words])
                        result = freq_service.parse_frequency([exact_phrase], self.geo_ids[0] if self.geo_ids else 225)
                        rec["bws"] = _to_int0(result[0].get("freq_exact", 0) if result else 0)
                    except Exception:
                        rec["bws"] = 0
            else:
                # Мок-данные для тестирования
                import random
                if self.modes.get("ws"): rec["ws"] = random.randint(100, 10000)
                if self.modes.get("qws"): rec["qws"] = random.randint(50, 5000)
                if self.modes.get("bws"): rec["bws"] = random.randint(10, 1000)
            
            self.tick.emit({"type": "freq", "phrase": phrase, "i": i, "n": total, "progress": int(i/total*100)})
            
            # Парсинг вглубь
            if self.depth_cfg.get("enabled"):
                # TODO: реализовать парсинг вглубь
                pass
            
            rec["status"] = "OK"
            rows.append(rec)
        
        self.done.emit(rows)

class ParsingTab(QWidget):
    """Единая вкладка Парсинг - объединяет Турбо/Частотность/Вглубь"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Главный сплиттер
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(6)
        
        # ---- LEFT: параметры ----
        left = QWidget()
        left_layout = QVBoxLayout(left)
        
        # Режимы частотности
        gb_modes = QGroupBox("Режимы частотности (Wordstat)")
        self.c_ws = QCheckBox("WS (базовая)")
        self.c_ws.setChecked(True)
        self.c_qws = QCheckBox('"WS" (в кавычках)')
        self.c_bws = QCheckBox("!WS (точная)")
        modes_layout = QVBoxLayout(gb_modes)
        modes_layout.addWidget(self.c_ws)
        modes_layout.addWidget(self.c_qws)
        modes_layout.addWidget(self.c_bws)
        
        # Парсинг вглубь
        gb_depth = QGroupBox("Парсинг вглубь")
        self.ch_depth = QCheckBox("Включить парсинг вглубь")
        self.sb_pages = QSpinBox()
        self.sb_pages.setRange(1, 40)
        self.sb_pages.setValue(20)
        self.ch_left = QCheckBox("Левая колонка")
        self.ch_left.setChecked(True)
        self.ch_right = QCheckBox("Правая колонка")
        depth_layout = QVBoxLayout(gb_depth)
        depth_layout.addWidget(self.ch_depth)
        depth_layout.addWidget(QLabel("Страниц:"))
        depth_layout.addWidget(self.sb_pages)
        depth_layout.addWidget(self.ch_left)
        depth_layout.addWidget(self.ch_right)
        
        # Регионы
        gb_geo = QGroupBox("Регионы (дерево)")
        self.geo = GeoTree()
        geo_layout = QVBoxLayout(gb_geo)
        geo_layout.addWidget(self.geo)
        
        # Аккаунт
        gb_acc = QGroupBox("Аккаунт / профиль")
        self.acc = QComboBox()
        self.acc.addItems(["Текущий", "Все по очереди"])
        acc_layout = QVBoxLayout(gb_acc)
        acc_layout.addWidget(self.acc)
        
        left_layout.addWidget(gb_modes)
        left_layout.addWidget(gb_depth)
        left_layout.addWidget(gb_geo, 1)
        left_layout.addWidget(gb_acc)
        
        # ---- CENTER: фразы + результаты ----
        center = QWidget()
        center_layout = QVBoxLayout(center)
        
        # Ввод фраз
        self.phrases_edit = QTextEdit()
        self.phrases_edit.setPlaceholderText("Вставьте ключевые фразы (по одной на строку)...")
        self.phrases_edit.setMaximumHeight(150)
        
        # Кнопки
        buttons = QHBoxLayout()
        
        # Add button with popup (like Frequency button)
        self.btn_add = QPushButton("Добавить")
        self.btn_add.clicked.connect(self._open_add_popup)
        buttons.addWidget(self.btn_add)
        
        self.btn_run = QPushButton("▶ ЗАПУСТИТЬ ПАРСИНГ")
        self.btn_stop = QPushButton("■ ОСТАНОВИТЬ")
        self.btn_stop.setEnabled(False)
        self.btn_export = QPushButton("💾 Экспорт в CSV")
        buttons.addWidget(self.btn_run)
        buttons.addWidget(self.btn_stop)
        buttons.addWidget(self.btn_export)
        buttons.addStretch()
        
        # Прогресс
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        
        # Таблица результатов
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Фраза", "WS", '"WS"', "!WS", "Статус", "Время", "Действия"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        
        center_layout.addWidget(QLabel("Ключевые фразы для парсинга:"))
        center_layout.addWidget(self.phrases_edit)
        center_layout.addLayout(buttons)
        center_layout.addWidget(self.progress)
        center_layout.addWidget(QLabel("Результаты:"))
        center_layout.addWidget(self.table, 1)
        
        # ---- RIGHT: панель ключей/групп ----
        self.right_panel = KeysPanel()
        
        # Собираем все вместе
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(self.right_panel)
        splitter.setStretchFactor(0, 0)  # Левая панель фиксированная
        splitter.setStretchFactor(1, 3)  # Центр растягивается
        splitter.setStretchFactor(2, 2)  # Правая панель средняя
        
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        
        # Подключаем обработчики
        self._worker = None
        self.btn_run.clicked.connect(self.on_run)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_export.clicked.connect(self.on_export)
    
    def on_run(self):
        """Запустить парсинг"""
        phrases = [p.strip() for p in self.phrases_edit.toPlainText().splitlines() if p.strip()]
        if not phrases:
            return
        
        modes = {
            "ws": self.c_ws.isChecked(),
            "qws": self.c_qws.isChecked(),
            "bws": self.c_bws.isChecked()
        }
        
        depth_cfg = {
            "enabled": self.ch_depth.isChecked(),
            "pages": self.sb_pages.value(),
            "left": self.ch_left.isChecked(),
            "right": self.ch_right.isChecked()
        }
        
        geo_ids = self.geo.selected_geo_ids()
        
        # UI
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.table.setRowCount(0)
        
        # Запускаем воркер
        self._worker = ParsingWorker(phrases, modes, depth_cfg, geo_ids, self)
        self._worker.tick.connect(self.on_tick)
        self._worker.done.connect(self.on_done)
        self._worker.start()
    
    def on_stop(self):
        """Остановить парсинг"""
        if self._worker:
            self._worker.stop()
            self._worker = None
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
    
    def on_tick(self, event):
        """Обновление прогресса"""
        if event.get("type") == "freq":
            self.progress.setValue(event.get("progress", 0))
    
    def on_done(self, rows):
        """Парсинг завершен"""
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress.setVisible(False)
        
        # Заполняем таблицу
        self.table.setRowCount(0)
        for row in rows:
            i = self.table.rowCount()
            self.table.insertRow(i)
            
            values = [
                row["phrase"],
                str(_to_int0(row.get("ws", 0))),
                str(_to_int0(row.get("qws", 0))),
                str(_to_int0(row.get("bws", 0))),
                row.get("status", ""),
                time.strftime("%H:%M:%S"),
                "➜"  # Кнопка действий
            ]
            
            for j, val in enumerate(values):
                item = QTableWidgetItem(str(val))
                # Right align numeric columns
                if j in (1, 2, 3):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(i, j, item)
        
        # Обновляем правую панель - добавляем фразы в группы
        # Группируем по первому слову для демонстрации
        from collections import defaultdict
        groups_data = defaultdict(list)
        
        for r in rows:
            phrase = r["phrase"]
            # Определяем группу по первому слову
            first_word = phrase.split()[0] if phrase else "Прочее"
            groups_data[first_word].append({
                "phrase": phrase,
                "freq": _to_int0(r.get("ws", 0)),
                "freq_quotes": _to_int0(r.get("qws", 0)),
                "freq_exact": _to_int0(r.get("bws", 0))
            })
        
        # Конвертируем в формат для KeysPanel
        self.right_panel.update_groups(groups_data)
    
    def on_export(self):
        """Экспорт в CSV"""
        import csv
        
        filename, _ = QFileDialog.getSaveFileName(self, "Экспорт в CSV", "", "CSV Files (*.csv)")
        if not filename:
            return
        
        rows = []
        for i in range(self.table.rowCount()):
            row = []
            for j in range(self.table.columnCount() - 1):  # Без колонки действий
                item = self.table.item(i, j)
                value = item.text() if item else ""
                # Convert numeric columns to 0 if empty
                if j in (1, 2, 3):  # WS, "WS", !WS columns
                    value = str(_to_int0(value))
                row.append(value)
            rows.append(row)
        
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            writer.writerow(["Фраза", "WS", '"WS"', "!WS", "Статус", "Время"])
            writer.writerows(rows)
    
    def _open_add_popup(self):
        """Open popup panel below Add button"""
        popup = AddActionsPopup(self)
        pos = self.btn_add.mapToGlobal(QPoint(0, self.btn_add.height()))
        popup.move(pos)
        popup.show()
    
    def on_add_phrases_dialog(self):
        """Add phrases via dialog"""
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Добавить фразы",
            "Введите фразы (по одной на строку):",
            self.phrases_edit.toPlainText()
        )
        if ok:
            self.phrases_edit.setPlainText(text)
    
    def on_load_from_file(self):
        """Load phrases from file"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Загрузить фразы из файла",
            "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        if filename:
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.phrases_edit.setPlainText(content)
            except Exception as e:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить файл:\n{str(e)}")
    
    def on_import_from_clipboard(self):
        """Import phrases from clipboard"""
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            self.phrases_edit.setPlainText(text)
    
    def on_clear_table(self):
        """Clear the results table"""
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self,
            "Очистить таблицу",
            "Вы уверены, что хотите очистить таблицу результатов?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.table.setRowCount(0)
