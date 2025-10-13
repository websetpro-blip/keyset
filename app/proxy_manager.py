"""
Proxy Manager - массовая загрузка и проверка прокси (как в Key Collector)
"""

from PySide6 import QtWidgets, QtCore
import re
import asyncio
import aiohttp
from datetime import datetime
from typing import Optional, List, Dict

try:
    from aiohttp_socks import ProxyConnector  # pip install aiohttp-socks
except ImportError:
    ProxyConnector = None


def parse_proxy_line(line: str) -> Optional[Dict]:
    """
    Парсит строку прокси в любом формате:
    - ip:port
    - user:pass@ip:port
    - ip:port@user:pass  (SemTool формат)
    - http://user:pass@ip:port
    - socks5://user:pass@ip:port
    """
    s = line.strip()
    if not s:
        return None
    
    # Формат SemTool: ip:port@user:pass
    if '@' in s and not s.startswith(('http://', 'https://', 'socks')):
        parts = s.split('@', 1)
        if len(parts) == 2 and ':' in parts[0] and ':' in parts[1]:
            server_part = parts[0]  # ip:port
            auth_part = parts[1]     # user:pass
            username, password = auth_part.split(':', 1)
            return {
                "server": f"http://{server_part}",
                "scheme": "http",
                "login": username,
                "password": password,
                "raw": s
            }
    
    # Нормализуем префикс
    if "://" not in s:
        s = "http://" + s
    
    # Парсим URL формат
    m = re.match(r"(?P<scheme>https?|socks5)://(?:(?P<u>[^:@]+):(?P<p>[^@]+)@)?(?P<h>[^:]+):(?P<port>\d+)", s, re.I)
    if not m:
        return None
    
    d = m.groupdict()
    return {
        "server": f"{d['scheme'].lower()}://{d['h']}:{d['port']}",
        "scheme": d["scheme"].lower(),
        "login": d.get("u") or "",
        "password": d.get("p") or "",
        "raw": line.strip()
    }


async def check_one_proxy(px: Dict, timeout_ms: int = 5000) -> tuple:
    """
    Проверяет один прокси
    Возвращает: (status, latency_ms, error_message)
    """
    url = "http://httpbin.org/ip"  # Быстрый тестовый сервис
    timeout = aiohttp.ClientTimeout(total=timeout_ms / 1000)
    
    start_time = asyncio.get_event_loop().time()
    
    try:
        if px["scheme"].startswith("socks"):
            if ProxyConnector is None:
                return ("ERR", None, "aiohttp_socks не установлен")
            
            conn = ProxyConnector.from_url(
                px["server"],
                rdns=True,
                username=px["login"] or None,
                password=px["password"] or None
            )
            
            async with aiohttp.ClientSession(connector=conn, timeout=timeout) as session:
                async with session.get(url) as response:
                    await response.text()
        else:
            # HTTP/HTTPS прокси
            async with aiohttp.ClientSession(timeout=timeout) as session:
                proxy_auth = None
                if px["login"]:
                    proxy_auth = aiohttp.BasicAuth(px["login"], px["password"])
                
                async with session.get(
                    url,
                    proxy=px["server"],
                    proxy_auth=proxy_auth,
                    ssl=False  # Отключаем SSL для избежания ошибок с прокси
                ) as response:
                    await response.text()
        
        elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
        return ("OK", elapsed_ms, "")
    
    except asyncio.TimeoutError:
        elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
        return ("TIMEOUT", elapsed_ms, "Превышен таймаут")
    
    except Exception as e:
        elapsed_ms = int((asyncio.get_event_loop().time() - start_time) * 1000)
        error_msg = str(e)[:120]  # Обрезаем длинные ошибки
        return ("FAIL", elapsed_ms, error_msg)


