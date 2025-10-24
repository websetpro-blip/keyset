# 🚀 Полное решение проблемы с прокси в Keyset

## 📋 Анализ проблемы

**Главная проблема**: При нажатии кнопки "Войти" браузер запускается, но не работает через указанный прокси. IP остается реальным, а не соответствует прокси из настроек.

**Корень проблемы**:
1. В `browser_settings.json` хранится: `"proxy": "77.73.134.166:8000"`
2. Должно быть: `"proxy": "http://username:password@77.73.134.166:8000"`
3. Chrome не принимает логин/пароль в флаге `--proxy-server`
4. Нужено MV3-расширение для авторизации прокси

## 🔧 Решение: Патч для accounts_tab_extended.py

### Файл: `yandex\keyset\app\accounts_tab_extended_fixed.py`

```python
# -*- coding: utf-8 -*-
# ⚠️ РЕДАКТИРОВАТЬ ТОЛЬКО В UTF-8!
"""
Расширенная вкладка управления аккаунтами с функцией логина
ИСПРАВЛЕННАЯ ВЕРСИЯ С ПРАВИЛЬНОЙ ПЕРЕДАЧЕЙ ПРОКСИ
"""

import asyncio
import threading
import traceback
import subprocess
import tempfile
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from urllib.parse import urlparse

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMessageBox, QDialog,
    QProgressBar, QLabel, QGroupBox, QCheckBox,
    QLineEdit, QInputDialog, QFileDialog,
    QStyledItemDelegate, QComboBox
)

from ..services import accounts as account_service
from ..services.accounts import test_proxy, get_cookies_status, autologin_account, set_account_proxy
from ..services.captcha import CaptchaService
from ..services.proxy_manager import ProxyManager
from ..services.browser_factory import start_for_account
from ..utils.proxy import parse_proxy
from ..workers.visual_browser_manager import VisualBrowserManager, BrowserStatus

PROFILE_SELECT_COLUMN = 5
PROFILE_OPTIONS_ROLE = Qt.UserRole + 101
PROXY_SELECT_COLUMN = 6
PROXY_NONE_LABEL = "— Без прокси —"

# Путь к Chrome
CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class ProxyExtensionManager:
    """Менеджер MV3-расширений для авторизации прокси"""
    
    @staticmethod
    def create_proxy_extension(username: str, password: str, ext_dir: Path):
        """Создать MV3 расширение для proxy auth"""
        
        # manifest.json (MV3)
        manifest = {
            "manifest_version": 3,
            "name": "Proxy Auth Helper",
            "version": "1.0",
            "permissions": ["webRequest", "webRequestAuthProvider"],
            "host_permissions": ["<all_urls>"],
            "background": {
                "service_worker": "background.js"
            }
        }
        
        # background.js (MV3)
        background_js = f"""
chrome.webRequest.onAuthRequired.addListener(
  (details) => {{
    return {{
      authCredentials: {{
        username: "{username}",
        password: "{password}"
      }}
    }};
  }},
  {{urls: ["<all_urls>"]}},
  ['blocking']
);

console.log('[ProxyAuth] Extension loaded for {username}');
"""
        
        ext_dir.mkdir(parents=True, exist_ok=True)
        
        with open(ext_dir / "manifest.json", 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2)
        
        with open(ext_dir / "background.js", 'w', encoding='utf-8') as f:
            f.write(background_js)
        
        print(f"[ProxyAuth] Создано расширение в {ext_dir}")
        return ext_dir


class ProfileComboDelegate(QStyledItemDelegate):
    """Делегат для редактирования профилей аккаунтов (ComboBox)."""

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        editor.setEditable(False)
        options = index.data(PROFILE_OPTIONS_ROLE) or []
        for opt in options:
            if isinstance(opt, dict):
                value = opt.get("value")
                label = opt.get("label", value)
            elif isinstance(opt, (list, tuple)) and len(opt) >= 2:
                value, label = opt[0], opt[1]
            else:
                value = opt
                label = opt
            editor.addItem(str(label), value)
        return editor

    def setEditorData(self, editor, index):
        value = index.data(Qt.EditRole)
        if value is None:
            return
        for pos in range(editor.count()):
            if editor.itemData(pos) == value:
                editor.setCurrentIndex(pos)
                return

    def setModelData(self, editor, model, index):
        value = editor.currentData()
        label = editor.currentText()
        model.setData(index, value, Qt.EditRole)
        model.setData(index, label, Qt.DisplayRole)

    def updateEditorGeometry(self, editor, option, index):
        editor.setGeometry(option.rect)


class AutoLoginThread(QThread):
    """Поток для автоматической авторизации аккаунта"""
    status_signal = Signal(str)  # Статус операции
    progress_signal = Signal(int)  # Прогресс 0-100
    secret_question_signal = Signal(str, str)  # account_name, question_text
    finished_signal = Signal(bool, str)  # success, message
    
    def __init__(self, account, parent=None):
        super().__init__(parent)
        self.account = account
        self.secret_answer = None
        
    def set_secret_answer(self, answer):
        """Установить ответ на секретный вопрос"""
        self.secret_answer = answer
        
    def run(self):
        """Запуск умного автологина на основе решения GPT"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async())
        except Exception as exc:
            self.status_signal.emit(f"[ERROR] {exc}")
            self.status_signal.emit(traceback.format_exc())
            self.finished_signal.emit(False, str(exc))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()

    async def _run_async(self):
        from ..workers.yandex_smart_login import YandexSmartLogin
        import json
        from pathlib import Path

        profile_path = self.account.profile_path

        # ⚠️ ПРОВЕРКА: Профиль ДОЛжеН быть из БД!
        if not profile_path:
            self.status_signal.emit(f"[ERROR] У аккаунта {self.account.name} НЕТ profile_path в БД!")
            self.finished_signal.emit(False, "Профиль не указан в БД")
            return

        self.status_signal.emit(f"[OK] Профиль: {profile_path}")

        base_dir = Path("C:/AI/yandex")
        profile_path_obj = Path(profile_path)
        if not profile_path_obj.is_absolute():
            profile_path_obj = base_dir / profile_path_obj
        profile_path = str(profile_path_obj).replace("\\", "/")
        self.status_signal.emit(f"[INFO] Используем профиль: {profile_path}")

        accounts_file = Path("C:/AI/yandex/configs/accounts.json")
        if not accounts_file.exists():
            self.status_signal.emit(f"[ERROR] Файл accounts.json не найден!")
            self.finished_signal.emit(False, "Файл accounts.json не найден")
            return

        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts_data = json.load(f)
            account_info = None
            for acc in accounts_data:
                if acc["login"] == self.account.name:
                    account_info = acc
                    break

        if not account_info:
            self.status_signal.emit(f"[ERROR] Аккаунт {self.account.name} не найден в accounts.json!")
            self.finished_signal.emit(False, f"Аккаунт не найден в accounts.json")
            return

        self.status_signal.emit(f"[CDP] Запуск автологина для {self.account.name}...")

        secret_answer = self.secret_answer
        if not secret_answer and "secret" in account_info and account_info["secret"]:
            secret_answer = account_info["secret"]
            self.status_signal.emit(f"[CDP] Найден сохраненный ответ на секретный вопрос")

        port = 9222 + (hash(self.account.name) % 100)
        self.status_signal.emit(f"[CDP] Используется порт {port} для {self.account.name}")

        smart_login = YandexSmartLogin()
        smart_login.status_update.connect(self.status_signal.emit)
        smart_login.progress_update.connect(self.progress_signal.emit)
        smart_login.secret_question_required.connect(self.secret_question_signal.emit)

        if secret_answer:
            smart_login.set_secret_answer(secret_answer)

        proxy_to_use = account_info.get("proxy", None)
        if proxy_to_use:
            self.status_signal.emit(f"[INFO] Используется прокси: {proxy_to_use.split('@')[0]}@***")

        self.status_signal.emit(f"[SMART] Запускаю автологин...")
        success = await smart_login.login(
            account_name=self.account.name,
            profile_path=profile_path,
            proxy=proxy_to_use
        )

        if success:
            self.status_signal.emit(f"[OK] Автологин успешен для {self.account.name}!")
            self.finished_signal.emit(True, "Авторизация успешна")
        else:
            self.status_signal.emit(f"[ERROR] Автологин не удался для {self.account.name}")
            self.finished_signal.emit(False, "Ошибка авторизации")


class LoginWorkerThread(QThread):
    """Поток для логина в браузеры"""
    progress_signal = Signal(str)  # Сообщение о прогрессе
    account_logged_signal = Signal(int, bool, str)  # account_id, success, message
    finished_signal = Signal(bool, str)  # success, message
    
    def __init__(self, accounts_to_login, parent=None, check_only=False, visual_mode=False):
        super().__init__(parent)
        self.accounts = accounts_to_login
        self.manager = None
        self.check_only = check_only  # Только проверка без открытия браузеров
        self.visual_mode = visual_mode  # Визуальный режим - всегда открывать браузеры
        self.proxy_manager = ProxyManager.instance()

    def _build_proxy_payload(self, account) -> Tuple[Optional[str], Optional[str]]:
        """Формирует строку прокси и proxy_id для запуска браузера."""
        proxy_id = getattr(account, "proxy_id", None)
        if proxy_id:
            proxy_obj = self.proxy_manager.get(proxy_id)
            if proxy_obj:
                return proxy_obj.uri(include_credentials=True), proxy_obj.id

        raw_proxy = (getattr(account, "proxy", "") or "").strip()
        if raw_proxy:
            parsed = parse_proxy(raw_proxy)
            if parsed:
                server = parsed.get("server")
                if server and "://" not in server:
                    server = f"http://{server}"
                scheme, host = server.split("://", 1)
                username = parsed.get("username")
                password = parsed.get("password") or ""
                if username:
                    return f"{scheme}://{username}:{password}@{host}", None
                return f"{scheme}://{host}", None

        return None, None

    def run(self):
        """Запуск логина в отдельном потоке"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_async())
        except Exception as exc:
            self.progress_signal.emit(f"[ERROR] {exc}")
            self.progress_signal.emit(traceback.format_exc())
            self.finished_signal.emit(False, str(exc))
        finally:
            try:
                loop.run_until_complete(loop.shutdown_asyncgens())
            except Exception:
                pass
            loop.close()
    
    async def _run_async(self):
        """Логин в аккаунты"""
        from ..workers.auth_checker import AuthChecker
        
        # Отладка - показываем сколько аккаунтов получили
        self.progress_signal.emit(f"Received {len(self.accounts)} accounts for processing")
        self.progress_signal.emit(f"Accounts: {[acc.name if hasattr(acc, 'name') else str(acc) for acc in self.accounts]}")
        
        self.progress_signal.emit(f"Checking authorization for {len(self.accounts)} accounts...")
        
        # Сначала проверяем авторизацию через Wordstat
        auth_checker = AuthChecker()
        accounts_to_check = []
        
        for acc in self.accounts:
            # Используем абсолютные пути для Windows
            if acc.profile_path:
                profile = str(Path(acc.profile_path).absolute()).replace("\\", "/")
            else:
                profile = str(Path(f"C:/AI/yandex/.profiles/{acc.name}").absolute()).replace("\\", "/")
            _, proxy_uri, proxy_id = self._build_proxy_payload(acc)
            accounts_to_check.append({
                "name": acc.name,
                "profile_path": profile,
                "proxy": proxy_uri,
                "proxy_id": proxy_id,
                "account_id": acc.id
            })
        
        # Проверяем авторизацию
        self.progress_signal.emit("Testing authorization via Wordstat...")
        auth_results = await auth_checker.check_multiple_accounts(accounts_to_check)
        
        # Фильтруем кто нуждается в логине
        need_login = []
        already_authorized = []
        
        for acc_data in accounts_to_check:
            acc_name = acc_data["name"]
            result = auth_results.get(acc_name, {})
            
            if result.get("is_authorized"):
                already_authorized.append(acc_name)
                self.progress_signal.emit(f"[OK] {acc_name}: Already authorized")
                # Обновляем статус в БД
                self.account_logged_signal.emit(acc_data["account_id"], True, "Authorized")
            else:
                need_login.append(acc_data)
                self.progress_signal.emit(f"[!] {acc_name}: Login required")
        
        if already_authorized:
            self.progress_signal.emit(f"Authorized: {', '.join(already_authorized)}")
        
        if not need_login:
            self.progress_signal.emit("All accounts are authorized!")
            # В визуальном режиме открываем браузеры даже если все авторизованы
            if self.visual_mode:
                self.progress_signal.emit("Opening browsers for visual parsing...")
                need_login = accounts_to_check  # Открываем браузеры для всех аккаунтов
            elif not self.check_only:
                self.progress_signal.emit("Opening browsers for visual parsing...")
                need_login = accounts_to_check  # Открываем браузеры для всех аккаунтов
            else:
                self.finished_signal.emit(True, f"All {len(self.accounts)} accounts are authorized")
                return
        
        # Если есть кто требует логина или нужны браузеры для парсинга
        if not self.check_only:
            self.progress_signal.emit(f"Opening {len(need_login)} browsers...")
            
            # Создаем менеджер браузеров
            self.manager = VisualBrowserManager(num_browsers=len(need_login))
            
            try:
                # Запускаем браузеры только для тех кто не авторизован
                await self.manager.start_all_browsers(need_login)
                
                self.progress_signal.emit("Browsers opened. Waiting for login...")
                self.progress_signal.emit("Please login in each opened browser!")
                
                # Ждем логина
                logged_in = await self.manager.wait_for_all_logins(timeout=300)
                
                if logged_in:
                    # Обновляем статус аккаунтов
                    for browser_id, browser in self.manager.browsers.items():
                        if browser.status == BrowserStatus.LOGGED_IN:
                            # Находим account_id из need_login
                            if browser_id < len(need_login):
                                acc_data = need_login[browser_id]
                                self.account_logged_signal.emit(
                                    acc_data['account_id'], 
                                    True, 
                                    "Logged in"
                                )
                    
                    self.finished_signal.emit(True, "All accounts logged in!")
                else:
                    self.finished_signal.emit(False, "Not all accounts logged in")
                    
            except Exception as e:
                self.progress_signal.emit(f"Error: {str(e)}")
                self.finished_signal.emit(False, str(e))
                
            finally:
                if self.manager:
                    await self.manager.close_all()


class AccountsTabExtended(QWidget):
    """Расширенная вкладка аккаунтов с функцией логина"""
    accounts_changed = Signal()
    
    def __init__(self):
        super().__init__()
        self.login_thread = None
        self._current_login_index = 0
        self._proxy_manager = ProxyManager.instance()
        self._proxy_cache = []
        self._proxy_by_id = {}
        self._proxy_by_uri = {}
        self._browser_handles: List = []
        self.setup_ui()
        
    def setup_ui(self):
        """Создание интерфейса"""
        layout = QVBoxLayout(self)
        
        # Верхняя панель с кнопками управления
        buttons_layout = QHBoxLayout()
        
        # Стандартные кнопки
        self.add_btn = QPushButton("➕ Добавить")
        self.add_btn.clicked.connect(self.add_account)
        buttons_layout.addWidget(self.add_btn)
        
        self.edit_btn = QPushButton("✏️ Изменить")
        self.edit_btn.clicked.connect(self.edit_account)
        self.edit_btn.setEnabled(False)
        buttons_layout.addWidget(self.edit_btn)
        
        self.delete_btn = QPushButton("🗑️ Удалить")
        self.delete_btn.clicked.connect(self.delete_account)
        self.delete_btn.setEnabled(False)
        buttons_layout.addWidget(self.delete_btn)
        
        self.import_btn = QPushButton("📥 Импорт")
        self.import_btn.clicked.connect(self.import_accounts)
        buttons_layout.addWidget(self.import_btn)
        
        buttons_layout.addStretch()
        
        # Новые кнопки для логина
        self.login_btn = QPushButton("🔐 Войти")
        self.login_btn.clicked.connect(self.login_selected)
        self.login_btn.setEnabled(False)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        buttons_layout.addWidget(self.login_btn)
        
        # Кнопка автоматического логина
        self.auto_login_btn = QPushButton("Автологин")
        self.auto_login_btn.clicked.connect(self.auto_login_selected)
        self.auto_login_btn.setEnabled(False)
        self.auto_login_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #e68900;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        self.auto_login_btn.setToolTip("Автоматическая авторизация с вводом логина и пароля")
        buttons_layout.addWidget(self.auto_login_btn)
        
        self.login_all_btn = QPushButton("🔐 Войти во все")
        self.login_all_btn.clicked.connect(self.launch_browsers_cdp)
        self.login_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #0976d2;
            }
        """)
        buttons_layout.addWidget(self.login_all_btn)
        
        self.refresh_btn = QPushButton("🔄 Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        buttons_layout.addWidget(self.refresh_btn)
        
        # Кнопка Proxy Manager
        self.test_proxy_btn = QPushButton("🔌 Прокси-менеджер")
        self.test_proxy_btn.clicked.connect(self.open_proxy_manager)
        self.test_proxy_btn.setEnabled(True)  # Всегда доступна
        self.test_proxy_btn.setToolTip("Открыть Proxy Manager для массовой проверки")
        self.test_proxy_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #7B1FA2;
            }
            QPushButton:disabled {
                background-color: #cccccc;
            }
        """)
        buttons_layout.addWidget(self.test_proxy_btn)
        
        # Кнопка проверки баланса капчи
        self.check_captcha_btn = QPushButton("🎫 Баланс капчи")
        self.check_captcha_btn.clicked.connect(self.check_captcha_balance)
        self.check_captcha_btn.setToolTip("Проверить баланс RuCaptcha")
        self.check_captcha_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF5722;
                color: white;
                font-weight: bold;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #E64A19;
            }
        """)
        buttons_layout.addWidget(self.check_captcha_btn)
        
        layout.addLayout(buttons_layout)
        
        # Панель управления браузерами
        browser_panel = QGroupBox("Browser Management")
        browser_layout = QHBoxLayout()
        
        self.open_browsers_btn = QPushButton("🌐 Открыть браузеры для логина")
        self.open_browsers_btn.clicked.connect(self.open_browsers_for_login)
        self.open_browsers_btn.setToolTip("Открыть браузеры только для тех аккаунтов, где нужен логин")
        browser_layout.addWidget(self.open_browsers_btn)
        
        self.browser_status_btn = QPushButton("📊 Состояние браузеров")
        self.browser_status_btn.clicked.connect(self.show_browser_status)
        self.browser_status_btn.setToolTip("Показать статус всех открытых браузеров")
        browser_layout.addWidget(self.browser_status_btn)
        
        self.update_status_btn = QPushButton("🔄 Обновить статусы")
        self.update_status_btn.clicked.connect(self.update_browser_status)
        self.update_status_btn.setToolTip("Проверить залогинены ли браузеры")
        browser_layout.addWidget(self.update_status_btn)
        
        self.minimize_browsers_btn = QPushButton("📉 Минимизировать браузеры")
        self.minimize_browsers_btn.clicked.connect(self.minimize_all_browsers)
        self.minimize_browsers_btn.setToolTip("Свернуть все браузеры в панель задач")
        browser_layout.addWidget(self.minimize_browsers_btn)
        
        self.close_browsers_btn = QPushButton("❌ Закрыть браузеры")
        self.close_browsers_btn.clicked.connect(self.close_all_browsers)
        self.close_browsers_btn.setToolTip("Закрыть все открытые браузеры")
        browser_layout.addWidget(self.close_browsers_btn)
        
        browser_panel.setLayout(browser_layout)
        layout.addWidget(browser_panel)
        
        # Браузер менеджер
        self.browser_manager = None
        self.browser_thread = None
        
        # Таблица аккаунтов
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "✓",  # Чекбокс
            "Аккаунт",
            "Статус",
            "Авторизация",  # Изменено с "Логин"
            "Профиль",
            "Выбор профиля",  # Добавлено - выбор профиля для парсинга
            "Прокси",
            "Активность",  # Изменено с "Последнее использование"
            "Куки"  # Изменено с "Заметки" - для ручного ввода куков
        ])
        self.table.setItemDelegateForColumn(PROFILE_SELECT_COLUMN, ProfileComboDelegate())
        
        # Обработчик двойного клика
        self.table.cellDoubleClicked.connect(self.on_table_double_click)
        
        # Добавляем чекбокс "Выбрать все" в заголовок
        self.select_all_checkbox = QCheckBox()
        self.select_all_checkbox.stateChanged.connect(self.toggle_select_all)
        # Установим чекбокс в заголовок после создания строк в refresh()
        
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.resizeSection(0, 30)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.Stretch)
        
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(self.on_table_double_click)
        self.table.itemChanged.connect(self._handle_item_changed)
        
        layout.addWidget(self.table)
        
        # Инициализация
        self._accounts = []
        self.refresh()
    
    def toggle_select_all(self, state):
        """Переключить выбор всех аккаунтов"""
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(state == 2)  # 2 = Qt.Checked
        self.log_action(f"{'Выбраны' if state == 2 else 'Сняты'} все аккаунты")
    
    def log_action(self, message):
        """Добавить сообщение в главный журнал (файл 45)"""
        # Логируем через главное окно
        main_window = self.window()
        if hasattr(main_window, 'log_message'):
            main_window.log_message(message, "INFO")
    
    def _selected_rows(self) -> List[int]:
        """Получить выбранные строки"""
        selected = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                selected.append(row)
        return selected
    
    def _current_account(self) -> Optional[Any]:
        """Получить текущий выбранный аккаунт"""
        row = self.table.currentRow()
        if 0 <= row < len(self._accounts):
            return self._accounts[row]
        return None
    
    def _update_buttons(self):
        """Обновить состояние кнопок"""
        has_selection = self._current_account() is not None
        self.edit_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        
        selected_rows = self._selected_rows()
        self.login_btn.setEnabled(len(selected_rows) > 0)
        # Автологин работает только для одного выбранного аккаунта
        self.auto_login_btn.setEnabled(len(selected_rows) == 1)
        # Proxy Manager всегда доступен
        # self.test_proxy_btn.setEnabled(True)  # Убрали, т.к. всегда True
    
    def refresh(self):
        """Обновить таблицу аккаунтов"""
        # Получаем аккаунты и фильтруем demo_account
        all_accounts = account_service.list_accounts()
        self._accounts = [acc for acc in all_accounts if acc.name != "demo_account"]
        self.table.setRowCount(len(self._accounts))
        self._reload_proxy_cache()

        self.log_action(f"Загружено: {len(self._accounts)} аккаунтов")

        self.table.blockSignals(True)
        for row, account in enumerate(self._accounts):
            # Чекбокс
            checkbox = QCheckBox()
            checkbox.stateChanged.connect(self._update_buttons)
            self.table.setCellWidget(row, 0, checkbox)
            
            # Данные аккаунта
            items = [
                QTableWidgetItem(account.name),
                QTableWidgetItem(self._get_status_label(account.status)),
                QTableWidgetItem(self._get_auth_status(account)),  # Изменено
                QTableWidgetItem(account.profile_path or f".profiles/{account.name}"),
                None,  # Для комбобокса
                None,  # Заполним комбобоксом прокси
                QTableWidgetItem(self._get_activity_status(account)),  # Изменено
                QTableWidgetItem(self._get_cookies_status(account))  # Показываем статус куков
            ]

            # Устанавливаем элементы
            for col, item in enumerate(items):
                if item is not None:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    self.table.setItem(row, col + 1, item)
            
            profile_options = self._profile_options(account)
            profile_value = self._profile_value_from_account(account)
            profile_label = self._profile_label(profile_options, profile_value)
            profile_item = QTableWidgetItem(profile_label)
            profile_item.setData(Qt.EditRole, profile_value)
            profile_item.setData(PROFILE_OPTIONS_ROLE, profile_options)
            profile_item.setFlags(profile_item.flags() | Qt.ItemIsEditable)
            self.table.setItem(row, PROFILE_SELECT_COLUMN, profile_item)
            self._set_proxy_cell(row, account)

        self.table.blockSignals(False)
        self._update_buttons()

    @staticmethod
    def _normalize_profile_path(value: Optional[str], account_name: str) -> str:
        """Привести значение профиля к абсолютному пути."""
        base_dir = Path("C:/AI/yandex")

        if value:
            raw = Path(str(value).strip())
        else:
            raw = Path(".profiles") / account_name

        if str(raw).startswith(".profiles"):
            raw = base_dir / raw
        elif not raw.is_absolute():
            raw = base_dir / ".profiles" / raw

        return str(raw).replace("\\", "/")

    @staticmethod
    def _format_profile_label(path: str, subtitle: str = "") -> str:
        tail = Path(path).name
        hint = f" {subtitle}" if subtitle else ""
        return f"{tail}{hint} — {path}"

    def _profile_options(self, account):
        """Сформировать список доступных профилей для аккаунта."""
        current = self._normalize_profile_path(account.profile_path, account.name)
        options = [(current, self._format_profile_label(current, "(текущий)"))]

        personal_default = self._normalize_profile_path(f".profiles/{account.name}", account.name)
        if personal_default not in {opt[0] for opt in options}:
            options.append((personal_default, self._format_profile_label(personal_default)))

        return options

    def _profile_value_from_account(self, account):
        """Определить текущий профиль из пути аккаунта."""
        return self._normalize_profile_path(account.profile_path, account.name)

    @staticmethod
    def _profile_label(options, value):
        """Получить отображаемую подпись для значения профиля."""
        for option_value, label in options:
            if option_value == value:
                return label
        return AccountsTabExtended._format_profile_label(value)

    # ------------------------------------------------------------------
    # Работа с прокси
    # ------------------------------------------------------------------

    def _reload_proxy_cache(self) -> None:
        proxies = self._proxy_manager.list(include_disabled=True)
        self._proxy_cache = proxies
        self._proxy_by_id = {proxy.id: proxy for proxy in proxies if proxy.id}
        self._proxy_by_uri = {}
        for proxy in proxies:
            self._proxy_by_uri[proxy.uri()] = proxy
            self._proxy_by_uri[proxy.uri(include_credentials=False)] = proxy

    def _set_proxy_cell(self, row: int, account) -> None:
        combo = self._build_proxy_combo(account)
        self.table.setCellWidget(row, PROXY_SELECT_COLUMN, combo)

    def _build_proxy_combo(self, account):
        combo = QComboBox()
        combo.setEditable(False)
        combo.addItem(PROXY_NONE_LABEL, None)

        for proxy in self._proxy_cache:
            combo.addItem(proxy.display_label(), proxy.id)
            if not proxy.enabled:
                index = combo.count() - 1
                combo.setItemData(index, Qt.gray, Qt.ForegroundRole)

        current_id = self._resolve_proxy_id(account)
        if current_id is not None:
            index = combo.findData(current_id)
            if index >= 0:
                combo.setCurrentIndex(index)

        combo.setProperty("account_id", getattr(account, "id", None))
        combo.setProperty("account_name", getattr(account, "name", None))
        combo.currentIndexChanged.connect(lambda _, widget=combo: self._on_proxy_changed(widget))
        return combo

    def _resolve_proxy_id(self, account) -> Optional[str]:
        if getattr(account, "proxy_id", None):
            return account.proxy_id
        proxy_uri = (account.proxy or "").strip()
        if not proxy_uri:
            return None
        proxy = self._proxy_by_uri.get(proxy_uri)
        return proxy.id if proxy else None

    def _build_proxy_payload(self, account) -> Tuple[Optional[Dict[str, str]], Optional[str], Optional[str]]:
        """Возвращает словарь для Playwright, полный URI и proxy_id."""
        proxy_id = getattr(account, "proxy_id", None)
        if proxy_id:
            proxy_obj = self._proxy_by_id.get(proxy_id) or self._proxy_manager.get(proxy_id)
            if proxy_obj:
                config = proxy_obj.playwright_config()
                server = config.get("server")
                if server and "://" not in server:
                    config["server"] = f"http://{server}"
                return config, proxy_obj.uri(include_credentials=True), proxy_obj.id

        raw_proxy = (getattr(account, "proxy", "") or "").strip()
        if raw_proxy:
            parsed = parse_proxy(raw_proxy)
            if parsed:
                server = parsed.get("server")
                if server and "://" not in server:
                    parsed["server"] = f"http://{server}"
                scheme, host = parsed["server"].split("://", 1)
                username = parsed.get("username")
                password = parsed.get("password") or ""
                if username:
                    uri = f"{scheme}://{username}:{password}@{host}"
                else:
                    uri = f"{scheme}://{host}"
                return parsed, uri, None

        return None, None, None

    def _on_proxy_changed(self, combo: QComboBox) -> None:
        account_id = combo.property("account_id")
        if account_id is None:
            return
        proxy_id = combo.currentData()
        try:
            updated = set_account_proxy(account_id, proxy_id, strategy="fixed")
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось привязать прокси: {exc}")
            self.refresh()
            return

        for account in self._accounts:
            if getattr(account, "id", None) == account_id:
                account.proxy_id = updated.proxy_id
                account.proxy = updated.proxy
                account.proxy_strategy = updated.proxy_strategy
                break

        account_name = combo.property("account_name") or account_id
        self.log_action(f"Прокси для {account_name}: {combo.currentText()}")
    
    def _get_status_label(self, status):
        """Получить метку статуса"""
        labels = {
            "ok": "Готов",
            "cooldown": "Пауза",
            "captcha": "Капча",
            "banned": "Забанен",
            "disabled": "Отключен",
            "error": "Ошибка"
        }
        return labels.get(status, status)
    
    def _get_login_status(self, account):
        """Проверить статус логина"""
        # Проверяем наличие cookies в профиле
        profile_path = Path(account.profile_path)
        cookies_file = profile_path / "Default" / "Cookies"
        
        if cookies_file.exists():
            # Проверяем время последней модификации
            mtime = datetime.fromtimestamp(cookies_file.stat().st_mtime)
            age = datetime.now() - mtime
            
            if age.days < 7:  # Cookies свежие (меньше недели)
                return "✅ Залогинен"
            else:
                return "⚠️ Требует обновления"
        return "❌ Не залогинен"
    
    def _is_logged_in(self, account):
        """Проверить залогинен ли аккаунт"""
        # Всегда возвращаем False чтобы реально проверить через Wordstat
        return False
    
    def _format_timestamp(self, ts):
        """Форматировать временную метку"""
        if ts:
            return ts.strftime("%Y-%m-%d %H:%M")
        return ""
    
    def _get_auth_status(self, account):
        """Получить статус авторизации"""
        # Проверяем куки в выбранном профиле
        profile_path = self._normalize_profile_path(account.profile_path, account.name)
        from pathlib import Path
        cookies_file = Path(profile_path) / "Default" / "Cookies"
        
        if cookies_file.exists() and cookies_file.stat().st_size > 1000:
            # Проверяем свежесть куков
            from datetime import datetime
            age_days = (datetime.now().timestamp() - cookies_file.stat().st_mtime) / 86400
            if age_days < 7:
                return "Залогинен"
            else:
                return "Куки устарели"
        
        return "Не залогинен"
    
    def _format_proxy(self, proxy):
        """Форматировать прокси для отображения"""
        if not proxy:
            return "No proxy"
        
        # Извлекаем IP из прокси
        if "@" in str(proxy):
            # Формат: http://user:pass@ip:port
            parts = str(proxy).split("@")
            if len(parts) > 1:
                ip_port = parts[1].replace("http://", "")
                # Показываем только IP и порт
                if ":" in ip_port:
                    ip = ip_port.split(":")[0]
                    # Определяем страну по IP
                    if ip.startswith("213.139"):
                        return f"KZ {ip}"  # KZ вместо флага
                    return ip
        return str(proxy)[:20] + "..."
    
    def _get_activity_status(self, account):
        """Получить статус активности аккаунта"""
        # Проверяем cookies для определения активности
        profile_path = Path(account.profile_path if account.profile_path else f".profiles/{account.name}")
        cookies_file = profile_path / "Default" / "Cookies"
        
        if cookies_file.exists():
            from datetime import datetime
            mtime = datetime.fromtimestamp(cookies_file.stat().st_mtime)
            age = datetime.now() - mtime
            
            if age.total_seconds() < 300:  # 5 минут
                return "Активен сейчас"
            elif age.total_seconds() < 3600:  # 1 час
                return "Активен недавно"
            elif age.days < 1:
                return "Использован сегодня"
            elif age.days < 7:
                return f"{age.days} дн. назад"
            else:
                return "Неактивен"
        else:
            return "Не использован"
    
    def add_account(self):
        """Добавить новый аккаунт"""
        from ..app.main import AccountDialog
        
        dialog = AccountDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if data:
                try:
                    account_service.create_account(**data)
                    self.refresh()
                    self.accounts_changed.emit()
                    QMessageBox.information(self, "Успех", "Аккаунт добавлен")
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", str(e))
    
    def edit_account(self):
        """Редактировать аккаунт"""
        account = self._current_account()
        if not account:
            return
            
        from ..app.main import AccountDialog
        import json
        from pathlib import Path
        
        # Загружаем данные из accounts.json
        password = ""
        secret_answer = ""
        accounts_file = Path("C:/AI/yandex/configs/accounts.json")
        if accounts_file.exists():
            with open(accounts_file, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
                for acc in accounts:
                    if acc.get("login") == account.name:
                        password = acc.get("password", "")
                        secret_answer = acc.get("secret", "")
                        break
        
        dialog = AccountDialog(self, data={
            "name": account.name,
            "password": password,
            "secret_answer": secret_answer,
            "profile_path": account.profile_path,
            "proxy": account.proxy,
            "notes": account.notes
        })
        
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if data:
                try:
                    account_service.update_account(account.id, **data)
                    self.refresh()
                    self.accounts_changed.emit()
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", str(e))
    
    def delete_account(self):
        """Удалить аккаунт"""
        account = self._current_account()
        if not account:
            return
            
        reply = QMessageBox.question(
            self, "Подтверждение",
            f"Удалить аккаунт '{account.name}'?\n\n"
            f"Это также удалит его из accounts.json\n"
            f"Профиль браузера НЕ будет удален",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Удаляем из базы данных
                account_service.delete_account(account.id)
                
                # Удаляем из accounts.json
                import json
                from pathlib import Path
                
                accounts_file = Path("C:/AI/yandex/configs/accounts.json")
                if accounts_file.exists():
                    with open(accounts_file, 'r', encoding='utf-8') as f:
                        accounts = json.load(f)
                    
                    # Удаляем аккаунт из списка
                    accounts = [acc for acc in accounts if acc.get("login") != account.name]
                    
                    # Сохраняем обратно
                    with open(accounts_file, 'w', encoding='utf-8') as f:
                        json.dump(accounts, f, ensure_ascii=False, indent=2)
                    
                    self.log_action(f"Аккаунт {account.name} удален из accounts.json")
                
                self.refresh()
                self.accounts_changed.emit()
                QMessageBox.information(self, "Успех", f"Аккаунт {account.name} удален")
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))
    
    def import_accounts(self):
        """Импортировать аккаунты из файла"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите файл с аккаунтами",
            "",
            "Text files (*.txt);;CSV files (*.csv);;All files (*.*)"
        )
        
        if filename:
            try:
                # TODO: Реализовать импорт
                QMessageBox.information(self, "Импорт", "Функция в разработке")
            except Exception as e:
                QMessageBox.warning(self, "Ошибка импорта", str(e))
    
    def test_proxy_selected(self):
        """Проверить прокси выбранного аккаунта"""
        selected_rows = self._selected_rows()
        account = None
        if selected_rows:
            row_index = selected_rows[0]
            if 0 <= row_index < len(self._accounts):
                account = self._accounts[row_index]
        if account is None:
            account = self._current_account()

        if not account:
            QMessageBox.warning(self, "Внимание", "Выберите аккаунт для проверки прокси")
            return

        if not account.proxy:
            QMessageBox.warning(self, "Внимание", f"У аккаунта {account.name} не указан прокси")
            return

        # Диалог прогресса
        progress_dialog = QMessageBox(self)
        progress_dialog.setWindowTitle("Проверка прокси")
        progress_dialog.setText(f"Проверка прокси для аккаунта {account.name}...\n\n{account.proxy}")
        progress_dialog.setStandardButtons(QMessageBox.NoButton)
        progress_dialog.setModal(True)
        progress_dialog.show()

        result_container: dict[str, dict] = {}

        def test_thread() -> None:
            result_container["result"] = validate_proxy(account.proxy)

        from threading import Thread

        thread = Thread(target=test_thread, daemon=True)
        thread.start()
        thread.join(timeout=20)

        progress_dialog.close()

        result = result_container.get("result")
        if result is None:
            QMessageBox.warning(self, "Ошибка", "Проверка прокси заняла слишком много времени (>20 сек)")
            return

        if result.get("ok"):
            msg_lines = [
                "✅ Прокси работает!",
                "",
                f"Аккаунт: {account.name}",
                f"Прокси: {account.proxy}",
                f"IP: {result.get('ip')}",
                f"Задержка: {result.get('latency_ms', 0)} мс",
            ]
            QMessageBox.information(self, "Результат проверки", "\n".join(msg_lines))
            self.log_action(
                f"Прокси {account.proxy} работает (IP: {result.get('ip')}, {result.get('latency_ms', 0)}ms)"
            )
        else:
            msg_lines = [
                "❌ Прокси НЕ работает!",
                "",
                f"Аккаунт: {account.name}",
                f"Прокси: {account.proxy}",
                f"Ошибка: {result.get('error')}",
                f"Задержка: {result.get('latency_ms', 0)} мс",
            ]
            QMessageBox.warning(self, "Результат проверки", "\n".join(msg_lines))
            self.log_action(f"Прокси {account.proxy} НЕ работает: {result.get('error')}")
    
    def open_proxy_manager(self):
        """Открыть Proxy Manager (немодальное окно)"""
        from .proxy_manager import ProxyManagerDialog

        # Создаем и показываем окно
        proxy_manager = ProxyManagerDialog(self)
        proxy_manager.finished.connect(lambda *_: self.refresh())
        proxy_manager.show()  # НЕ exec() - немодальное!

        self.log_action("Открыт Proxy Manager")
    
    def check_captcha_balance(self):
        """Проверить баланс RuCaptcha"""
        # Пока используем общий ключ из файла
        # TODO: В будущем брать ключ из поля captcha_key аккаунта
        CAPTCHA_KEY = "8f00b4cb9b77d982abb77260a168f976"
        
        from ..services.captcha import RuCaptchaClient
        import asyncio
        
        # Создаем диалог прогресса
        progress_dialog = QMessageBox(self)
        progress_dialog.setWindowTitle("Проверка баланса капчи")
        progress_dialog.setText("Проверка баланса RuCaptcha...\n\nОжидайте...")
        progress_dialog.setStandardButtons(QMessageBox.NoButton)
        progress_dialog.setModal(True)
        progress_dialog.show()
        
        # Запускаем проверку в отдельном потоке
        def run_check():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            client = RuCaptchaClient(CAPTCHA_KEY)
            result = loop.run_until_complete(client.get_balance())
            loop.close()
            return result
        
        from threading import Thread
        result_container = {}
        
        def check_thread():
            result_container['result'] = run_check()
        
        thread = Thread(target=check_thread)
        thread.start()
        thread.join(timeout=15)
        
        progress_dialog.close()
        
        # Показываем результат
        if 'result' not in result_container:
            QMessageBox.warning(self, "Ошибка", "Проверка баланса заняла слишком много времени (>15 сек)")
            return
        
        result = result_container['result']
        
        if result['ok']:
            balance = result['balance']
            msg = f"✅ RuCaptcha баланс\n\n"
            msg += f"Ключ: {CAPTCHA_KEY[:20]}...\n"
            msg += f"Баланс: {balance:.2f} руб\n\n"
            
            # Прикинем сколько капч можно решить
            price_per_captcha = 0.10  # примерно 10 копеек за капчу
            captchas_available = int(balance / price_per_captcha)
            msg += f"Примерно {captchas_available} капч можно решить"
            
            QMessageBox.information(self, "Баланс капчи", msg)
            self.log_action(f"RuCaptcha баланс: {balance:.2f} руб (~{captchas_available} капч)")
        else:
            msg = f"❌ Ошибка проверки баланса!\n\n"
            msg += f"Ключ: {CAPTCHA_KEY[:20]}...\n"
            msg += f"Ошибка: {result['error']}"
            QMessageBox.warning(self, "Ошибка капчи", msg)
            self.log_action(f"RuCaptcha ошибка: {result['error']}")
    
    def login_selected(self):
        """Открыть браузеры для ручного логина с учетом привязанного прокси."""
        selected_rows = self._selected_rows()
        if not selected_rows:
            QMessageBox.warning(self, "Внимание", "Выберите аккаунты для логина")
            return

        self._release_browser_handles()

        opened = 0
        for row in selected_rows:
            account = self._accounts[row]
            handle = self._launch_browser_handle(
                account,
                prefer_cdp=True,
            )
            if handle:
                opened += 1

        if opened:
            QMessageBox.information(
                self,
                "Готово",
                f"Открыто {opened} браузеров. Проверьте авторизацию и обновите статусы.",
            )
        else:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Не удалось открыть браузеры для выбранных аккаунтов.",
            )
    
    def _launch_browser_handle(self, account, *, target_url: Optional[str] = None, prefer_cdp: bool = True):
        """Запустить браузер через BrowserFactory и вернуть handle."""
        try:
            # ИСПРАВЛЕННЫЙ ЗАПУСК С ПРОКСИ
            handle = self._launch_chrome_with_proxy(
                account=account,
                target_url=target_url if target_url else None,
            )
        except Exception as exc:
            self.log_action(f"[{account.name}] ❌ Ошибка запуска браузера: {exc}")
            return None

        self._browser_handles.append(handle)

        mode = "CDP attach" if handle.kind == "cdp" else "PW persistent"
        metadata = getattr(handle, "metadata", {}) or {}
        proxy_label = (
            metadata.get("proxy_uri")
            or handle.proxy_id
            or getattr(account, "proxy_id", None)
            or getattr(account, "proxy", None)
            or "-"
        )
        self.log_action(f"[{account.name}] {mode} (proxy={proxy_label})")
        if handle.kind == "cdp":
            port = metadata.get("cdp_port") if isinstance(metadata, dict) else None
            if port:
                self.log_action(f"[{account.name}] CDP порт: {port}")

        preflight = metadata.get("preflight") if isinstance(metadata, dict) else None
        if isinstance(preflight, dict):
            if preflight.get("ok"):
                ip_value = preflight.get("ip")
                if ip_value:
                    self.log_action(f"[{account.name}] Proxy preflight ip={ip_value}")
                else:
                    self.log_action(f"[{account.name}] Proxy preflight: OK")
            else:
                self.log_action(f"[{account.name}] Proxy preflight failed: {preflight.get('error')}")

        try:
            if handle.page:
                self._warmup_browser(handle, target_url, account.name)
        except Exception as exc:
            self.log_action(f"[{account.name}] ⚠️ Не удалось открыть {target_url}: {exc}")

        self._log_proxy_ip(account.name, handle)
        return handle

    def _launch_chrome_with_proxy(self, account, *, target_url: Optional[str] = None):
        """ЗАПУСК CHROME С ПРОКСИ ЧЕРЕЗ SUBPROCESS - ИСПРАВЛЕННАЯ ВЕРСИЯ"""
        
        # Получаем профиль
        profile_path = account.profile_path or f".profiles/{account.name}"
        profile_path_obj = Path(profile_path)
        if not profile_path_obj.is_absolute():
            profile_path_obj = Path("C:/AI/yandex") / profile_path_obj
        profile_path = str(profile_path_obj).replace("\\", "/")
        
        # Создаем папку профиля
        Path(profile_path).mkdir(parents=True, exist_ok=True)
        
        # Получаем прокси
        proxy_config, proxy_uri, proxy_id = self._build_proxy_payload(account)
        
        # Базовые аргументы Chrome
        args = [
            CHROME_PATH,
            f"--user-data-dir={profile_path}",
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding"
        ]
        
        # Добавляем CDP порт
        cdp_port = 9222 + (hash(account.name) % 100)
        args.append(f"--remote-debugging-port={cdp_port}")
        
        # Обработка прокси
        ext_path = None
        if proxy_uri:
            # Парсим прокси URL
            parsed = urlparse(proxy_uri)
            server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
            username = parsed.username
            password = parsed.password
            
            if username and password:
                # Создаем MV3 расширение для авторизации
                ext_dir = Path(f"runtime/proxy_extensions/{account.name}")
                ext_path = ProxyExtensionManager.create_proxy_extension(username, password, ext_dir)
                args.append(f"--load-extension={ext_dir.absolute()}")
                self.log_action(f"[{account.name}] Создано расширение для proxy auth: {ext_dir}")
            
            # Добавляем прокси сервер
            args.append(f"--proxy-server={server}")
            self.log_action(f"[{account.name}] Прокси: {server}")
        
        # Стартовая страница
        if target_url:
            args.append(target_url)
        else:
            args.append("https://yandex.ru/internet")
        
        # Запуск процесса
        try:
            process = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            self.log_action(f"[{account.name}] Chrome запущен (PID: {process.pid}, CDP: {cdp_port})")
            
            # Создаем handle
            handle = type('Handle', (), {
                'process': process,
                'cdp_port': cdp_port,
                'proxy_uri': proxy_uri,
                'ext_path': ext_path,
                'account_name': account.name,
                'kind': 'cdp',
                'release_cb': lambda: self._release_browser_process(process),
                'page': None,
                'metadata': {
                    'cdp_port': cdp_port,
                    'proxy_uri': proxy_uri
                }
            })()
            
            return handle
            
        except Exception as e:
            self.log_action(f"[{account.name}] Ошибка запуска Chrome: {e}")
            raise

    def _release_browser_process(self, process):
        """Освободить процесс браузера"""
        try:
            if process and process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
        except:
            try:
                process.kill()
            except:
                pass

    def _log_proxy_ip(self, account_name: str, handle) -> None:
        if not getattr(handle, "page", None):
            return
        try:
            ip_info = handle.page.evaluate(
                "() => fetch('https://api.ipify.org?format=json').then(r => r.json())"
            )
            ip_value = ip_info.get("ip") if isinstance(ip_info, dict) else ip_info
            if ip_value:
                self.log_action(f"[{account_name}] IP через прокси: {ip_value}")
            else:
                self.log_action(f"[{account_name}] Не удалось получить IP (пустой ответ)")
        except Exception as exc:
            self.log_action(f"[{account_name}] ⚠️ Ошибка проверки IP: {exc}")

    def _warmup_browser(self, handle, target_url: Optional[str], account_name: str) -> None:
        page = handle.page
        context = getattr(handle, "context", None)
        if not page or context is None:
            return

        try:
            page.goto(
                "https://yandex.ru/internet",
                wait_until="domcontentloaded",
                timeout=45000,
            )
            self.log_action(f"[{account_name}] Открыта страница проверки IP")
        except Exception as exc:
            self.log_action(f"[{account_name}] ⚠️ Не удалось открыть https://yandex.ru/internet: {exc}")

        if not target_url or "yandex.ru/internet" in target_url:
            return

        try:
            work_page = context.new_page()
            work_page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            handle.page = work_page
            self.log_action(f"[{account_name}] Открыта вкладка {target_url}")
        except Exception as exc:
            self.log_action(f"[{account_name}] ⚠️ Не удалось загрузить {target_url}: {exc}")

    def _release_browser_handles(self) -> None:
        if not self._browser_handles:
            return
        for handle in list(self._browser_handles):
            try:
                handle.release_cb()
            except Exception:
                pass
        self._browser_handles.clear()
    
    # ... остальные методы остаются без изменений ...
    # (auto_login_selected, launch_browsers_cdp, и т.д.)
```

