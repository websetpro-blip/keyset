# -*- coding: utf-8 -*-
# ⚠️ РЕДАКТИРОВАТЬ ТОЛЬКО В UTF-8!
"""
Расширенная вкладка управления аккаунтами с функцией логина

ПРАВИЛО №1: НЕ ЛОМАТЬ ТО ЧТО РАБОТАЕТ!
- Не удалять рабочие функции
- Не изменять работающую логику
- Не трогать то, что пользователь не просил менять
"""

import asyncio
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

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
# Старый worker больше не используется, теперь CDP подход

PROFILE_SELECT_COLUMN = 5
PROFILE_OPTIONS_ROLE = Qt.UserRole + 101
PROXY_SELECT_COLUMN = 6
PROXY_NONE_LABEL = "— Без прокси —"


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

        self.status_signal.emit(f"[OK] Профиль РёР· Р'Р]: {profile_path}")

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
        
        # Убрали локальный Status and Activity - используем главный журнал внизу (файл 45)
        
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
        account = self._current_account()
        if not account:
            QMessageBox.warning(self, "Внимание", "Выберите аккаунт для проверки прокси")
            return
        
        if not account.proxy:
            QMessageBox.warning(self, "Внимание", f"У аккаунта {account.name} не указан прокси")
            return
        
        # Импортируем сервис проверки прокси
        from ..services.proxy_check import test_proxy
        import asyncio
        
        # Создаем диалог прогресса
        progress_dialog = QMessageBox(self)
        progress_dialog.setWindowTitle("Проверка прокси")
        progress_dialog.setText(f"Проверка прокси для аккаунта {account.name}...\n\n{account.proxy}")
        progress_dialog.setStandardButtons(QMessageBox.NoButton)
        progress_dialog.setModal(True)
        progress_dialog.show()
        
        # Запускаем проверку в отдельном потоке
        def run_test():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(test_proxy(account.proxy))
            loop.close()
            return result
        
        from threading import Thread
        result_container = {}
        
        def test_thread():
            result_container['result'] = run_test()
        
        thread = Thread(target=test_thread)
        thread.start()
        thread.join(timeout=15)
        
        progress_dialog.close()
        
        # Показываем результат
        if 'result' not in result_container:
            QMessageBox.warning(self, "Ошибка", "Проверка прокси заняла слишком много времени (>15 сек)")
            return
        
        result = result_container['result']
        
        if result['ok']:
            msg = f"✅ Прокси работает!\n\n"
            msg += f"Аккаунт: {account.name}\n"
            msg += f"Прокси: {account.proxy}\n"
            msg += f"IP: {result['ip']}\n"
            msg += f"Задержка: {result['latency_ms']} мс"
            QMessageBox.information(self, "Результат проверки", msg)
            self.log_action(f"Прокси {account.proxy} работает (IP: {result['ip']}, {result['latency_ms']}ms)")
        else:
            msg = f"❌ Прокси НЕ работает!\n\n"
            msg += f"Аккаунт: {account.name}\n"
            msg += f"Прокси: {account.proxy}\n"
            msg += f"Ошибка: {result['error']}\n"
            msg += f"Задержка: {result['latency_ms']} мс"
            QMessageBox.warning(self, "Результат проверки", msg)
            self.log_action(f"Прокси {account.proxy} НЕ работает: {result['error']}")
    
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
                target_url="https://wordstat.yandex.ru/?region=225",
                prefer_cdp=False,
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
    
    def auto_login_selected(self):
        """Автоматическая авторизация ВЫБРАННЫХ аккаунтов (где стоят галочки)"""
        # Берем только выбранные аккаунты
        selected_rows = self._selected_rows()
        
        if not selected_rows:
            QMessageBox.warning(self, "Внимание", "Выберите аккаунты для автологина (поставьте галочки)")
            return
        
        # Если выбрано больше одного - спрашиваем подтверждение
        if len(selected_rows) > 1:
            reply = QMessageBox.question(self, "Подтверждение",
                f"Будет выполнена авторизация {len(selected_rows)} выбранных аккаунтов.\n\n"
                f"Каждый аккаунт будет открыт в отдельном браузере.\n"
                f"Продолжить?",
                QMessageBox.Yes | QMessageBox.No)
            
            if reply != QMessageBox.Yes:
                return
        
        self.log_action(f"Запуск автологина для {len(selected_rows)} выбранных аккаунтов...")
        
        # Запускаем автологин только для ВЫБРАННЫХ аккаунтов
        self.auto_login_threads = []
        for idx, row_idx in enumerate(selected_rows):
            account = self._accounts[row_idx]
            self.log_action(f"[{idx+1}/{len(selected_rows)}] Запуск автологина для {account.name}...")
            
            # Создаем отдельный поток для каждого аккаунта
            thread = AutoLoginThread(account)
            thread.status_signal.connect(lambda msg, acc=account.name: self.log_action(f"[{acc}] {msg}"))
            thread.progress_signal.connect(self._update_progress)
            thread.secret_question_signal.connect(self._handle_secret_question)
            thread.finished_signal.connect(lambda success, msg, acc=account.name: self._on_auto_login_finished(success, f"[{acc}] {msg}"))
            
            # ВАЖНО: Большая задержка между запусками чтобы не вызвать капчу!
            QTimer.singleShot(idx * 10000, thread.start)  # 10 секунд между запусками!
            self.auto_login_threads.append(thread)
        
        # Отключаем кнопки на время авторизации
        self.auto_login_btn.setEnabled(False)
        self.log_action(f"Запуск автологина для {account.name}...")
    
    def _handle_secret_question(self, account_name: str, question_text: str):
        """Обработка секретного вопроса"""
        from PySide6.QtWidgets import QInputDialog
        
        # Показываем диалог для ввода ответа
        answer, ok = QInputDialog.getText(
            self,
            "Секретный вопрос",
            f"Аккаунт: {account_name}\n\n{question_text}\n\nВведите ответ:",
            echo=QLineEdit.Normal
        )
        
        if ok and answer:
            # Передаем ответ в поток
            if hasattr(self, 'auto_login_thread'):
                self.auto_login_thread.set_secret_answer(answer)
    
    def _update_progress(self, value: int):
        """Обновление прогресса"""
        # Если есть прогресс-бар, обновляем его
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setValue(value)
    
    def _on_auto_login_finished(self, success: bool, message: str):
        """Обработка завершения автологина"""
        # Включаем кнопку обратно
        self.auto_login_btn.setEnabled(True)
        
        if success:
            self.log_action(f"[OK] {message}")
            # Обновляем таблицу
            self.refresh()
        else:
            self.log_action(f"[ERROR] {message}")
            QMessageBox.warning(self, "Ошибка автологина", message)
    
    def launch_browsers_cdp(self):
        """Открыть браузеры для парсинга, учитывая выбранные прокси."""
        selected_rows = self._selected_rows()
        if not selected_rows:
            QMessageBox.warning(self, "Внимание", "Выберите аккаунты для запуска")
            return

        selected_accounts = [
            self._accounts[row] for row in selected_rows if row < len(self._accounts)
        ]

        self.log_action(f"Запуск {len(selected_accounts)} выбранных браузеров для парсинга...")

        reply = QMessageBox.question(
            self,
            "Запуск браузеров",
            f"Будет запущено {len(selected_accounts)} браузеров для парсинга.\n\n"
            f"Аккаунты:\n" + "\n".join(f"  • {acc.name}" for acc in selected_accounts) + "\n\n"
            "Браузеры откроются с существующими куками без попытки автологина.\n"
            "Продолжить?",
        )

        if reply != QMessageBox.Yes:
            return

        self._release_browser_handles()
        launched = 0

        for account in selected_accounts:
            handle = self._launch_browser_handle(
                account,
                target_url="https://wordstat.yandex.ru/?region=225",
                prefer_cdp=False,
            )
            if handle:
                launched += 1

        if launched:
            QMessageBox.information(
                self,
                "Успех",
                f"Запущено {launched} браузеров. Теперь можно запускать парсер.",
            )
        else:
            self.log_action("❌ Не удалось запустить браузеры")
            QMessageBox.warning(self, "Ошибка", "Не удалось запустить браузеры")

    def _launch_browser_handle(self, account, *, target_url: str, prefer_cdp: bool):
        """Запустить браузер через BrowserFactory и вернуть handle."""
        try:
            handle = start_for_account(
                account_id=account.id,
                headless=False,
                use_cdp=prefer_cdp,
                profile_override=account.profile_path or f".profiles/{account.name}",
            )
        except Exception as exc:
            self.log_action(f"[{account.name}] ❌ Ошибка запуска браузера: {exc}")
            return None

        self._browser_handles.append(handle)

        mode = "CDP attach" if handle.kind == "cdp" else "PW persistent"
        proxy_label = handle.proxy_id or getattr(account, "proxy_id", None) or getattr(account, "proxy", None) or "-"
        self.log_action(f"[{account.name}] {mode} (proxy={proxy_label})")

        metadata = getattr(handle, "metadata", {}) or {}
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

    def _warmup_browser(self, handle, target_url: str, account_name: str) -> None:
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
    
    def login_all(self):
        """Автологин для новых аккаунтов - последовательная авторизация"""
        if not self._accounts:
            QMessageBox.warning(self, "Внимание", "Нет аккаунтов для логина")
            return
        
        self.log_action("Запуск последовательной авторизации всех аккаунтов...")
        
        # Спрашиваем подтверждение
        reply = QMessageBox.question(self, "Подтверждение",
            f"Будет выполнен последовательный вход в {len(self._accounts)} аккаунт(ов).\n\n"
            f"Каждый аккаунт будет авторизован автоматически.\n"
            f"Это может занять несколько минут.\n\n"
            f"Продолжить?")
        
        if reply == QMessageBox.Yes:
            self.log_action("Начинаем последовательную авторизацию...")
            # Запускаем последовательную авторизацию
            self._current_login_index = 0
            self._login_next_account()
    
    def _login_next_account(self):
        """Логин в следующий аккаунт из списка"""
        if self._current_login_index >= len(self._accounts):
            # Все аккаунты обработаны
            self.log_action("✅ Авторизация всех аккаунтов завершена!")
            QMessageBox.information(self, "Готово", "Авторизация всех аккаунтов завершена!")
            self.refresh()
            return
        
        account = self._accounts[self._current_login_index]
        self.log_action(f"Авторизация {self._current_login_index + 1}/{len(self._accounts)}: {account.name}...")
        
        # Запускаем автологин для текущего аккаунта
        self.auto_login_thread = AutoLoginThread(account)
        self.auto_login_thread.status_signal.connect(lambda msg: self.log_action(f"[{account.name}] {msg}"))
        self.auto_login_thread.finished_signal.connect(self._on_account_login_finished)
        self.auto_login_thread.start()
    
    def _on_account_login_finished(self, success: bool, message: str):
        """Обработка завершения логина одного аккаунта"""
        account = self._accounts[self._current_login_index]
        
        if success:
            self.log_action(f"✅ {account.name}: {message}")
        else:
            self.log_action(f"❌ {account.name}: {message}")
        
        # Переходим к следующему аккаунту
        self._current_login_index += 1
        
        # Небольшая задержка перед следующим аккаунтом
        QTimer.singleShot(2000, self._login_next_account)
    
    def _start_login(self, accounts, headless=False, visual_mode=False):
        """Запустить процесс логина"""
        if self.login_thread and self.login_thread.isRunning():
            QMessageBox.warning(self, "Внимание", "Процесс логина уже запущен")
            return
        
        # Блокируем кнопки
        self.login_btn.setEnabled(False)
        self.login_all_btn.setEnabled(False)
        
        # Показываем прогресс
        self.login_progress.setVisible(True)
        self.login_progress.setRange(0, 0)  # Неопределенный прогресс
        
        # Создаем и запускаем поток
        # visual_mode=True для визуального парсинга
        self.login_thread = LoginWorkerThread(accounts, check_only=headless, visual_mode=visual_mode)
        self.login_thread.progress_signal.connect(self.on_login_progress)
        self.login_thread.account_logged_signal.connect(self.on_account_logged)
        self.login_thread.finished_signal.connect(self.on_login_finished)
        self.login_thread.start()
        
        self.log_action(f"Запуск {len(accounts)} браузеров...")
    
    def on_login_progress(self, message):
        """Обработка прогресса логина"""
        self.log_action(message)
    
    def on_account_logged(self, account_id, success, message):
        """Обработка логина конкретного аккаунта"""
        # Обновляем статус в БД
        if success:
            account_service.mark_ok(account_id)
        
        # Обновляем таблицу
        self.refresh()
    
    def on_login_finished(self, success, message):
        """Обработка завершения логина"""
        self.login_progress.setVisible(False)
        self.login_btn.setEnabled(True)
        self.login_all_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "Успех", message)
        else:
            QMessageBox.warning(self, "Внимание", message)
        
        self.log_action("Готов к работе")
        self.refresh()
    
    def open_browsers_for_login(self):
        """Открыть браузеры только для тех аккаунтов где нужен логин"""
        from pathlib import Path
        
        # Фильтруем аккаунты которые требуют логина
        accounts_to_check = []
        for acc in self._accounts:
            if acc.name != "demo_account":  # Пропускаем демо
                # Используем полный путь к профилю
                # acc.profile_path может содержать относительный путь типа ".profiles/dsmismirnov"
                if acc.profile_path:
                    # Если путь начинается с .profiles - это относительный путь
                    if acc.profile_path.startswith(".profiles"):
                        profile_full_path = Path("C:/AI/yandex") / acc.profile_path
                    else:
                        profile_full_path = Path(acc.profile_path)
                else:
                    # Если путь не задан, используем стандартный
                    profile_full_path = Path("C:/AI/yandex/.profiles") / acc.name
                
                # Проверяем есть ли сохраненные куки
                cookie_file = profile_full_path / "Default" / "Cookies"
                _, proxy_uri, proxy_id = self._build_proxy_payload(acc)
                
                # Добавляем в список для проверки
                accounts_to_check.append({
                    "account": acc,
                    "has_cookies": cookie_file.exists(),
                    "profile_path": str(profile_full_path),
                    "proxy": proxy_uri,
                    "proxy_id": proxy_id,
                })
        
        if not accounts_to_check:
            QMessageBox.information(self, "Информация", "Нет аккаунтов для проверки")
            return
        
        # Показываем диалог выбора
        msg = "Статус аккаунтов:\n\n"
        
        # Даже если все авторизованы, открываем браузеры для визуального парсинга
        msg += "\n⚠️ ВНИМАНИЕ: Браузеры будут открыты для визуального парсинга.\n"
        msg += "Все аккаунты должны быть авторизованы.\n"
        msg += "Открыть браузеры?"
        
        reply = QMessageBox.question(self, "Открыть браузеры для логина", msg)
        if reply != QMessageBox.Yes:
            return

        self._release_browser_handles()

        launched = 0
        for info in accounts_to_check:
            account = info["account"]
            handle = self._launch_browser_handle(
                account,
                target_url="https://wordstat.yandex.ru/?region=225",
                prefer_cdp=False,
            )
            if handle:
                launched += 1

        if launched:
            QMessageBox.information(
                self,
                "Готово",
                f"Открыто {launched} браузеров. Войдите вручную и обновите статусы.",
            )
        else:
            QMessageBox.warning(
                self,
                "Ошибка",
                "Не удалось открыть браузеры для визуального парсинга.",
            )
    
    def show_browser_status(self):
        """Показать статус браузеров"""
        if hasattr(self, 'browser_manager') and self.browser_manager:
            self.browser_manager.show_status()
        else:
            QMessageBox.information(self, "Статус", "Браузеры не запущены")
    
    def update_browser_status(self):
        """Обновить статусы залогинены ли браузеры"""
        if hasattr(self, 'browser_manager') and self.browser_manager:
            QMessageBox.information(self, "Статус", "Проверка статусов...")
            # TODO: реализовать проверку через browser_manager
        else:
            QMessageBox.warning(self, "Внимание", "Браузеры не запущены")
    
    def minimize_all_browsers(self):
        """Минимизировать все браузеры"""
        if hasattr(self, 'browser_manager') and self.browser_manager:
            try:
                # TODO: реализовать минимизацию в browser_manager
                QMessageBox.information(self, "Готово", "Функция в разработке")
            except Exception as e:
                QMessageBox.warning(self, "Ошибка", str(e))
        else:
            QMessageBox.warning(self, "Внимание", "Браузеры не запущены")
    
    def close_all_browsers(self):
        """Закрыть все открытые браузеры (и через BrowserFactory, и через VisualBrowserManager)."""
        closed = False

        if self._browser_handles:
            for handle in list(self._browser_handles):
                try:
                    handle.release_cb()
                except Exception:
                    pass
            self._browser_handles.clear()
            closed = True

        if hasattr(self, 'browser_manager') and self.browser_manager:
            reply = QMessageBox.question(
                self,
                "Подтверждение",
                "Закрыть все браузеры?",
                QMessageBox.Yes | QMessageBox.No,
            )

            if reply == QMessageBox.Yes:
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.browser_manager.close_all())
                    self.browser_manager = None
                    QMessageBox.information(self, "Готово", "Браузеры закрыты")
                    closed = True
                except Exception as e:
                    QMessageBox.warning(self, "Ошибка", f"Ошибка при закрытии: {e}")

        if not closed:
            QMessageBox.information(self, "Информация", "Браузеры не запущены")
    
    def on_table_double_click(self, item):
        """Обработчик двойного клика по ячейке таблицы"""
        column = self.table.currentColumn()
        
        # Если клик по колонке "Куки" (индекс 7)
        if column == 7:
            self.edit_cookies()
        else:
            self.edit_account()
    
    def edit_cookies(self, row):
        """Редактировать куки для аккаунта"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QLabel

        account = self._accounts[row]
        profile_path_str = self._normalize_profile_path(account.profile_path, account.name)
        profile_path = Path(profile_path_str)
        
        # Создаем диалог
        dialog = QDialog(self)
        dialog.setWindowTitle("Управление куками Wordstat")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # Информация
        info = QLabel(f"""