class ProxyManagerDialog(QtWidgets.QDialog):
    """Окно управления прокси (как в Key Collector)"""
    
    COLUMNS = ["Proxy", "Тип", "Логин", "Пароль", "Статус", "Пинг (мс)", "Ошибка", "Проверено"]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("🔌 Прокси-менеджер")
        self.setModal(False)  # ВАЖНО: немодальное окно, не блокирует приложение
        self.resize(1000, 600)
        
        # Данные
        self._proxies: List[Dict] = []
        self._stop_flag = False
        
        # Создаем UI
        self._create_ui()
        
    def _create_ui(self):
        """Создает интерфейс"""
        layout = QtWidgets.QVBoxLayout(self)
        
        # Кнопки управления
        buttons_layout = QtWidgets.QHBoxLayout()
        
        self.btn_paste = QtWidgets.QPushButton("📋 Вставить из буфера")
        self.btn_load_file = QtWidgets.QPushButton("📁 Загрузить .txt")
        self.btn_check_all = QtWidgets.QPushButton("✅ Проверить все")
        self.btn_stop = QtWidgets.QPushButton("⛔ Остановить")
        self.btn_apply = QtWidgets.QPushButton("💾 Применить к аккаунтам")
        self.btn_export = QtWidgets.QPushButton("📤 Экспорт OK")
        self.btn_clear = QtWidgets.QPushButton("🗑 Очистить")
        self.btn_close = QtWidgets.QPushButton("❌ Закрыть")
        
        self.btn_stop.setEnabled(False)
        
        buttons_layout.addWidget(self.btn_paste)
        buttons_layout.addWidget(self.btn_load_file)
        buttons_layout.addWidget(self.btn_check_all)
        buttons_layout.addWidget(self.btn_stop)
        buttons_layout.addWidget(self.btn_apply)
        buttons_layout.addWidget(self.btn_export)
        buttons_layout.addWidget(self.btn_clear)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.btn_close)
        
        layout.addLayout(buttons_layout)
        
        # Настройки проверки
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
        
        # Таблица прокси
        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        
        # Растягиваем колонки
        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        for i in [0, 6]:  # Proxy и Ошибка
            header.setSectionResizeMode(i, QtWidgets.QHeaderView.Stretch)
        
        layout.addWidget(self.table)
        
        # Подключаем сигналы
        self.btn_paste.clicked.connect(self._on_paste)
        self.btn_load_file.clicked.connect(self._on_load_file)
        self.btn_check_all.clicked.connect(self._on_check_all)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_clear.clicked.connect(self._on_clear)
        self.btn_export.clicked.connect(self._on_export)
        self.btn_close.clicked.connect(self.close)
    
    def _append_proxy(self, px: Dict):
        """Добавляет прокси в таблицу"""
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        values = [
            px["raw"],
            px["scheme"].upper(),
            px["login"],
            "***" if px["password"] else "",
            "WAIT",
            "",
            "",
            ""
        ]
        
        for col, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(str(value))
            if col == 4:  # Статус
                item.setTextAlignment(QtCore.Qt.AlignCenter)
            self.table.setItem(row, col, item)
        
        self._proxies.append(px)
        self._update_stats()
    
    def _on_paste(self):
        """Вставить из буфера обмена"""
        text = QtWidgets.QApplication.clipboard().text()
        added = 0
        
        for line in text.splitlines():
            px = parse_proxy_line(line)
            if px:
                self._append_proxy(px)
                added += 1
        
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
                    px = parse_proxy_line(line)
                    if px:
                        self._append_proxy(px)
                        added += 1
            
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
    
    def _on_check_all(self):
        """Запустить массовую проверку"""
        if not self._proxies:
            QtWidgets.QMessageBox.warning(
                self,
                "Нет прокси",
                "Добавьте прокси для проверки"
            )
            return
        
        self._stop_flag = False
        self.btn_check_all.setEnabled(False)
        self.btn_stop.setEnabled(True)
        
        # Запускаем проверку в asyncio
        asyncio.create_task(self._check_all_async())
    
    async def _check_all_async(self):
        """Массовая проверка прокси"""
        concurrency = self.spin_threads.value()
        timeout_ms = self.spin_timeout.value() * 1000
        
        sem = asyncio.Semaphore(concurrency)
        
        async def check_one(idx: int, px: Dict):
            if self._stop_flag:
                return
            
            async with sem:
                status, latency, error = await check_one_proxy(px, timeout_ms)
                
                # Обновляем таблицу
                self.table.item(idx, 4).setText(status)
                
                if latency is not None:
                    self.table.item(idx, 5).setText(str(latency))
                
                self.table.item(idx, 6).setText(error)
                
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.table.item(idx, 7).setText(now)
                
                # Цветовое выделение
                color = QtCore.Qt.green if status == "OK" else QtCore.Qt.red
                for col in range(self.table.columnCount()):
                    self.table.item(idx, col).setBackground(color)
                
                self._update_stats()
        
        tasks = [check_one(i, px) for i, px in enumerate(self._proxies)]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        self.btn_check_all.setEnabled(True)
        self.btn_stop.setEnabled(False)
    
    def _on_stop(self):
        """Остановить проверку"""
        self._stop_flag = True
        self.btn_check_all.setEnabled(True)
        self.btn_stop.setEnabled(False)
    
    def _on_clear(self):
        """Очистить таблицу"""
        reply = QtWidgets.QMessageBox.question(
            self,
            "Подтверждение",
            "Очистить все прокси?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply == QtWidgets.QMessageBox.Yes:
            self.table.setRowCount(0)
            self._proxies.clear()
            self._update_stats()
    
    def _on_export(self):
        """Экспорт рабочих прокси"""
        ok_proxies = []
        
        for row in range(self.table.rowCount()):
            status = self.table.item(row, 4).text()
            if status == "OK":
                proxy_raw = self.table.item(row, 0).text()
                ok_proxies.append(proxy_raw)
        
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
                    f.write("\n".join(ok_proxies))
                
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
    
    def _update_stats(self):
        """Обновляет статистику"""
        total = self.table.rowCount()
        ok = 0
        fail = 0
        
        for row in range(total):
            status = self.table.item(row, 4).text()
            if status == "OK":
                ok += 1
            elif status in ("FAIL", "TIMEOUT", "ERR"):
                fail += 1
        
        self.lbl_stats.setText(f"Всего: {total} | OK: {ok} | FAIL: {fail}")
    
    def get_working_proxies(self) -> List[str]:
        """Возвращает список рабочих прокси"""
        working = []
        
        for row in range(self.table.rowCount()):
            status = self.table.item(row, 4).text()
            if status == "OK":
                proxy_raw = self.table.item(row, 0).text()
                working.append(proxy_raw)
        
        return working