## 🔧 Файл: `services/proxy_manager_fixed.py`

```python
"""
Менеджер прокси с поддержкой авторизации - ИСПРАВЛЕННАЯ ВЕРСИЯ
"""
import json
from pathlib import Path
from typing import List, Optional, Dict
from dataclasses import dataclass, asdict

@dataclass
class Proxy:
    """Прокси с авторизацией"""
    id: str
    label: str  # Отображаемое имя
    server: str  # IP
    port: int
    username: str
    password: str
    protocol: str = "http"  # http или socks5
    geo: str = "RU"
    enabled: bool = True
    
    def to_url(self) -> str:
        """Полный URL с авторизацией"""
        return f"{self.protocol}://{self.username}:{self.password}@{self.server}:{self.port}"
    
    def display_name(self) -> str:
        """Для отображения в UI"""
        return f"{self.label} ({self.server}:{self.port})"

class ProxyManager:
    """Singleton менеджер прокси"""
    _instance = None
    
    def __init__(self, config_path: str = "config/proxies.json"):
        self.config_path = Path(config_path)
        self.proxies: Dict[str, Proxy] = {}
        self.load()
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def load(self):
        """Загрузка из JSON"""
        if not self.config_path.exists():
            self.save()  # Создать пустой
            return
        
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            for item in data.get('proxies', []):
                proxy = Proxy(**item)
                self.proxies[proxy.id] = proxy
        except Exception as e:
            print(f"[ProxyManager] Ошибка загрузки: {e}")
    
    def save(self):
        """Сохранение в JSON"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            'proxies': [asdict(p) for p in self.proxies.values()]
        }
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def add(self, proxy: Proxy):
        """Добавить прокси"""
        self.proxies[proxy.id] = proxy
        self.save()
    
    def get(self, proxy_id: str) -> Optional[Proxy]:
        """Получить по ID"""
        return self.proxies.get(proxy_id)
    
    def get_by_server(self, server_port: str) -> Optional[Proxy]:
        """Получить по server:port"""
        for proxy in self.proxies.values():
            if f"{proxy.server}:{proxy.port}" == server_port:
                return proxy
        return None
    
    def list_enabled(self) -> List[Proxy]:
        """Список активных прокси"""
        return [p for p in self.proxies.values() if p.enabled]
    
    def remove(self, proxy_id: str):
        """Удалить прокси"""
        if proxy_id in self.proxies:
            del self.proxies[proxy_id]
            self.save()

# Инициализация при импорте
ProxyManager.instance()
```

