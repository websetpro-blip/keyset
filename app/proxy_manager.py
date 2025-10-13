"""
Proxy Manager - массовая загрузка и проверка прокси (как в Key Collector)
Интегрирован с ProxyStore и аккаунтами
"""

from PySide6 import QtWidgets, QtCore, QtGui
from PySide6.QtCore import QThread, Signal
import asyncio
import aiohttp
import time
from datetime import datetime
from typing import List, Dict

try:
    from aiohttp_socks import ProxyConnector
except ImportError:
    ProxyConnector = None

try:
    from ..core import proxy_store
except ImportError:
    # Если запускается отдельно
    import sys
    sys.path.insert(0, "C:/AI/yandex/semtool")
    from core import proxy_store

from ..services import accounts as account_service


async def check_http_proxy(px: Dict, timeout: float = 5.0) -> tuple:
    """Проверка HTTP/HTTPS прокси (без ssl:default ошибок)"""
    t0 = time.perf_counter()
    timeout_obj = aiohttp.ClientTimeout(total=timeout)
    
    try:
        async with aiohttp.ClientSession(timeout=timeout_obj) as session:
            proxy_auth = None
            if px.get("login"):
                proxy_auth = aiohttp.BasicAuth(px["login"], px.get("password", ""))
            
            # httpbin по http, ssl=False - избегаем ssl:default
            async with session.get(
                "http://httpbin.org/ip",
                proxy=px["server"],
                proxy_auth=proxy_auth,
                ssl=False
            ) as response:
                await response.text()
        
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return ("OK", elapsed_ms, "")
    
    except asyncio.TimeoutError:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return ("TIMEOUT", elapsed_ms, "Превышен таймаут")
    
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return ("FAIL", elapsed_ms, str(e)[:120])


async def check_socks_proxy(px: Dict, timeout: float = 5.0) -> tuple:
    """Проверка SOCKS прокси"""
    if ProxyConnector is None:
        return ("ERR", None, "aiohttp_socks не установлен")
    
    t0 = time.perf_counter()
    
    try:
        conn = ProxyConnector.from_url(
            px["server"],
            rdns=True,
            username=px.get("login") or None,
            password=px.get("password") or None
        )
        
        timeout_obj = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(connector=conn, timeout=timeout_obj) as session:
            async with session.get("http://httpbin.org/ip") as response:
                await response.text()
        
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return ("OK", elapsed_ms, "")
    
    except asyncio.TimeoutError:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return ("TIMEOUT", elapsed_ms, "Превышен таймаут")
    
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return ("FAIL", elapsed_ms, str(e)[:120])


async def check_one_proxy(px: Dict, timeout: float = 5.0) -> tuple:
    """Проверяет один прокси"""
    try:
        if px["scheme"].startswith("socks"):
            return await check_socks_proxy(px, timeout)
        else:
            return await check_http_proxy(px, timeout)
    except Exception as e:
        return ("FAIL", None, str(e)[:120])