<b>Важные куки для Wordstat:</b><br>
• sessionid2 - основная сессия<br>
• yandex_login - логин пользователя<br>
• yandexuid - ID пользователя<br>
• L - токен авторизации<br>
<br>
<b>Профиль:</b> {account.name}<br>
<b>Путь:</b> {profile_path_str}
        """)
        layout.addWidget(info)
        
        # Поле для ввода куков
        cookies_edit = QTextEdit()
        cookies_edit.setPlaceholderText(
            "Вставьте куки в формате:\n"
            "sessionid2=value1; yandex_login=value2; L=value3"
        )
        
        # Пытаемся прочитать текущие куки (упрощенно)
        cookies_file = profile_path / "Default" / "Cookies"
        if cookies_file.exists():
            cookies_edit.setPlainText(f"Файл куков существует: {cookies_file}\nРазмер: {cookies_file.stat().st_size} bytes\n\n[Для редактирования куков используйте браузер]")
        
        layout.addWidget(cookies_edit)
        
        # Кнопки
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            # Здесь можно добавить логику сохранения куков
            # Но безопаснее логиниться через браузер
            QMessageBox.information(self, "Информация", 
                "Для изменения куков откройте браузер с этим профилем,\n"
                "войдите в Яндекс вручную или используйте кнопку 'Автологин'.")

    def _update_profile(self, account_id, profile_key, account_name: Optional[str] = None):
        """Обновить профиль для аккаунта"""
        normalized_name = account_name if account_name else ""
        profile_path = self._normalize_profile_path(profile_key, normalized_name)
        account_service.update_account(account_id, profile_path=profile_path)
        print(f"[Accounts] Профиль для аккаунта {account_id} изменён на {profile_path}")

    def _handle_item_changed(self, item):
        """Отслеживаем изменение профиля через делегат."""
        if item.column() != PROFILE_SELECT_COLUMN or not self._accounts:
            return
        row = item.row()
        if row < 0 or row >= len(self._accounts):
            return
        account = self._accounts[row]
        profile_value = (item.data(Qt.EditRole) or item.text() or "").strip()
        normalized_path = self._normalize_profile_path(profile_value, account.name)
        options = self._profile_options(account)
        label = self._profile_label(options, normalized_path)
        self.table.blockSignals(True)
        item.setData(Qt.DisplayRole, label)
        item.setData(Qt.EditRole, normalized_path)
        item.setText(label)
        self.table.blockSignals(False)
        account.profile_path = normalized_path
        self._update_profile(account.id, normalized_path, account.name)
        
    def on_table_double_click(self, row, col):
        """Обработка двойного клика по таблице"""
        # Если кликнули по колонке куков - открываем диалог редактирования
        if col == 8:  # Колонка куков
            self.edit_cookies(row)
            
    def edit_cookies(self, row):
        """Редактировать куки для аккаунта"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QLabel

        account = self._accounts[row]
        profile_path_str = self._normalize_profile_path(account.profile_path, account.name)
        profile_path = Path(profile_path_str)

        dialog = QDialog(self)
        dialog.setWindowTitle("Управление куками Wordstat")
        dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(dialog)

        info = QLabel(f"""
<b>Важные куки для Wordstat:</b><br>
• sessionid2 - основная сессия<br>
• yandex_login - логин пользователя<br>
• yandexuid - ID пользователя<br>
• L - токен авторизации<br>
<br>
<b>Профиль:</b> {account.name}<br>
<b>Путь:</b> {profile_path_str}
        """)
        layout.addWidget(info)

        cookies_edit = QTextEdit()
        cookies_edit.setPlaceholderText(
            "Вставьте куки в формате:\n"
            "sessionid2=value1; yandex_login=value2; L=value3"
        )

        cookies_file = profile_path / "Default" / "Cookies"
        if cookies_file.exists():
            cookies_edit.setPlainText(
                f"Файл куков существует: {cookies_file}\n"
                f"Размер: {cookies_file.stat().st_size} bytes\n\n"
                "[Для редактирования куков используйте браузер]"
            )

        layout.addWidget(cookies_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            QMessageBox.information(
                self,
                "Информация",
                "Для изменения куков откройте браузер с этим профилем,\n"
                "войдите в Яндекс вручную или используйте кнопку 'Автологин'."
            )
            
    def open_chrome_with_profile(self):
        """Открыть Chrome с профилем выбранного аккаунта"""
        import subprocess
        
        selected = self._selected_rows()
        if not selected:
            QMessageBox.warning(self, "Внимание", "Выберите аккаунт для открытия Chrome")
            return
            
        if len(selected) > 1:
            QMessageBox.warning(self, "Внимание", "Выберите только один аккаунт")
            return
            
        account = self._accounts[selected[0]]
        
        # Определяем профиль
        base_dir = Path("C:/AI/yandex")
        profile_path = account.profile_path or f".profiles/{account.name}"
        profile_path_obj = Path(profile_path)
        if not profile_path_obj.is_absolute():
            profile_path_obj = base_dir / profile_path_obj
        profile_path = str(profile_path_obj).replace("\\", "/")
            
        # Запускаем Chrome
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        
        try:
            subprocess.Popen([
                chrome_path,
                f"--user-data-dir={profile_path}",
                "--new-window",
                "https://wordstat.yandex.ru"
            ])
            
            self.log_action(f"Chrome запущен с профилем: {profile_path.split('/')[-1]}")
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось запустить Chrome: {str(e)}")
        
    def _get_cookies_status(self, account):
        """Получить статус куков для аккаунта (используем функцию из файла 42)"""
        # Используем функцию get_cookies_status() из services/accounts.py
        return get_cookies_status(account)