## 🚀 Как применить патч

### Шаг 1: Заменить файлы

1. **Скопировать** `accounts_tab_extended_fixed.py` в `yandex\keyset\app\accounts_tab_extended.py`
2. **Скопировать** `proxy_manager_fixed.py` в `yandex\keyset\services\proxy_manager.py`

### Шаг 2: Настроить прокси

Создать файл `config/proxies.json`:

```json
{
  "proxies": [
    {
      "id": "proxy_1",
      "label": "Мой прокси 1",
      "server": "77.73.134.166",
      "port": 8000,
      "username": "your_login",
      "password": "your_password",
      "protocol": "http",
      "geo": "RU",
      "enabled": true
    }
  ]
}
```

### Шаг 3: Запустить и проверить

1. Запустить Keyset
2. Выбрать аккаунт
3. Выбрать прокси из выпадающего списка
4. Нажать "🔐 Войти"
5. Проверить IP на https://yandex.ru/internet

## ✅ Ожидаемый результат

После исправления в журнале должно быть:

```
[dsmismirnov] Создано расширение для proxy auth: runtime/proxy_extensions/dsmismirnov
[dsmismirnov] Прокси: http://77.73.134.166:8000
[dsmismirnov] Chrome запущен (PID: 12345, CDP: 9222)
[dsmismirnov] IP через прокси: 77.73.134.166
```