class ProxyCheckThread(QThread):
    """Поток для проверки прокси через asyncio"""
    
    progress = Signal(int, str, int, str)  # proxy_id, status, latency, error
    finished = Signal()
    
    def __init__(self, proxies: List[Dict], timeout: float = 5.0):
        super().__init__()
        self.proxies = proxies
        self.timeout = timeout
        self._stop = False
    
    def stop(self):
        self._stop = True
    
    def run(self):
        """Запускает asyncio event loop в потоке"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._check_all())
        finally:
            loop.close()
            self.finished.emit()
    
    async def _check_all(self):
        """Проверяет все прокси параллельно"""
        sem = asyncio.Semaphore(40)  # 40 параллельных проверок
        
        async def check_one(px):
            if self._stop:
                return
            
            async with sem:
                status, latency, error = await check_one_proxy(px, self.timeout)
                self.progress.emit(px['id'], status, latency or 0, error)
                
                # Обновляем статус в ProxyStore
                proxy_store.update_proxy_status(px['id'], status, latency, error)
        
        tasks = [check_one(px) for px in self.proxies]
        await asyncio.gather(*tasks, return_exceptions=True)


class ProxyManagerDialog(QtWidgets.QDialog):
    """Окно управления прокси (как в Key Collector)"""
    
    BASE_COLUMNS = ["ID", "Proxy", "Тип", "Логин", "Статус", "Пинг (мс)"]
    TAIL_COLUMNS = ["Ошибка", "Проверено"]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔌 Прокси-менеджер")
        self.setModal(False)  # ВАЖНО: немодальное окно
        self.resize(1400, 650)
        
        self._proxies: List[Dict] = []
        self._check_thread = None
        self._accounts_map = {}  # {proxy_raw: [account_names]}
        self._accounts_list = []  # Список аккаунтов для динамических столбцов
        self._account_columns = []  # Список имен аккаунтов для столбцов
        
        # ВАЖНО: Загружаем аккаунты ПЕРЕД созданием UI (для динамических столбцов)
        self._load_accounts_info()
        
        self._create_ui()
        self._load_from_store()
        
        # Если ProxyStore пустой - автоматически синхронизируем с аккаунтами
        if not self._proxies:
            added = proxy_store.sync_from_accounts()
            if added > 0:
                self._load_from_store()
                print(f"[Proxy Manager] Автоматически синхронизировано {added} прокси из аккаунтов")
        
        # ВАЖНО: загружаем привязку и обновляем таблицу ПОСЛЕ загрузки прокси
        self._load_accounts_map()
    
    def _load_accounts_info(self):
        """Загружает список аккаунтов для динамических столбцов"""
        accounts = account_service.list_accounts()
        self._accounts_list = [acc for acc in accounts if acc.name not in ["demo_account", "wordstat_main"]]
        self._account_columns = [acc.name for acc in self._accounts_list]
    
    def _create_ui(self):
        """Создает интерфейс с динамическими столбцами аккаунтов"""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Кнопки управления
        buttons_layout = QtWidgets.QHBoxLayout()
        
        self.btn_paste = QtWidgets.QPushButton("📋 Вставить из буфера")
        self.btn_load_file = QtWidgets.QPushButton("📁 Загрузить .txt")
        self.btn_sync = QtWidgets.QPushButton("🔄 Синхронизировать с аккаунтами")
        self.btn_check_all = QtWidgets.QPushButton("✅ Проверить все")
        self.btn_stop = QtWidgets.QPushButton("⛔ Остановить")
        self.btn_apply = QtWidgets.QPushButton("💾 Применить к аккаунтам")
        self.btn_auto_distribute = QtWidgets.QPushButton("⚡ Автораспределение")
        self.btn_export = QtWidgets.QPushButton("📤 Экспорт OK")
        self.btn_clear = QtWidgets.QPushButton("🗑 Очистить")
        self.btn_close = QtWidgets.QPushButton("❌ Закрыть")
        
        self.btn_stop.setEnabled(False)
        
        buttons_layout.addWidget(self.btn_paste)
        buttons_layout.addWidget(self.btn_load_file)
        buttons_layout.addWidget(self.btn_sync)
        buttons_layout.addWidget(self.btn_check_all)
        buttons_layout.addWidget(self.btn_stop)
        buttons_layout.addWidget(self.btn_apply)
        buttons_layout.addWidget(self.btn_auto_distribute)
        buttons_layout.addWidget(self.btn_export)
        buttons_layout.addWidget(self.btn_clear)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.btn_close)
        
        layout.addLayout(buttons_layout)
        
        # Настройки
        settings_layout = QtWidgets.QHBoxLayout()
        settings_layout.addWidget(QtWidgets.QLabel("Потоков:"))
        
        self.spin_threads = QtWidgets.QSpinBox()
        self.spin_threads.setRange(1, 100)
        self.spin_threads.setValue(40)
        settings_layout.addWidget(self.spin_threads)
        
        settings_layout.addWidget(QtWidgets.QLabel("Таймаут (сек):"))
        
        self.spin_timeout = QtWidgets.QSpinBox()
        self.spin_timeout.setRange(1, 60)
        self.spin_timeout.setValue(5)
        settings_layout.addWidget(self.spin_timeout)
        
        settings_layout.addStretch()
        
        self.lbl_stats = QtWidgets.QLabel("Всего: 0 | OK: 0 | FAIL: 0")
        settings_layout.addWidget(self.lbl_stats)
        
        layout.addLayout(settings_layout)
        
        # ДИНАМИЧЕСКИЕ СТОЛБЦЫ: BASE + АККАУНТЫ + TAIL
        all_columns = self.BASE_COLUMNS + self._account_columns + self.TAIL_COLUMNS
        
        # Таблица с динамическими столбцами
        self.table = QtWidgets.QTableWidget(0, len(all_columns))
        self.table.setHorizontalHeaderLabels(all_columns)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        self.table.setAlternatingRowColors(True)
        
        # ВАЖНО: Запрет редактирования (как в Кей-Коллекторе)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        
        # Настройка отображения текста
        self.table.setTextElideMode(QtCore.Qt.ElideRight)
        self.table.setWordWrap(False)
        
        header = self.table.horizontalHeader()
        
        # Настройка ширины столбцов
        # BASE: ID, Proxy, Тип, Логин, Статус, Пинг
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)  # ID
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)  # Proxy
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.Interactive)  # Тип
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.Interactive)  # Логин
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.Interactive)  # Статус
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.Interactive)  # Пинг
        
        # АККАУНТЫ: автоширина по содержимому (✓ или пусто)
        base_col_count = len(self.BASE_COLUMNS)
        for i in range(len(self._account_columns)):
            col_idx = base_col_count + i
            header.setSectionResizeMode(col_idx, QtWidgets.QHeaderView.ResizeToContents)
        
        # TAIL: Ошибка (последняя - растягивается)
        tail_start = base_col_count + len(self._account_columns)
        for i in range(len(self.TAIL_COLUMNS) - 1):
            header.setSectionResizeMode(tail_start + i, QtWidgets.QHeaderView.Interactive)
        
        header.setStretchLastSection(True)  # Последняя колонка растягивается
        
        # Добавляем таблицу
        layout.addWidget(self.table)
        
        # ВАЖНО: Скрываем колонку "Логин" (как в файле 43 - не показываем логины прокси)
        # Логин доступен в tooltip при наведении на Proxy
        self.table.setColumnHidden(3, True)
        
        # Подключаем сигналы
        self.btn_paste.clicked.connect(self._on_paste)
        self.btn_load_file.clicked.connect(self._on_load_file)
        self.btn_sync.clicked.connect(self._on_sync_accounts)
        self.btn_check_all.clicked.connect(self._on_check_all)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_apply.clicked.connect(self._on_apply_to_accounts)
        self.btn_auto_distribute.clicked.connect(self._on_auto_distribute)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_close.clicked.connect(self.close)
    
    def _load_from_store(self):
        """Загружает прокси из ProxyStore (БЕЗ обновления таблицы)"""
        try:
            self._proxies = proxy_store.get_all_proxies()
        except Exception as e:
            print(f"[ERROR] Не удалось загрузить прокси из store: {e}")
            self._proxies = []
    
    def _load_accounts_map(self):
        """Загружает привязку прокси к аккаунтам"""
        self._accounts_map = {}
        
        # Обновляем список аккаунтов
        accounts = account_service.list_accounts()
        self._accounts_list = [acc for acc in accounts if acc.name not in ["demo_account", "wordstat_main"]]
        
        for acc in self._accounts_list:
            if acc.proxy:
                if acc.proxy not in self._accounts_map:
                    self._accounts_map[acc.proxy] = []
                self._accounts_map[acc.proxy].append(acc.name)
        
        # Обновляем таблицу
        self._refresh_table()
    
    def _refresh_table(self):
        """Обновляет таблицу с динамическими столбцами аккаунтов"""
        self.table.setRowCount(len(self._proxies))
        
        base_col_count = len(self.BASE_COLUMNS)
        account_col_count = len(self._account_columns)
        
        for row, px in enumerate(self._proxies):
            # BASE COLUMNS
            col = 0
            
            # ID
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(str(px['id'])))
            col += 1
            
            # Proxy с тултипом
            proxy_item = QtWidgets.QTableWidgetItem(px['raw'])
            proxy_item.setToolTip(px['raw'])
            self.table.setItem(row, col, proxy_item)
            col += 1
            
            # Тип
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(px['scheme'].upper()))
            col += 1
            
            # Логин
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(px['login'] or ""))
            col += 1
            
            # Статус
            status = px['last_status'] or "WAIT"
            status_item = QtWidgets.QTableWidgetItem(status)
            status_item.setTextAlignment(QtCore.Qt.AlignCenter)
            
            if status == "OK":
                status_item.setForeground(QtGui.QBrush(QtGui.QColor("#4CAF50")))
            elif status in ("FAIL", "TIMEOUT", "ERR"):
                status_item.setForeground(QtGui.QBrush(QtGui.QColor("#F44336")))
            
            self.table.setItem(row, col, status_item)
            col += 1
            
            # Пинг
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(str(px['latency_ms'] or "")))
            col += 1
            
            # ДИНАМИЧЕСКИЕ СТОЛБЦЫ АККАУНТОВ (✓ если назначен)
            accounts_using = self._accounts_map.get(px['raw'], [])
            
            for acc_name in self._account_columns:
                check_item = QtWidgets.QTableWidgetItem()
                check_item.setTextAlignment(QtCore.Qt.AlignCenter)
                
                if acc_name in accounts_using:
                    check_item.setText("✓")
                    check_item.setForeground(QtGui.QBrush(QtGui.QColor("#4CAF50")))  # Зеленая галочка
                else:
                    check_item.setText("")
                
                check_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                self.table.setItem(row, col, check_item)
                col += 1
            
            # TAIL COLUMNS: Ошибка, Проверено
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(px['last_error'] or ""))
            col += 1
            
            checked_at = ""
            if px['last_check']:
                checked_at = px['last_check'].strftime("%Y-%m-%d %H:%M:%S") if isinstance(px['last_check'], datetime) else str(px['last_check'])
            
            self.table.setItem(row, col, QtWidgets.QTableWidgetItem(checked_at))
        
        self._update_stats()
    
    def _on_paste(self):
        """Вставить из буфера"""
        text = QtWidgets.QApplication.clipboard().text()
        added = 0
        
        for line in text.splitlines():
            proxy = proxy_store.add_proxy(line)
            if proxy:
                added += 1
        
        self._load_from_store()
        self._load_accounts_map()
        
        QtWidgets.QMessageBox.information(
            self,
            "Добавлено",
            f"Добавлено прокси: {added}"
        )
    
    def _on_load_file(self):
        """Загрузить из файла"""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Выбрать файл с прокси",
            "",
            "Text Files (*.txt);;All Files (*.*)"
        )
        
        if not path:
            return
        
        added = 0
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    proxy = proxy_store.add_proxy(line.strip())
                    if proxy:
                        added += 1
            
            self._load_from_store()
            self._load_accounts_map()
            
            QtWidgets.QMessageBox.information(
                self,
                "Загружено",
                f"Загружено прокси: {added}"
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                "Ошибка",
                f"Не удалось загрузить файл:\n{e}"
            )
    
    def _on_sync_accounts(self):
        """Синхронизировать прокси из аккаунтов"""
        added = proxy_store.sync_from_accounts()
        self._load_from_store()
        self._load_accounts_map()  # Обновляем привязку
        
        QtWidgets.QMessageBox.information(
            self,
            "Синхронизация",
            f"Добавлено прокси из аккаунтов: {added}"
        )
    
    def _on_check_all(self):
        """Проверить все прокси"""
        if not self._proxies:
            QtWidgets.QMessageBox.warning(
                self,
                "Нет прокси",
                "Добавьте прокси для проверки"
            )
            return
        
        self.btn_check_all.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        # Запускаем проверку в QThread
        timeout = self.spin_timeout.value()
        self._check_thread = ProxyCheckThread(self._proxies, timeout)
        self._check_thread.progress.connect(self._on_check_progress)
        self._check_thread.finished.connect(self._on_check_finished)
        self._check_thread.start()
    
    def _on_check_progress(self, proxy_id: int, status: str, latency: int, error: str):
        """Обновление прогресса проверки"""
        # Находим строку с proxy_id
        for row in range(self.table.rowCount()):
            if int(self.table.item(row, 0).text()) == proxy_id:
                # Обновляем статус
                status_item = QtWidgets.QTableWidgetItem(status)
                status_item.setTextAlignment(QtCore.Qt.AlignCenter)
                
                if status == "OK":
                    status_item.setBackground(QtGui.QColor("#d4edda"))
                elif status in ("FAIL", "TIMEOUT", "ERR"):
                    status_item.setBackground(QtGui.QColor("#f8d7da"))
                
                self.table.setItem(row, 4, status_item)
                self.table.setItem(row, 5, QtWidgets.QTableWidgetItem(str(latency) if latency else ""))
                # row 6 - "Используется" - не трогаем
                self.table.setItem(row, 7, QtWidgets.QTableWidgetItem(error))
                self.table.setItem(row, 8, QtWidgets.QTableWidgetItem(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
                break
        
        self._update_stats()
    
    def _on_check_finished(self):
        """Проверка завершена"""
        self.btn_check_all.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self._load_from_store()
        self._load_accounts_map()  # Перезагружаем из БД с привязкой
    
    def _on_stop(self):
        """Остановить проверку"""
        if self._check_thread:
            self._check_thread.stop()
        
        self.btn_check_all.setEnabled(True)
        self.btn_stop.setEnabled(False)
    
    def _on_apply_to_accounts(self):
        """Применить прокси к аккаунтам"""
        # Получаем выбранные строки
        selected_rows = set(item.row() for item in self.table.selectedItems())
        
        if not selected_rows:
            QtWidgets.QMessageBox.warning(
                self,
                "Не выбрано",
                "Выберите прокси для применения"
            )
            return
        
        selected_proxies = [self._proxies[row] for row in selected_rows]
        
        # Диалог выбора аккаунтов
        accounts = account_service.list_accounts()
        account_names = [acc.name for acc in accounts if acc.name not in ["demo_account", "wordstat_main"]]
        
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Применить к аккаунтам")
        dialog.resize(400, 300)
        
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel(f"Выбрано прокси: {len(selected_proxies)}"))
        layout.addWidget(QtWidgets.QLabel("Выберите аккаунты:"))
        
        list_widget = QtWidgets.QListWidget()
        list_widget.setSelectionMode(QtWidgets.QAbstractItemView.MultiSelection)
        for name in account_names:
            list_widget.addItem(name)
        layout.addWidget(list_widget)
        
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            selected_account_names = [item.text() for item in list_widget.selectedItems()]
            
            if not selected_account_names:
                QtWidgets.QMessageBox.warning(self, "Не выбрано", "Выберите аккаунты")
                return
            
            # Применяем прокси к аккаунтам (по кругу если прокси меньше)
            updated = 0
            for i, acc_name in enumerate(selected_account_names):
                proxy = selected_proxies[i % len(selected_proxies)]
                account_service.update_account_proxy(acc_name, proxy['raw'])
                updated += 1
            
            # Обновляем привязку и обе таблицы
            self._load_accounts_map()
            
            QtWidgets.QMessageBox.information(
                self,
                "Применено",
                f"Прокси применены к {updated} аккаунтам"
            )
    
    def _on_auto_distribute(self):
        """Автоматическое распределение OK прокси по всем аккаунтам"""
        # Получаем только рабочие прокси
        ok_proxies = [px for px in self._proxies if px.get('last_status') == 'OK']
        
        if not ok_proxies:
            QtWidgets.QMessageBox.warning(
                self,
                "Нет рабочих прокси",
                "Сначала проверьте прокси. Автораспределение работает только с прокси со статусом OK."
            )
            return
        
        # Получаем все аккаунты (кроме demo и wordstat_main)
        accounts = account_service.list_accounts()
        target_accounts = [acc for acc in accounts if acc.name not in ["demo_account", "wordstat_main"]]
        
        if not target_accounts:
            QtWidgets.QMessageBox.warning(
                self,
                "Нет аккаунтов",
                "Не найдено аккаунтов для распределения прокси"
            )
            return
        
        # Подтверждение
        reply = QtWidgets.QMessageBox.question(
            self,
            "Автораспределение прокси",
            f"Распределить {len(ok_proxies)} рабочих прокси по {len(target_accounts)} аккаунтам?\n\n"
            f"Прокси будут назначены по кругу (round-robin).",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            return
        
        # Распределяем по кругу (round-robin)
        updated = 0
        for i, acc in enumerate(target_accounts):
            proxy = ok_proxies[i % len(ok_proxies)]
            account_service.update_account_proxy(acc.name, proxy['raw'])
            updated += 1
        
        # Обновляем привязку и обе таблицы
        self._load_accounts_map()
        
        QtWidgets.QMessageBox.information(
            self,
            "Автораспределение завершено",
            f"✅ Прокси распределены по {updated} аккаунтам\n\n"
            f"Рабочих прокси: {len(ok_proxies)}\n"
            f"Аккаунтов: {len(target_accounts)}\n"
            f"Метод: round-robin (по кругу)\n\n"
            f"Проверьте правую таблицу Аккаунты"
        )
    
    def _on_export(self):
        """Экспорт рабочих прокси"""
        ok_proxies = [px for px in self._proxies if px['last_status'] == 'OK']
        
        if not ok_proxies:
            QtWidgets.QMessageBox.warning(
                self,
                "Нет рабочих прокси",
                "Сначала проверьте прокси"
            )
            return
        
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Сохранить рабочие прокси",
            "working_proxies.txt",
            "Text Files (*.txt)"
        )
        
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write("\n".join([px['raw'] for px in ok_proxies]))
                
                QtWidgets.QMessageBox.information(
                    self,
                    "Сохранено",
                    f"Сохранено прокси: {len(ok_proxies)}"
                )
            except Exception as e:
                QtWidgets.QMessageBox.critical(
                    self,
                    "Ошибка",
                    f"Не удалось сохранить:\n{e}"
                )
    
    def _on_clear(self):
        """Очистить все прокси"""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Подтверждение",
            "Очистить все прокси из хранилища?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            proxy_store.clear_all()
            self._load_from_store()
            self._load_accounts_map()
    
    def _update_stats(self):
        """Обновляет статистику"""
        total = len(self._proxies)
        ok = sum(1 for px in self._proxies if px['last_status'] == 'OK')
        fail = sum(1 for px in self._proxies if px['last_status'] in ('FAIL', 'TIMEOUT', 'ERR'))
        
        self.lbl_stats.setText(f"Всего: {total} | OK: {ok} | FAIL: {fail}")

    
    def _refresh_accounts_table(self):
        """Обновляет правую таблицу аккаунтов"""
        if not hasattr(self, '_accounts_list'):
            return
        
        if not hasattr(self, 'accounts_table'):
            return
        
        self.accounts_table.setRowCount(len(self._accounts_list))
        
        for row, acc in enumerate(self._accounts_list):
            # Аккаунт
            name_item = QtWidgets.QTableWidgetItem(acc.name)
            name_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            self.accounts_table.setItem(row, 0, name_item)
            
            # Прокси (короткий формат для читаемости)
            proxy_text = ""
            if acc.proxy:
                # Показываем только host:port (без логина/пароля)
                try:
                    from ..utils.proxy import parse_proxy
                    parsed = parse_proxy(acc.proxy)
                    if parsed:
                        proxy_text = parsed['server'].replace('http://', '').replace('https://', '').replace('socks5://', '')
                    else:
                        proxy_text = acc.proxy[:30]
                except:
                    proxy_text = acc.proxy[:30]
            
            proxy_item = QtWidgets.QTableWidgetItem(proxy_text)
            proxy_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            
            if acc.proxy:
                proxy_item.setToolTip(f"Полный прокси:\n{acc.proxy}")
            
            self.accounts_table.setItem(row, 1, proxy_item)
            
            # Статус (куки)
            try:
                from ..services.accounts import get_cookies_status
                cookies_status = get_cookies_status(acc)
            except:
                cookies_status = "?"
            
            status_item = QtWidgets.QTableWidgetItem(cookies_status)
            status_item.setTextAlignment(QtCore.Qt.AlignCenter)
            status_item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
            
            if cookies_status == "Fresh":
                status_item.setForeground(QtGui.QBrush(QtGui.QColor("#4CAF50")))
            elif cookies_status == "Expired":
                status_item.setForeground(QtGui.QBrush(QtGui.QColor("#F44336")))
            
            self.accounts_table.setItem(row, 2, status_item)