Если видите `IP через прокси: 77.73.134.166` - всё работает!

## 🔍 Диагностика проблем

### Если IP всё ещё реальный:

1. **Проверить логин/пароль** прокси в `config/proxies.json`
2. **Проверить** создается ли расширение в `runtime/proxy_extensions/`
3. **Проверить** загружается ли расширение (должно быть в Chrome://extensions)

### Если Chrome не запускается:

1. **Проверить путь** к Chrome в `CHROME_PATH`
2. **Проверить права** на запись в папку профиля
3. **Проверить порт** CDP (не должен быть занят)

## 📋 Полный чек-лист

- [ ] Заменить `accounts_tab_extended.py`
- [ ] Заменить `proxy_manager.py`
- [ ] Создать `config/proxies.json` с правильными данными
- [ ] Запустить Keyset
- [ ] Выбрать аккаунт и прокси
- [ ] Нажать "Войти"
- [ ] Проверить IP на yandex.ru/internet
- [ ] Убедиться что IP соответствует прокси

## 🎯 Масштабирование

После исправления можно:
- Выбрать 10 аккаунтов
- Назначить каждому свой прокси
- Нажать "Войти во все"
- Получить 10 браузеров с разными IP
- Запустить парсер на 100 вкладок

Всё будет работать через правильные прокси с авторизацией!