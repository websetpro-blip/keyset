# -*- coding: utf-8 -*-
"""
Р Р°СЃС€РёСЂРµРЅРЅР°СЏ РІРєР»Р°РґРєР° СѓРїСЂР°РІР»РµРЅРёСЏ Р°РєРєР°СѓРЅС‚Р°РјРё СЃ С„СѓРЅРєС†РёРµР№ Р»РѕРіРёРЅР°

РџР РђР’РР›Рћ в„–1: РќР• Р›РћРњРђРўР¬ РўРћ Р§РўРћ Р РђР‘РћРўРђР•Рў!
- РќРµ СѓРґР°Р»СЏС‚СЊ СЂР°Р±РѕС‡РёРµ С„СѓРЅРєС†РёРё
- РќРµ РёР·РјРµРЅСЏС‚СЊ СЂР°Р±РѕС‚Р°СЋС‰СѓСЋ Р»РѕРіРёРєСѓ
- РќРµ С‚СЂРѕРіР°С‚СЊ С‚Рѕ, С‡С‚Рѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊ РЅРµ РїСЂРѕСЃРёР» РјРµРЅСЏС‚СЊ
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
# РЎС‚Р°СЂС‹Р№ worker Р±РѕР»СЊС€Рµ РЅРµ РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ, С‚РµРїРµСЂСЊ CDP РїРѕРґС…РѕРґ

PROFILE_SELECT_COLUMN = 5
PROFILE_OPTIONS_ROLE = Qt.UserRole + 101
PROXY_SELECT_COLUMN = 6
PROXY_NONE_LABEL = "вЂ” Р‘РµР· РїСЂРѕРєСЃРё вЂ”"


class ProfileComboDelegate(QStyledItemDelegate):
    """Р”РµР»РµРіР°С‚ РґР»СЏ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ РїСЂРѕС„РёР»РµР№ Р°РєРєР°СѓРЅС‚РѕРІ (ComboBox)."""

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
    """РџРѕС‚РѕРє РґР»СЏ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРѕР№ Р°РІС‚РѕСЂРёР·Р°С†РёРё Р°РєРєР°СѓРЅС‚Р°"""
    status_signal = Signal(str)  # РЎС‚Р°С‚СѓСЃ РѕРїРµСЂР°С†РёРё
    progress_signal = Signal(int)  # РџСЂРѕРіСЂРµСЃСЃ 0-100
    secret_question_signal = Signal(str, str)  # account_name, question_text
    finished_signal = Signal(bool, str)  # success, message
    
    def __init__(self, account, parent=None):
        super().__init__(parent)
        self.account = account
        self.secret_answer = None
        
    def set_secret_answer(self, answer):
        """РЈСЃС‚Р°РЅРѕРІРёС‚СЊ РѕС‚РІРµС‚ РЅР° СЃРµРєСЂРµС‚РЅС‹Р№ РІРѕРїСЂРѕСЃ"""
        self.secret_answer = answer
        
    def run(self):
        """Р—Р°РїСѓСЃРє СѓРјРЅРѕРіРѕ Р°РІС‚РѕР»РѕРіРёРЅР° РЅР° РѕСЃРЅРѕРІРµ СЂРµС€РµРЅРёСЏ GPT"""
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

        # вљ пёЏ РџР РћР’Р•Р РљРђ: РџСЂРѕС„РёР»СЊ Р”РћР›Р¶РµРќ Р±С‹С‚СЊ РёР· Р‘Р”!
        if not profile_path:
            self.status_signal.emit(f"[ERROR] РЈ Р°РєРєР°СѓРЅС‚Р° {self.account.name} РќР•Рў profile_path РІ Р‘Р”!")
            self.finished_signal.emit(False, "РџСЂРѕС„РёР»СЊ РЅРµ СѓРєР°Р·Р°РЅ РІ Р‘Р”")
            return

        self.status_signal.emit(f"[OK] РџСЂРѕС„РёР»СЊ Р С‘Р В· Р 'Р ]: {profile_path}")

        base_dir = Path("C:/AI/yandex")
        profile_path_obj = Path(profile_path)
        if not profile_path_obj.is_absolute():
            profile_path_obj = base_dir / profile_path_obj
        profile_path = str(profile_path_obj).replace("\\", "/")
        self.status_signal.emit(f"[INFO] РСЃРїРѕР»СЊР·СѓРµРј РїСЂРѕС„РёР»СЊ: {profile_path}")

        accounts_file = Path("C:/AI/yandex/configs/accounts.json")
        if not accounts_file.exists():
            self.status_signal.emit(f"[ERROR] Р¤Р°Р№Р» accounts.json РЅРµ РЅР°Р№РґРµРЅ!")
            self.finished_signal.emit(False, "Р¤Р°Р№Р» accounts.json РЅРµ РЅР°Р№РґРµРЅ")
            return

        with open(accounts_file, 'r', encoding='utf-8') as f:
            accounts_data = json.load(f)
            account_info = None
            for acc in accounts_data:
                if acc["login"] == self.account.name:
                    account_info = acc
                    break

        if not account_info:
            self.status_signal.emit(f"[ERROR] РђРєРєР°СѓРЅС‚ {self.account.name} РЅРµ РЅР°Р№РґРµРЅ РІ accounts.json!")
            self.finished_signal.emit(False, f"РђРєРєР°СѓРЅС‚ РЅРµ РЅР°Р№РґРµРЅ РІ accounts.json")
            return

        self.status_signal.emit(f"[CDP] Р—Р°РїСѓСЃРє Р°РІС‚РѕР»РѕРіРёРЅР° РґР»СЏ {self.account.name}...")

        secret_answer = self.secret_answer
        if not secret_answer and "secret" in account_info and account_info["secret"]:
            secret_answer = account_info["secret"]
            self.status_signal.emit(f"[CDP] РќР°Р№РґРµРЅ СЃРѕС…СЂР°РЅРµРЅРЅС‹Р№ РѕС‚РІРµС‚ РЅР° СЃРµРєСЂРµС‚РЅС‹Р№ РІРѕРїСЂРѕСЃ")

        port = 9222 + (hash(self.account.name) % 100)
        self.status_signal.emit(f"[CDP] РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РїРѕСЂС‚ {port} РґР»СЏ {self.account.name}")

        smart_login = YandexSmartLogin()
        smart_login.status_update.connect(self.status_signal.emit)
        smart_login.progress_update.connect(self.progress_signal.emit)
        smart_login.secret_question_required.connect(self.secret_question_signal.emit)

        if secret_answer:
            smart_login.set_secret_answer(secret_answer)

        proxy_to_use = account_info.get("proxy", None)
        if proxy_to_use:
            self.status_signal.emit(f"[INFO] РСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ РїСЂРѕРєСЃРё: {proxy_to_use.split('@')[0]}@***")

        self.status_signal.emit(f"[SMART] Р—Р°РїСѓСЃРєР°СЋ Р°РІС‚РѕР»РѕРіРёРЅ...")
        success = await smart_login.login(
            account_name=self.account.name,
            profile_path=profile_path,
            proxy=proxy_to_use
        )

        if success:
            self.status_signal.emit(f"[OK] РђРІС‚РѕР»РѕРіРёРЅ СѓСЃРїРµС€РµРЅ РґР»СЏ {self.account.name}!")
            self.finished_signal.emit(True, "РђРІС‚РѕСЂРёР·Р°С†РёСЏ СѓСЃРїРµС€РЅР°")
        else:
            self.status_signal.emit(f"[ERROR] РђРІС‚РѕР»РѕРіРёРЅ РЅРµ СѓРґР°Р»СЃСЏ РґР»СЏ {self.account.name}")
            self.finished_signal.emit(False, "РћС€РёР±РєР° Р°РІС‚РѕСЂРёР·Р°С†РёРё")


class LoginWorkerThread(QThread):
    """РџРѕС‚РѕРє РґР»СЏ Р»РѕРіРёРЅР° РІ Р±СЂР°СѓР·РµСЂС‹"""
    progress_signal = Signal(str)  # РЎРѕРѕР±С‰РµРЅРёРµ Рѕ РїСЂРѕРіСЂРµСЃСЃРµ
    account_logged_signal = Signal(int, bool, str)  # account_id, success, message
    finished_signal = Signal(bool, str)  # success, message
    
    def __init__(self, accounts_to_login, parent=None, check_only=False, visual_mode=False):
        super().__init__(parent)
        self.accounts = accounts_to_login
        self.manager = None
        self.check_only = check_only  # РўРѕР»СЊРєРѕ РїСЂРѕРІРµСЂРєР° Р±РµР· РѕС‚РєСЂС‹С‚РёСЏ Р±СЂР°СѓР·РµСЂРѕРІ
        self.visual_mode = visual_mode  # Р’РёР·СѓР°Р»СЊРЅС‹Р№ СЂРµР¶РёРј - РІСЃРµРіРґР° РѕС‚РєСЂС‹РІР°С‚СЊ Р±СЂР°СѓР·РµСЂС‹
        self.proxy_manager = ProxyManager.instance()

    def _build_proxy_payload(self, account) -> Tuple[Optional[Dict[str, str]], Optional[str], Optional[str]]:
        """Готовит прокси-конфиг для аккаунта: (playwright_config, proxy_uri, proxy_id)."""
        proxy_id = getattr(account, "proxy_id", None)
        if proxy_id:
            proxy_obj = self.proxy_manager.get(proxy_id)
            if proxy_obj:
                cfg = proxy_obj.playwright_config()
                server = cfg.get("server")
                if server and "://" not in server:
                    cfg["server"] = f"http://{server}"
                return cfg, proxy_obj.uri(include_credentials=True), proxy_obj.id

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

    def run(self):
        """Р—Р°РїСѓСЃРє Р»РѕРіРёРЅР° РІ РѕС‚РґРµР»СЊРЅРѕРј РїРѕС‚РѕРєРµ"""
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
        """Р›РѕРіРёРЅ РІ Р°РєРєР°СѓРЅС‚С‹"""
        from ..workers.auth_checker import AuthChecker
        
        # РћС‚Р»Р°РґРєР° - РїРѕРєР°Р·С‹РІР°РµРј СЃРєРѕР»СЊРєРѕ Р°РєРєР°СѓРЅС‚РѕРІ РїРѕР»СѓС‡РёР»Рё
        self.progress_signal.emit(f"Received {len(self.accounts)} accounts for processing")
        self.progress_signal.emit(f"Accounts: {[acc.name if hasattr(acc, 'name') else str(acc) for acc in self.accounts]}")
        
        self.progress_signal.emit(f"Checking authorization for {len(self.accounts)} accounts...")
        
        # РЎРЅР°С‡Р°Р»Р° РїСЂРѕРІРµСЂСЏРµРј Р°РІС‚РѕСЂРёР·Р°С†РёСЋ С‡РµСЂРµР· Wordstat
        auth_checker = AuthChecker()
        accounts_to_check = []
        
        for acc in self.accounts:
            # РСЃРїРѕР»СЊР·СѓРµРј Р°Р±СЃРѕР»СЋС‚РЅС‹Рµ РїСѓС‚Рё РґР»СЏ Windows
            if acc.profile_path:
                profile = str(Path(acc.profile_path).absolute()).replace("\\", "/")
            else:
                profile = str(Path(f"C:/AI/yandex/.profiles/{acc.name}").absolute()).replace("\\", "/")
            _, proxy_uri, proxy_id = self._build_proxy_payload(acc)
            accounts_to_check.append({
                "name": acc.name,
                "profile_path": profile,
                "proxy": proxy_uri or acc.proxy,
                "proxy_id": proxy_id,
                "account_id": acc.id
            })
        
        # РџСЂРѕРІРµСЂСЏРµРј Р°РІС‚РѕСЂРёР·Р°С†РёСЋ
        self.progress_signal.emit("Testing authorization via Wordstat...")
        auth_results = await auth_checker.check_multiple_accounts(accounts_to_check)
        
        # Р¤РёР»СЊС‚СЂСѓРµРј РєС‚Рѕ РЅСѓР¶РґР°РµС‚СЃСЏ РІ Р»РѕРіРёРЅРµ
        need_login = []
        already_authorized = []
        
        for acc_data in accounts_to_check:
            acc_name = acc_data["name"]
            result = auth_results.get(acc_name, {})
            
            if result.get("is_authorized"):
                already_authorized.append(acc_name)
                self.progress_signal.emit(f"[OK] {acc_name}: Already authorized")
                # РћР±РЅРѕРІР»СЏРµРј СЃС‚Р°С‚СѓСЃ РІ Р‘Р”
                self.account_logged_signal.emit(acc_data["account_id"], True, "Authorized")
            else:
                need_login.append(acc_data)
                self.progress_signal.emit(f"[!] {acc_name}: Login required")
        
        if already_authorized:
            self.progress_signal.emit(f"Authorized: {', '.join(already_authorized)}")
        
        if not need_login:
            self.progress_signal.emit("All accounts are authorized!")
            # Р’ РІРёР·СѓР°Р»СЊРЅРѕРј СЂРµР¶РёРјРµ РѕС‚РєСЂС‹РІР°РµРј Р±СЂР°СѓР·РµСЂС‹ РґР°Р¶Рµ РµСЃР»Рё РІСЃРµ Р°РІС‚РѕСЂРёР·РѕРІР°РЅС‹
            if self.visual_mode:
                self.progress_signal.emit("Opening browsers for visual parsing...")
                need_login = accounts_to_check  # РћС‚РєСЂС‹РІР°РµРј Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ РІСЃРµС… Р°РєРєР°СѓРЅС‚РѕРІ
            elif not self.check_only:
                self.progress_signal.emit("Opening browsers for visual parsing...")
                need_login = accounts_to_check  # РћС‚РєСЂС‹РІР°РµРј Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ РІСЃРµС… Р°РєРєР°СѓРЅС‚РѕРІ
            else:
                self.finished_signal.emit(True, f"All {len(self.accounts)} accounts are authorized")
                return
        
        # Р•СЃР»Рё РµСЃС‚СЊ РєС‚Рѕ С‚СЂРµР±СѓРµС‚ Р»РѕРіРёРЅР° РёР»Рё РЅСѓР¶РЅС‹ Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ РїР°СЂСЃРёРЅРіР°
        if not self.check_only:
            self.progress_signal.emit(f"Opening {len(need_login)} browsers...")
            
            # РЎРѕР·РґР°РµРј РјРµРЅРµРґР¶РµСЂ Р±СЂР°СѓР·РµСЂРѕРІ
            self.manager = VisualBrowserManager(num_browsers=len(need_login))
            
            try:
                # Р—Р°РїСѓСЃРєР°РµРј Р±СЂР°СѓР·РµСЂС‹ С‚РѕР»СЊРєРѕ РґР»СЏ С‚РµС… РєС‚Рѕ РЅРµ Р°РІС‚РѕСЂРёР·РѕРІР°РЅ
                await self.manager.start_all_browsers(need_login)
                
                self.progress_signal.emit("Browsers opened. Waiting for login...")
                self.progress_signal.emit("Please login in each opened browser!")
                
                # Р–РґРµРј Р»РѕРіРёРЅР°
                logged_in = await self.manager.wait_for_all_logins(timeout=300)
                
                if logged_in:
                    # РћР±РЅРѕРІР»СЏРµРј СЃС‚Р°С‚СѓСЃ Р°РєРєР°СѓРЅС‚РѕРІ
                    for browser_id, browser in self.manager.browsers.items():
                        if browser.status == BrowserStatus.LOGGED_IN:
                            # РќР°С…РѕРґРёРј account_id РёР· need_login
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
    """Р Р°СЃС€РёСЂРµРЅРЅР°СЏ РІРєР»Р°РґРєР° Р°РєРєР°СѓРЅС‚РѕРІ СЃ С„СѓРЅРєС†РёРµР№ Р»РѕРіРёРЅР°"""
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
        """РЎРѕР·РґР°РЅРёРµ РёРЅС‚РµСЂС„РµР№СЃР°"""
        layout = QVBoxLayout(self)
        
        # Р’РµСЂС…РЅСЏСЏ РїР°РЅРµР»СЊ СЃ РєРЅРѕРїРєР°РјРё СѓРїСЂР°РІР»РµРЅРёСЏ
        buttons_layout = QHBoxLayout()
        
        # РЎС‚Р°РЅРґР°СЂС‚РЅС‹Рµ РєРЅРѕРїРєРё
        self.add_btn = QPushButton("вћ• Р”РѕР±Р°РІРёС‚СЊ")
        self.add_btn.clicked.connect(self.add_account)
        buttons_layout.addWidget(self.add_btn)
        
        self.edit_btn = QPushButton("вњЏпёЏ РР·РјРµРЅРёС‚СЊ")
        self.edit_btn.clicked.connect(self.edit_account)
        self.edit_btn.setEnabled(False)
        buttons_layout.addWidget(self.edit_btn)
        
        self.delete_btn = QPushButton("рџ—‘пёЏ РЈРґР°Р»РёС‚СЊ")
        self.delete_btn.clicked.connect(self.delete_account)
        self.delete_btn.setEnabled(False)
        buttons_layout.addWidget(self.delete_btn)
        
        self.import_btn = QPushButton("рџ“Ґ РРјРїРѕСЂС‚")
        self.import_btn.clicked.connect(self.import_accounts)
        buttons_layout.addWidget(self.import_btn)
        
        buttons_layout.addStretch()
        
        # РќРѕРІС‹Рµ РєРЅРѕРїРєРё РґР»СЏ Р»РѕРіРёРЅР°
        self.login_btn = QPushButton("рџ”ђ Р’РѕР№С‚Рё")
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
        
        # РљРЅРѕРїРєР° Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРѕРіРѕ Р»РѕРіРёРЅР°
        self.auto_login_btn = QPushButton("РђРІС‚РѕР»РѕРіРёРЅ")
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
        self.auto_login_btn.setToolTip("РђРІС‚РѕРјР°С‚РёС‡РµСЃРєР°СЏ Р°РІС‚РѕСЂРёР·Р°С†РёСЏ СЃ РІРІРѕРґРѕРј Р»РѕРіРёРЅР° Рё РїР°СЂРѕР»СЏ")
        buttons_layout.addWidget(self.auto_login_btn)
        
        self.login_all_btn = QPushButton("рџ”ђ Р’РѕР№С‚Рё РІРѕ РІСЃРµ")
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
        
        self.refresh_btn = QPushButton("рџ”„ РћР±РЅРѕРІРёС‚СЊ")
        self.refresh_btn.clicked.connect(self.refresh)
        buttons_layout.addWidget(self.refresh_btn)
        
        # РљРЅРѕРїРєР° Proxy Manager
        self.test_proxy_btn = QPushButton("рџ”Њ РџСЂРѕРєСЃРё-РјРµРЅРµРґР¶РµСЂ")
        self.test_proxy_btn.clicked.connect(self.open_proxy_manager)
        self.test_proxy_btn.setEnabled(True)  # Р’СЃРµРіРґР° РґРѕСЃС‚СѓРїРЅР°
        self.test_proxy_btn.setToolTip("РћС‚РєСЂС‹С‚СЊ Proxy Manager РґР»СЏ РјР°СЃСЃРѕРІРѕР№ РїСЂРѕРІРµСЂРєРё")
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
        
        # РљРЅРѕРїРєР° РїСЂРѕРІРµСЂРєРё Р±Р°Р»Р°РЅСЃР° РєР°РїС‡Рё
        self.check_captcha_btn = QPushButton("рџЋ« Р‘Р°Р»Р°РЅСЃ РєР°РїС‡Рё")
        self.check_captcha_btn.clicked.connect(self.check_captcha_balance)
        self.check_captcha_btn.setToolTip("РџСЂРѕРІРµСЂРёС‚СЊ Р±Р°Р»Р°РЅСЃ RuCaptcha")
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
        
        # РџР°РЅРµР»СЊ СѓРїСЂР°РІР»РµРЅРёСЏ Р±СЂР°СѓР·РµСЂР°РјРё
        browser_panel = QGroupBox("Browser Management")
        browser_layout = QHBoxLayout()
        
        self.open_browsers_btn = QPushButton("рџЊђ РћС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ Р»РѕРіРёРЅР°")
        self.open_browsers_btn.clicked.connect(self.open_browsers_for_login)
        self.open_browsers_btn.setToolTip("РћС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹ С‚РѕР»СЊРєРѕ РґР»СЏ С‚РµС… Р°РєРєР°СѓРЅС‚РѕРІ, РіРґРµ РЅСѓР¶РµРЅ Р»РѕРіРёРЅ")
        browser_layout.addWidget(self.open_browsers_btn)
        
        self.browser_status_btn = QPushButton("рџ“Љ РЎРѕСЃС‚РѕСЏРЅРёРµ Р±СЂР°СѓР·РµСЂРѕРІ")
        self.browser_status_btn.clicked.connect(self.show_browser_status)
        self.browser_status_btn.setToolTip("РџРѕРєР°Р·Р°С‚СЊ СЃС‚Р°С‚СѓСЃ РІСЃРµС… РѕС‚РєСЂС‹С‚С‹С… Р±СЂР°СѓР·РµСЂРѕРІ")
        browser_layout.addWidget(self.browser_status_btn)
        
        self.update_status_btn = QPushButton("рџ”„ РћР±РЅРѕРІРёС‚СЊ СЃС‚Р°С‚СѓСЃС‹")
        self.update_status_btn.clicked.connect(self.update_browser_status)
        self.update_status_btn.setToolTip("РџСЂРѕРІРµСЂРёС‚СЊ Р·Р°Р»РѕРіРёРЅРµРЅС‹ Р»Рё Р±СЂР°СѓР·РµСЂС‹")
        browser_layout.addWidget(self.update_status_btn)
        
        self.minimize_browsers_btn = QPushButton("рџ“‰ РњРёРЅРёРјРёР·РёСЂРѕРІР°С‚СЊ Р±СЂР°СѓР·РµСЂС‹")
        self.minimize_browsers_btn.clicked.connect(self.minimize_all_browsers)
        self.minimize_browsers_btn.setToolTip("РЎРІРµСЂРЅСѓС‚СЊ РІСЃРµ Р±СЂР°СѓР·РµСЂС‹ РІ РїР°РЅРµР»СЊ Р·Р°РґР°С‡")
        browser_layout.addWidget(self.minimize_browsers_btn)
        
        self.close_browsers_btn = QPushButton("вќЊ Р—Р°РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹")
        self.close_browsers_btn.clicked.connect(self.close_all_browsers)
        self.close_browsers_btn.setToolTip("Р—Р°РєСЂС‹С‚СЊ РІСЃРµ РѕС‚РєСЂС‹С‚С‹Рµ Р±СЂР°СѓР·РµСЂС‹")
        browser_layout.addWidget(self.close_browsers_btn)
        
        browser_panel.setLayout(browser_layout)
        layout.addWidget(browser_panel)
        
        # Р‘СЂР°СѓР·РµСЂ РјРµРЅРµРґР¶РµСЂ
        self.browser_manager = None
        self.browser_thread = None
        
        # РўР°Р±Р»РёС†Р° Р°РєРєР°СѓРЅС‚РѕРІ
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels([
            "вњ“",  # Р§РµРєР±РѕРєСЃ
            "РђРєРєР°СѓРЅС‚",
            "РЎС‚Р°С‚СѓСЃ",
            "РђРІС‚РѕСЂРёР·Р°С†РёСЏ",  # РР·РјРµРЅРµРЅРѕ СЃ "Р›РѕРіРёРЅ"
            "РџСЂРѕС„РёР»СЊ",
            "Р’С‹Р±РѕСЂ РїСЂРѕС„РёР»СЏ",  # Р”РѕР±Р°РІР»РµРЅРѕ - РІС‹Р±РѕСЂ РїСЂРѕС„РёР»СЏ РґР»СЏ РїР°СЂСЃРёРЅРіР°
            "РџСЂРѕРєСЃРё",
            "РђРєС‚РёРІРЅРѕСЃС‚СЊ",  # РР·РјРµРЅРµРЅРѕ СЃ "РџРѕСЃР»РµРґРЅРµРµ РёСЃРїРѕР»СЊР·РѕРІР°РЅРёРµ"
            "РљСѓРєРё"  # РР·РјРµРЅРµРЅРѕ СЃ "Р—Р°РјРµС‚РєРё" - РґР»СЏ СЂСѓС‡РЅРѕРіРѕ РІРІРѕРґР° РєСѓРєРѕРІ
        ])
        self.table.setItemDelegateForColumn(PROFILE_SELECT_COLUMN, ProfileComboDelegate())
        
        # РћР±СЂР°Р±РѕС‚С‡РёРє РґРІРѕР№РЅРѕРіРѕ РєР»РёРєР°
        self.table.cellDoubleClicked.connect(self.on_table_double_click)
        
        # Р”РѕР±Р°РІР»СЏРµРј С‡РµРєР±РѕРєСЃ "Р’С‹Р±СЂР°С‚СЊ РІСЃРµ" РІ Р·Р°РіРѕР»РѕРІРѕРє
        self.select_all_checkbox = QCheckBox()
        self.select_all_checkbox.stateChanged.connect(self.toggle_select_all)
        # РЈСЃС‚Р°РЅРѕРІРёРј С‡РµРєР±РѕРєСЃ РІ Р·Р°РіРѕР»РѕРІРѕРє РїРѕСЃР»Рµ СЃРѕР·РґР°РЅРёСЏ СЃС‚СЂРѕРє РІ refresh()
        
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
        
        # РЈР±СЂР°Р»Рё Р»РѕРєР°Р»СЊРЅС‹Р№ Status and Activity - РёСЃРїРѕР»СЊР·СѓРµРј РіР»Р°РІРЅС‹Р№ Р¶СѓСЂРЅР°Р» РІРЅРёР·Сѓ (С„Р°Р№Р» 45)
        
        # РРЅРёС†РёР°Р»РёР·Р°С†РёСЏ
        self._accounts = []
        self.refresh()
    
    def toggle_select_all(self, state):
        """РџРµСЂРµРєР»СЋС‡РёС‚СЊ РІС‹Р±РѕСЂ РІСЃРµС… Р°РєРєР°СѓРЅС‚РѕРІ"""
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if checkbox:
                checkbox.setChecked(state == 2)  # 2 = Qt.Checked
        self.log_action(f"{'Р’С‹Р±СЂР°РЅС‹' if state == 2 else 'РЎРЅСЏС‚С‹'} РІСЃРµ Р°РєРєР°СѓРЅС‚С‹")
    
    def log_action(self, message):
        """Р”РѕР±Р°РІРёС‚СЊ СЃРѕРѕР±С‰РµРЅРёРµ РІ РіР»Р°РІРЅС‹Р№ Р¶СѓСЂРЅР°Р» (С„Р°Р№Р» 45)"""
        # Р›РѕРіРёСЂСѓРµРј С‡РµСЂРµР· РіР»Р°РІРЅРѕРµ РѕРєРЅРѕ
        main_window = self.window()
        if hasattr(main_window, 'log_message'):
            main_window.log_message(message, "INFO")
    
    def _selected_rows(self) -> List[int]:
        """РџРѕР»СѓС‡РёС‚СЊ РІС‹Р±СЂР°РЅРЅС‹Рµ СЃС‚СЂРѕРєРё"""
        selected = []
        for row in range(self.table.rowCount()):
            checkbox = self.table.cellWidget(row, 0)
            if checkbox and checkbox.isChecked():
                selected.append(row)
        return selected
    
    def _current_account(self) -> Optional[Any]:
        """РџРѕР»СѓС‡РёС‚СЊ С‚РµРєСѓС‰РёР№ РІС‹Р±СЂР°РЅРЅС‹Р№ Р°РєРєР°СѓРЅС‚"""
        row = self.table.currentRow()
        if 0 <= row < len(self._accounts):
            return self._accounts[row]
        return None
    
    def _update_buttons(self):
        """РћР±РЅРѕРІРёС‚СЊ СЃРѕСЃС‚РѕСЏРЅРёРµ РєРЅРѕРїРѕРє"""
        has_selection = self._current_account() is not None
        self.edit_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        
        selected_rows = self._selected_rows()
        self.login_btn.setEnabled(len(selected_rows) > 0)
        # РђРІС‚РѕР»РѕРіРёРЅ СЂР°Р±РѕС‚Р°РµС‚ С‚РѕР»СЊРєРѕ РґР»СЏ РѕРґРЅРѕРіРѕ РІС‹Р±СЂР°РЅРЅРѕРіРѕ Р°РєРєР°СѓРЅС‚Р°
        self.auto_login_btn.setEnabled(len(selected_rows) == 1)
        # Proxy Manager РІСЃРµРіРґР° РґРѕСЃС‚СѓРїРµРЅ
        # self.test_proxy_btn.setEnabled(True)  # РЈР±СЂР°Р»Рё, С‚.Рє. РІСЃРµРіРґР° True
    
    def refresh(self):
        """РћР±РЅРѕРІРёС‚СЊ С‚Р°Р±Р»РёС†Сѓ Р°РєРєР°СѓРЅС‚РѕРІ"""
        # РџРѕР»СѓС‡Р°РµРј Р°РєРєР°СѓРЅС‚С‹ Рё С„РёР»СЊС‚СЂСѓРµРј demo_account
        all_accounts = account_service.list_accounts()
        self._accounts = [acc for acc in all_accounts if acc.name != "demo_account"]
        self.table.setRowCount(len(self._accounts))
        self._reload_proxy_cache()

        self.log_action(f"Р—Р°РіСЂСѓР¶РµРЅРѕ: {len(self._accounts)} Р°РєРєР°СѓРЅС‚РѕРІ")

        self.table.blockSignals(True)
        for row, account in enumerate(self._accounts):
            # Р§РµРєР±РѕРєСЃ
            checkbox = QCheckBox()
            checkbox.stateChanged.connect(self._update_buttons)
            self.table.setCellWidget(row, 0, checkbox)
            
            # Р”Р°РЅРЅС‹Рµ Р°РєРєР°СѓРЅС‚Р°
            items = [
                QTableWidgetItem(account.name),
                QTableWidgetItem(self._get_status_label(account.status)),
                QTableWidgetItem(self._get_auth_status(account)),  # РР·РјРµРЅРµРЅРѕ
                QTableWidgetItem(account.profile_path or f".profiles/{account.name}"),
                None,  # Р”Р»СЏ РєРѕРјР±РѕР±РѕРєСЃР°
                None,  # Р—Р°РїРѕР»РЅРёРј РєРѕРјР±РѕР±РѕРєСЃРѕРј РїСЂРѕРєСЃРё
                QTableWidgetItem(self._get_activity_status(account)),  # РР·РјРµРЅРµРЅРѕ
                QTableWidgetItem(self._get_cookies_status(account))  # РџРѕРєР°Р·С‹РІР°РµРј СЃС‚Р°С‚СѓСЃ РєСѓРєРѕРІ
            ]

            # РЈСЃС‚Р°РЅР°РІР»РёРІР°РµРј СЌР»РµРјРµРЅС‚С‹
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
        """РџСЂРёРІРµСЃС‚Рё Р·РЅР°С‡РµРЅРёРµ РїСЂРѕС„РёР»СЏ Рє Р°Р±СЃРѕР»СЋС‚РЅРѕРјСѓ РїСѓС‚Рё."""
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
        return f"{tail}{hint} вЂ” {path}"

    def _profile_options(self, account):
        """РЎС„РѕСЂРјРёСЂРѕРІР°С‚СЊ СЃРїРёСЃРѕРє РґРѕСЃС‚СѓРїРЅС‹С… РїСЂРѕС„РёР»РµР№ РґР»СЏ Р°РєРєР°СѓРЅС‚Р°."""
        current = self._normalize_profile_path(account.profile_path, account.name)
        options = [(current, self._format_profile_label(current, "(С‚РµРєСѓС‰РёР№)"))]

        personal_default = self._normalize_profile_path(f".profiles/{account.name}", account.name)
        if personal_default not in {opt[0] for opt in options}:
            options.append((personal_default, self._format_profile_label(personal_default)))

        return options

    def _profile_value_from_account(self, account):
        """РћРїСЂРµРґРµР»РёС‚СЊ С‚РµРєСѓС‰РёР№ РїСЂРѕС„РёР»СЊ РёР· РїСѓС‚Рё Р°РєРєР°СѓРЅС‚Р°."""
        return self._normalize_profile_path(account.profile_path, account.name)

    @staticmethod
    def _profile_label(options, value):
        """РџРѕР»СѓС‡РёС‚СЊ РѕС‚РѕР±СЂР°Р¶Р°РµРјСѓСЋ РїРѕРґРїРёСЃСЊ РґР»СЏ Р·РЅР°С‡РµРЅРёСЏ РїСЂРѕС„РёР»СЏ."""
        for option_value, label in options:
            if option_value == value:
                return label
        return AccountsTabExtended._format_profile_label(value)

    # ------------------------------------------------------------------
    # Р Р°Р±РѕС‚Р° СЃ РїСЂРѕРєСЃРё
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

    def _resolve_proxy_payload(self, account) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
        """Возвращает конфиг прокси для Playwright и полноценный URI с учётом учётных данных."""
        proxy_obj = None
        proxy_id = getattr(account, "proxy_id", None)
        if proxy_id:
            proxy_obj = self._proxy_by_id.get(proxy_id) or self._proxy_manager.get(proxy_id)
        elif getattr(account, "proxy", None):
            proxy_obj = self._proxy_by_uri.get(account.proxy)

        if proxy_obj:
            config = proxy_obj.playwright_config()
            server = config.get("server")
            if server and "://" not in server:
                config["server"] = f"http://{server}"
            return config, proxy_obj.uri(include_credentials=True)

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
                return parsed, uri

        return None, None

    def _on_proxy_changed(self, combo: QComboBox) -> None:
        account_id = combo.property("account_id")
        if account_id is None:
            return
        proxy_id = combo.currentData()
        try:
            updated = set_account_proxy(account_id, proxy_id, strategy="fixed")
        except Exception as exc:
            QMessageBox.critical(self, "РћС€РёР±РєР°", f"РќРµ СѓРґР°Р»РѕСЃСЊ РїСЂРёРІСЏР·Р°С‚СЊ РїСЂРѕРєСЃРё: {exc}")
            self.refresh()
            return

        for account in self._accounts:
            if getattr(account, "id", None) == account_id:
                account.proxy_id = updated.proxy_id
                account.proxy = updated.proxy
                account.proxy_strategy = updated.proxy_strategy
                break

        account_name = combo.property("account_name") or account_id
        self.log_action(f"РџСЂРѕРєСЃРё РґР»СЏ {account_name}: {combo.currentText()}")
    
    def _get_status_label(self, status):
        """РџРѕР»СѓС‡РёС‚СЊ РјРµС‚РєСѓ СЃС‚Р°С‚СѓСЃР°"""
        labels = {
            "ok": "Р“РѕС‚РѕРІ",
            "cooldown": "РџР°СѓР·Р°",
            "captcha": "РљР°РїС‡Р°",
            "banned": "Р—Р°Р±Р°РЅРµРЅ",
            "disabled": "РћС‚РєР»СЋС‡РµРЅ",
            "error": "РћС€РёР±РєР°"
        }
        return labels.get(status, status)
    
    def _get_login_status(self, account):
        """РџСЂРѕРІРµСЂРёС‚СЊ СЃС‚Р°С‚СѓСЃ Р»РѕРіРёРЅР°"""
        # РџСЂРѕРІРµСЂСЏРµРј РЅР°Р»РёС‡РёРµ cookies РІ РїСЂРѕС„РёР»Рµ
        profile_path = Path(account.profile_path)
        cookies_file = profile_path / "Default" / "Cookies"
        
        if cookies_file.exists():
            # РџСЂРѕРІРµСЂСЏРµРј РІСЂРµРјСЏ РїРѕСЃР»РµРґРЅРµР№ РјРѕРґРёС„РёРєР°С†РёРё
            mtime = datetime.fromtimestamp(cookies_file.stat().st_mtime)
            age = datetime.now() - mtime
            
            if age.days < 7:  # Cookies СЃРІРµР¶РёРµ (РјРµРЅСЊС€Рµ РЅРµРґРµР»Рё)
                return "вњ… Р—Р°Р»РѕРіРёРЅРµРЅ"
            else:
                return "вљ пёЏ РўСЂРµР±СѓРµС‚ РѕР±РЅРѕРІР»РµРЅРёСЏ"
        return "вќЊ РќРµ Р·Р°Р»РѕРіРёРЅРµРЅ"
    
    def _is_logged_in(self, account):
        """РџСЂРѕРІРµСЂРёС‚СЊ Р·Р°Р»РѕРіРёРЅРµРЅ Р»Рё Р°РєРєР°СѓРЅС‚"""
        # Р’СЃРµРіРґР° РІРѕР·РІСЂР°С‰Р°РµРј False С‡С‚РѕР±С‹ СЂРµР°Р»СЊРЅРѕ РїСЂРѕРІРµСЂРёС‚СЊ С‡РµСЂРµР· Wordstat
        return False
    
    def _format_timestamp(self, ts):
        """Р¤РѕСЂРјР°С‚РёСЂРѕРІР°С‚СЊ РІСЂРµРјРµРЅРЅСѓСЋ РјРµС‚РєСѓ"""
        if ts:
            return ts.strftime("%Y-%m-%d %H:%M")
        return ""
    
    def _get_auth_status(self, account):
        """РџРѕР»СѓС‡РёС‚СЊ СЃС‚Р°С‚СѓСЃ Р°РІС‚РѕСЂРёР·Р°С†РёРё"""
        # РџСЂРѕРІРµСЂСЏРµРј РєСѓРєРё РІ РІС‹Р±СЂР°РЅРЅРѕРј РїСЂРѕС„РёР»Рµ
        profile_path = self._normalize_profile_path(account.profile_path, account.name)
        from pathlib import Path
        cookies_file = Path(profile_path) / "Default" / "Cookies"
        
        if cookies_file.exists() and cookies_file.stat().st_size > 1000:
            # РџСЂРѕРІРµСЂСЏРµРј СЃРІРµР¶РµСЃС‚СЊ РєСѓРєРѕРІ
            from datetime import datetime
            age_days = (datetime.now().timestamp() - cookies_file.stat().st_mtime) / 86400
            if age_days < 7:
                return "Р—Р°Р»РѕРіРёРЅРµРЅ"
            else:
                return "РљСѓРєРё СѓСЃС‚Р°СЂРµР»Рё"
        
        return "РќРµ Р·Р°Р»РѕРіРёРЅРµРЅ"
    
    def _format_proxy(self, proxy):
        """Р¤РѕСЂРјР°С‚РёСЂРѕРІР°С‚СЊ РїСЂРѕРєСЃРё РґР»СЏ РѕС‚РѕР±СЂР°Р¶РµРЅРёСЏ"""
        if not proxy:
            return "No proxy"
        
        # РР·РІР»РµРєР°РµРј IP РёР· РїСЂРѕРєСЃРё
        if "@" in str(proxy):
            # Р¤РѕСЂРјР°С‚: http://user:pass@ip:port
            parts = str(proxy).split("@")
            if len(parts) > 1:
                ip_port = parts[1].replace("http://", "")
                # РџРѕРєР°Р·С‹РІР°РµРј С‚РѕР»СЊРєРѕ IP Рё РїРѕСЂС‚
                if ":" in ip_port:
                    ip = ip_port.split(":")[0]
                    # РћРїСЂРµРґРµР»СЏРµРј СЃС‚СЂР°РЅСѓ РїРѕ IP
                    if ip.startswith("213.139"):
                        return f"KZ {ip}"  # KZ РІРјРµСЃС‚Рѕ С„Р»Р°РіР°
                    return ip
        return str(proxy)[:20] + "..."
    
    def _get_activity_status(self, account):
        """РџРѕР»СѓС‡РёС‚СЊ СЃС‚Р°С‚СѓСЃ Р°РєС‚РёРІРЅРѕСЃС‚Рё Р°РєРєР°СѓРЅС‚Р°"""
        # РџСЂРѕРІРµСЂСЏРµРј cookies РґР»СЏ РѕРїСЂРµРґРµР»РµРЅРёСЏ Р°РєС‚РёРІРЅРѕСЃС‚Рё
        profile_path = Path(account.profile_path if account.profile_path else f".profiles/{account.name}")
        cookies_file = profile_path / "Default" / "Cookies"
        
        if cookies_file.exists():
            from datetime import datetime
            mtime = datetime.fromtimestamp(cookies_file.stat().st_mtime)
            age = datetime.now() - mtime
            
            if age.total_seconds() < 300:  # 5 РјРёРЅСѓС‚
                return "РђРєС‚РёРІРµРЅ СЃРµР№С‡Р°СЃ"
            elif age.total_seconds() < 3600:  # 1 С‡Р°СЃ
                return "РђРєС‚РёРІРµРЅ РЅРµРґР°РІРЅРѕ"
            elif age.days < 1:
                return "РСЃРїРѕР»СЊР·РѕРІР°РЅ СЃРµРіРѕРґРЅСЏ"
            elif age.days < 7:
                return f"{age.days} РґРЅ. РЅР°Р·Р°Рґ"
            else:
                return "РќРµР°РєС‚РёРІРµРЅ"
        else:
            return "РќРµ РёСЃРїРѕР»СЊР·РѕРІР°РЅ"
    
    def add_account(self):
        """Р”РѕР±Р°РІРёС‚СЊ РЅРѕРІС‹Р№ Р°РєРєР°СѓРЅС‚"""
        from ..app.main import AccountDialog
        
        dialog = AccountDialog(self)
        if dialog.exec() == QDialog.Accepted:
            data = dialog.get_data()
            if data:
                try:
                    account_service.create_account(**data)
                    self.refresh()
                    self.accounts_changed.emit()
                    QMessageBox.information(self, "РЈСЃРїРµС…", "РђРєРєР°СѓРЅС‚ РґРѕР±Р°РІР»РµРЅ")
                except Exception as e:
                    QMessageBox.warning(self, "РћС€РёР±РєР°", str(e))
    
    def edit_account(self):
        """Р РµРґР°РєС‚РёСЂРѕРІР°С‚СЊ Р°РєРєР°СѓРЅС‚"""
        account = self._current_account()
        if not account:
            return
            
        from ..app.main import AccountDialog
        import json
        from pathlib import Path
        
        # Р—Р°РіСЂСѓР¶Р°РµРј РґР°РЅРЅС‹Рµ РёР· accounts.json
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
                    QMessageBox.warning(self, "РћС€РёР±РєР°", str(e))
    
    def delete_account(self):
        """РЈРґР°Р»РёС‚СЊ Р°РєРєР°СѓРЅС‚"""
        account = self._current_account()
        if not account:
            return
            
        reply = QMessageBox.question(
            self, "РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ",
            f"РЈРґР°Р»РёС‚СЊ Р°РєРєР°СѓРЅС‚ '{account.name}'?\n\n"
            f"Р­С‚Рѕ С‚Р°РєР¶Рµ СѓРґР°Р»РёС‚ РµРіРѕ РёР· accounts.json\n"
            f"РџСЂРѕС„РёР»СЊ Р±СЂР°СѓР·РµСЂР° РќР• Р±СѓРґРµС‚ СѓРґР°Р»РµРЅ",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # РЈРґР°Р»СЏРµРј РёР· Р±Р°Р·С‹ РґР°РЅРЅС‹С…
                account_service.delete_account(account.id)
                
                # РЈРґР°Р»СЏРµРј РёР· accounts.json
                import json
                from pathlib import Path
                
                accounts_file = Path("C:/AI/yandex/configs/accounts.json")
                if accounts_file.exists():
                    with open(accounts_file, 'r', encoding='utf-8') as f:
                        accounts = json.load(f)
                    
                    # РЈРґР°Р»СЏРµРј Р°РєРєР°СѓРЅС‚ РёР· СЃРїРёСЃРєР°
                    accounts = [acc for acc in accounts if acc.get("login") != account.name]
                    
                    # РЎРѕС…СЂР°РЅСЏРµРј РѕР±СЂР°С‚РЅРѕ
                    with open(accounts_file, 'w', encoding='utf-8') as f:
                        json.dump(accounts, f, ensure_ascii=False, indent=2)
                    
                    self.log_action(f"РђРєРєР°СѓРЅС‚ {account.name} СѓРґР°Р»РµРЅ РёР· accounts.json")
                
                self.refresh()
                self.accounts_changed.emit()
                QMessageBox.information(self, "РЈСЃРїРµС…", f"РђРєРєР°СѓРЅС‚ {account.name} СѓРґР°Р»РµРЅ")
            except Exception as e:
                QMessageBox.warning(self, "РћС€РёР±РєР°", str(e))
    
    def import_accounts(self):
        """РРјРїРѕСЂС‚РёСЂРѕРІР°С‚СЊ Р°РєРєР°СѓРЅС‚С‹ РёР· С„Р°Р№Р»Р°"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Р’С‹Р±РµСЂРёС‚Рµ С„Р°Р№Р» СЃ Р°РєРєР°СѓРЅС‚Р°РјРё",
            "",
            "Text files (*.txt);;CSV files (*.csv);;All files (*.*)"
        )
        
        if filename:
            try:
                # TODO: Р РµР°Р»РёР·РѕРІР°С‚СЊ РёРјРїРѕСЂС‚
                QMessageBox.information(self, "РРјРїРѕСЂС‚", "Р¤СѓРЅРєС†РёСЏ РІ СЂР°Р·СЂР°Р±РѕС‚РєРµ")
            except Exception as e:
                QMessageBox.warning(self, "РћС€РёР±РєР° РёРјРїРѕСЂС‚Р°", str(e))
    
    def test_proxy_selected(self):
        """РџСЂРѕРІРµСЂРёС‚СЊ РїСЂРѕРєСЃРё РІС‹Р±СЂР°РЅРЅРѕРіРѕ Р°РєРєР°СѓРЅС‚Р°"""
        account = self._current_account()
        if not account:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "Р’С‹Р±РµСЂРёС‚Рµ Р°РєРєР°СѓРЅС‚ РґР»СЏ РїСЂРѕРІРµСЂРєРё РїСЂРѕРєСЃРё")
            return
        
        if not account.proxy:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", f"РЈ Р°РєРєР°СѓРЅС‚Р° {account.name} РЅРµ СѓРєР°Р·Р°РЅ РїСЂРѕРєСЃРё")
            return
        
        # РРјРїРѕСЂС‚РёСЂСѓРµРј СЃРµСЂРІРёСЃ РїСЂРѕРІРµСЂРєРё РїСЂРѕРєСЃРё
        from ..services.proxy_check import test_proxy
        import asyncio
        
        # РЎРѕР·РґР°РµРј РґРёР°Р»РѕРі РїСЂРѕРіСЂРµСЃСЃР°
        progress_dialog = QMessageBox(self)
        progress_dialog.setWindowTitle("РџСЂРѕРІРµСЂРєР° РїСЂРѕРєСЃРё")
        progress_dialog.setText(f"РџСЂРѕРІРµСЂРєР° РїСЂРѕРєСЃРё РґР»СЏ Р°РєРєР°СѓРЅС‚Р° {account.name}...\n\n{account.proxy}")
        progress_dialog.setStandardButtons(QMessageBox.NoButton)
        progress_dialog.setModal(True)
        progress_dialog.show()
        
        # Р—Р°РїСѓСЃРєР°РµРј РїСЂРѕРІРµСЂРєСѓ РІ РѕС‚РґРµР»СЊРЅРѕРј РїРѕС‚РѕРєРµ
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
        
        # РџРѕРєР°Р·С‹РІР°РµРј СЂРµР·СѓР»СЊС‚Р°С‚
        if 'result' not in result_container:
            QMessageBox.warning(self, "РћС€РёР±РєР°", "РџСЂРѕРІРµСЂРєР° РїСЂРѕРєСЃРё Р·Р°РЅСЏР»Р° СЃР»РёС€РєРѕРј РјРЅРѕРіРѕ РІСЂРµРјРµРЅРё (>15 СЃРµРє)")
            return
        
        result = result_container['result']
        
        if result['ok']:
            msg = f"вњ… РџСЂРѕРєСЃРё СЂР°Р±РѕС‚Р°РµС‚!\n\n"
            msg += f"РђРєРєР°СѓРЅС‚: {account.name}\n"
            msg += f"РџСЂРѕРєСЃРё: {account.proxy}\n"
            msg += f"IP: {result['ip']}\n"
            msg += f"Р—Р°РґРµСЂР¶РєР°: {result['latency_ms']} РјСЃ"
            QMessageBox.information(self, "Р РµР·СѓР»СЊС‚Р°С‚ РїСЂРѕРІРµСЂРєРё", msg)
            self.log_action(f"РџСЂРѕРєСЃРё {account.proxy} СЂР°Р±РѕС‚Р°РµС‚ (IP: {result['ip']}, {result['latency_ms']}ms)")
        else:
            msg = f"вќЊ РџСЂРѕРєСЃРё РќР• СЂР°Р±РѕС‚Р°РµС‚!\n\n"
            msg += f"РђРєРєР°СѓРЅС‚: {account.name}\n"
            msg += f"РџСЂРѕРєСЃРё: {account.proxy}\n"
            msg += f"РћС€РёР±РєР°: {result['error']}\n"
            msg += f"Р—Р°РґРµСЂР¶РєР°: {result['latency_ms']} РјСЃ"
            QMessageBox.warning(self, "Р РµР·СѓР»СЊС‚Р°С‚ РїСЂРѕРІРµСЂРєРё", msg)
            self.log_action(f"РџСЂРѕРєСЃРё {account.proxy} РќР• СЂР°Р±РѕС‚Р°РµС‚: {result['error']}")
    
    def open_proxy_manager(self):
        """РћС‚РєСЂС‹С‚СЊ Proxy Manager (РЅРµРјРѕРґР°Р»СЊРЅРѕРµ РѕРєРЅРѕ)"""
        from .proxy_manager import ProxyManagerDialog

        # РЎРѕР·РґР°РµРј Рё РїРѕРєР°Р·С‹РІР°РµРј РѕРєРЅРѕ
        proxy_manager = ProxyManagerDialog(self)
        proxy_manager.finished.connect(lambda *_: self.refresh())
        proxy_manager.show()  # РќР• exec() - РЅРµРјРѕРґР°Р»СЊРЅРѕРµ!

        self.log_action("РћС‚РєСЂС‹С‚ Proxy Manager")
    
    def check_captcha_balance(self):
        """РџСЂРѕРІРµСЂРёС‚СЊ Р±Р°Р»Р°РЅСЃ RuCaptcha"""
        # РџРѕРєР° РёСЃРїРѕР»СЊР·СѓРµРј РѕР±С‰РёР№ РєР»СЋС‡ РёР· С„Р°Р№Р»Р°
        # TODO: Р’ Р±СѓРґСѓС‰РµРј Р±СЂР°С‚СЊ РєР»СЋС‡ РёР· РїРѕР»СЏ captcha_key Р°РєРєР°СѓРЅС‚Р°
        CAPTCHA_KEY = "8f00b4cb9b77d982abb77260a168f976"
        
        from ..services.captcha import RuCaptchaClient
        import asyncio
        
        # РЎРѕР·РґР°РµРј РґРёР°Р»РѕРі РїСЂРѕРіСЂРµСЃСЃР°
        progress_dialog = QMessageBox(self)
        progress_dialog.setWindowTitle("РџСЂРѕРІРµСЂРєР° Р±Р°Р»Р°РЅСЃР° РєР°РїС‡Рё")
        progress_dialog.setText("РџСЂРѕРІРµСЂРєР° Р±Р°Р»Р°РЅСЃР° RuCaptcha...\n\nРћР¶РёРґР°Р№С‚Рµ...")
        progress_dialog.setStandardButtons(QMessageBox.NoButton)
        progress_dialog.setModal(True)
        progress_dialog.show()
        
        # Р—Р°РїСѓСЃРєР°РµРј РїСЂРѕРІРµСЂРєСѓ РІ РѕС‚РґРµР»СЊРЅРѕРј РїРѕС‚РѕРєРµ
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
        
        # РџРѕРєР°Р·С‹РІР°РµРј СЂРµР·СѓР»СЊС‚Р°С‚
        if 'result' not in result_container:
            QMessageBox.warning(self, "РћС€РёР±РєР°", "РџСЂРѕРІРµСЂРєР° Р±Р°Р»Р°РЅСЃР° Р·Р°РЅСЏР»Р° СЃР»РёС€РєРѕРј РјРЅРѕРіРѕ РІСЂРµРјРµРЅРё (>15 СЃРµРє)")
            return
        
        result = result_container['result']
        
        if result['ok']:
            balance = result['balance']
            msg = f"вњ… RuCaptcha Р±Р°Р»Р°РЅСЃ\n\n"
            msg += f"РљР»СЋС‡: {CAPTCHA_KEY[:20]}...\n"
            msg += f"Р‘Р°Р»Р°РЅСЃ: {balance:.2f} СЂСѓР±\n\n"
            
            # РџСЂРёРєРёРЅРµРј СЃРєРѕР»СЊРєРѕ РєР°РїС‡ РјРѕР¶РЅРѕ СЂРµС€РёС‚СЊ
            price_per_captcha = 0.10  # РїСЂРёРјРµСЂРЅРѕ 10 РєРѕРїРµРµРє Р·Р° РєР°РїС‡Сѓ
            captchas_available = int(balance / price_per_captcha)
            msg += f"РџСЂРёРјРµСЂРЅРѕ {captchas_available} РєР°РїС‡ РјРѕР¶РЅРѕ СЂРµС€РёС‚СЊ"
            
            QMessageBox.information(self, "Р‘Р°Р»Р°РЅСЃ РєР°РїС‡Рё", msg)
            self.log_action(f"RuCaptcha Р±Р°Р»Р°РЅСЃ: {balance:.2f} СЂСѓР± (~{captchas_available} РєР°РїС‡)")
        else:
            msg = f"вќЊ РћС€РёР±РєР° РїСЂРѕРІРµСЂРєРё Р±Р°Р»Р°РЅСЃР°!\n\n"
            msg += f"РљР»СЋС‡: {CAPTCHA_KEY[:20]}...\n"
            msg += f"РћС€РёР±РєР°: {result['error']}"
            QMessageBox.warning(self, "РћС€РёР±РєР° РєР°РїС‡Рё", msg)
            self.log_action(f"RuCaptcha РѕС€РёР±РєР°: {result['error']}")
    
    def login_selected(self):
        """РћС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ СЂСѓС‡РЅРѕРіРѕ Р»РѕРіРёРЅР° СЃ СѓС‡РµС‚РѕРј РїСЂРёРІСЏР·Р°РЅРЅРѕРіРѕ РїСЂРѕРєСЃРё."""
        selected_rows = self._selected_rows()
        if not selected_rows:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "Р’С‹Р±РµСЂРёС‚Рµ Р°РєРєР°СѓРЅС‚С‹ РґР»СЏ Р»РѕРіРёРЅР°")
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
                "Р“РѕС‚РѕРІРѕ",
                f"РћС‚РєСЂС‹С‚Рѕ {opened} Р±СЂР°СѓР·РµСЂРѕРІ. РџСЂРѕРІРµСЂСЊС‚Рµ Р°РІС‚РѕСЂРёР·Р°С†РёСЋ Рё РѕР±РЅРѕРІРёС‚Рµ СЃС‚Р°С‚СѓСЃС‹.",
            )
        else:
            QMessageBox.warning(
                self,
                "РћС€РёР±РєР°",
                "РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ РІС‹Р±СЂР°РЅРЅС‹С… Р°РєРєР°СѓРЅС‚РѕРІ.",
            )
    
    def auto_login_selected(self):
        """РђРІС‚РѕРјР°С‚РёС‡РµСЃРєР°СЏ Р°РІС‚РѕСЂРёР·Р°С†РёСЏ Р’Р«Р‘Р РђРќРќР«РҐ Р°РєРєР°СѓРЅС‚РѕРІ (РіРґРµ СЃС‚РѕСЏС‚ РіР°Р»РѕС‡РєРё)"""
        # Р‘РµСЂРµРј С‚РѕР»СЊРєРѕ РІС‹Р±СЂР°РЅРЅС‹Рµ Р°РєРєР°СѓРЅС‚С‹
        selected_rows = self._selected_rows()
        
        if not selected_rows:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "Р’С‹Р±РµСЂРёС‚Рµ Р°РєРєР°СѓРЅС‚С‹ РґР»СЏ Р°РІС‚РѕР»РѕРіРёРЅР° (РїРѕСЃС‚Р°РІСЊС‚Рµ РіР°Р»РѕС‡РєРё)")
            return
        
        # Р•СЃР»Рё РІС‹Р±СЂР°РЅРѕ Р±РѕР»СЊС€Рµ РѕРґРЅРѕРіРѕ - СЃРїСЂР°С€РёРІР°РµРј РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ
        if len(selected_rows) > 1:
            reply = QMessageBox.question(self, "РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ",
                f"Р‘СѓРґРµС‚ РІС‹РїРѕР»РЅРµРЅР° Р°РІС‚РѕСЂРёР·Р°С†РёСЏ {len(selected_rows)} РІС‹Р±СЂР°РЅРЅС‹С… Р°РєРєР°СѓРЅС‚РѕРІ.\n\n"
                f"РљР°Р¶РґС‹Р№ Р°РєРєР°СѓРЅС‚ Р±СѓРґРµС‚ РѕС‚РєСЂС‹С‚ РІ РѕС‚РґРµР»СЊРЅРѕРј Р±СЂР°СѓР·РµСЂРµ.\n"
                f"РџСЂРѕРґРѕР»Р¶РёС‚СЊ?",
                QMessageBox.Yes | QMessageBox.No)
            
            if reply != QMessageBox.Yes:
                return
        
        self.log_action(f"Р—Р°РїСѓСЃРє Р°РІС‚РѕР»РѕРіРёРЅР° РґР»СЏ {len(selected_rows)} РІС‹Р±СЂР°РЅРЅС‹С… Р°РєРєР°СѓРЅС‚РѕРІ...")
        
        # Р—Р°РїСѓСЃРєР°РµРј Р°РІС‚РѕР»РѕРіРёРЅ С‚РѕР»СЊРєРѕ РґР»СЏ Р’Р«Р‘Р РђРќРќР«РҐ Р°РєРєР°СѓРЅС‚РѕРІ
        self.auto_login_threads = []
        for idx, row_idx in enumerate(selected_rows):
            account = self._accounts[row_idx]
            self.log_action(f"[{idx+1}/{len(selected_rows)}] Р—Р°РїСѓСЃРє Р°РІС‚РѕР»РѕРіРёРЅР° РґР»СЏ {account.name}...")
            
            # РЎРѕР·РґР°РµРј РѕС‚РґРµР»СЊРЅС‹Р№ РїРѕС‚РѕРє РґР»СЏ РєР°Р¶РґРѕРіРѕ Р°РєРєР°СѓРЅС‚Р°
            thread = AutoLoginThread(account)
            thread.status_signal.connect(lambda msg, acc=account.name: self.log_action(f"[{acc}] {msg}"))
            thread.progress_signal.connect(self._update_progress)
            thread.secret_question_signal.connect(self._handle_secret_question)
            thread.finished_signal.connect(lambda success, msg, acc=account.name: self._on_auto_login_finished(success, f"[{acc}] {msg}"))
            
            # Р’РђР–РќРћ: Р‘РѕР»СЊС€Р°СЏ Р·Р°РґРµСЂР¶РєР° РјРµР¶РґСѓ Р·Р°РїСѓСЃРєР°РјРё С‡С‚РѕР±С‹ РЅРµ РІС‹Р·РІР°С‚СЊ РєР°РїС‡Сѓ!
            QTimer.singleShot(idx * 10000, thread.start)  # 10 СЃРµРєСѓРЅРґ РјРµР¶РґСѓ Р·Р°РїСѓСЃРєР°РјРё!
            self.auto_login_threads.append(thread)
        
        # РћС‚РєР»СЋС‡Р°РµРј РєРЅРѕРїРєРё РЅР° РІСЂРµРјСЏ Р°РІС‚РѕСЂРёР·Р°С†РёРё
        self.auto_login_btn.setEnabled(False)
        self.log_action(f"Р—Р°РїСѓСЃРє Р°РІС‚РѕР»РѕРіРёРЅР° РґР»СЏ {account.name}...")
    
    def _handle_secret_question(self, account_name: str, question_text: str):
        """РћР±СЂР°Р±РѕС‚РєР° СЃРµРєСЂРµС‚РЅРѕРіРѕ РІРѕРїСЂРѕСЃР°"""
        from PySide6.QtWidgets import QInputDialog
        
        # РџРѕРєР°Р·С‹РІР°РµРј РґРёР°Р»РѕРі РґР»СЏ РІРІРѕРґР° РѕС‚РІРµС‚Р°
        answer, ok = QInputDialog.getText(
            self,
            "РЎРµРєСЂРµС‚РЅС‹Р№ РІРѕРїСЂРѕСЃ",
            f"РђРєРєР°СѓРЅС‚: {account_name}\n\n{question_text}\n\nР’РІРµРґРёС‚Рµ РѕС‚РІРµС‚:",
            echo=QLineEdit.Normal
        )
        
        if ok and answer:
            # РџРµСЂРµРґР°РµРј РѕС‚РІРµС‚ РІ РїРѕС‚РѕРє
            if hasattr(self, 'auto_login_thread'):
                self.auto_login_thread.set_secret_answer(answer)
    
    def _update_progress(self, value: int):
        """РћР±РЅРѕРІР»РµРЅРёРµ РїСЂРѕРіСЂРµСЃСЃР°"""
        # Р•СЃР»Рё РµСЃС‚СЊ РїСЂРѕРіСЂРµСЃСЃ-Р±Р°СЂ, РѕР±РЅРѕРІР»СЏРµРј РµРіРѕ
        if hasattr(self, 'progress_bar'):
            self.progress_bar.setValue(value)
    
    def _on_auto_login_finished(self, success: bool, message: str):
        """РћР±СЂР°Р±РѕС‚РєР° Р·Р°РІРµСЂС€РµРЅРёСЏ Р°РІС‚РѕР»РѕРіРёРЅР°"""
        # Р’РєР»СЋС‡Р°РµРј РєРЅРѕРїРєСѓ РѕР±СЂР°С‚РЅРѕ
        self.auto_login_btn.setEnabled(True)
        
        if success:
            self.log_action(f"[OK] {message}")
            # РћР±РЅРѕРІР»СЏРµРј С‚Р°Р±Р»РёС†Сѓ
            self.refresh()
        else:
            self.log_action(f"[ERROR] {message}")
            QMessageBox.warning(self, "РћС€РёР±РєР° Р°РІС‚РѕР»РѕРіРёРЅР°", message)
    
    def launch_browsers_cdp(self):
        """РћС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ РїР°СЂСЃРёРЅРіР°, СѓС‡РёС‚С‹РІР°СЏ РІС‹Р±СЂР°РЅРЅС‹Рµ РїСЂРѕРєСЃРё."""
        selected_rows = self._selected_rows()
        if not selected_rows:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "Р’С‹Р±РµСЂРёС‚Рµ Р°РєРєР°СѓРЅС‚С‹ РґР»СЏ Р·Р°РїСѓСЃРєР°")
            return

        selected_accounts = [
            self._accounts[row] for row in selected_rows if row < len(self._accounts)
        ]

        self.log_action(f"Р—Р°РїСѓСЃРє {len(selected_accounts)} РІС‹Р±СЂР°РЅРЅС‹С… Р±СЂР°СѓР·РµСЂРѕРІ РґР»СЏ РїР°СЂСЃРёРЅРіР°...")

        reply = QMessageBox.question(
            self,
            "Р—Р°РїСѓСЃРє Р±СЂР°СѓР·РµСЂРѕРІ",
            f"Р‘СѓРґРµС‚ Р·Р°РїСѓС‰РµРЅРѕ {len(selected_accounts)} Р±СЂР°СѓР·РµСЂРѕРІ РґР»СЏ РїР°СЂСЃРёРЅРіР°.\n\n"
            f"РђРєРєР°СѓРЅС‚С‹:\n" + "\n".join(f"  вЂў {acc.name}" for acc in selected_accounts) + "\n\n"
            "Р‘СЂР°СѓР·РµСЂС‹ РѕС‚РєСЂРѕСЋС‚СЃСЏ СЃ СЃСѓС‰РµСЃС‚РІСѓСЋС‰РёРјРё РєСѓРєР°РјРё Р±РµР· РїРѕРїС‹С‚РєРё Р°РІС‚РѕР»РѕРіРёРЅР°.\n"
            "РџСЂРѕРґРѕР»Р¶РёС‚СЊ?",
        )

        if reply != QMessageBox.Yes:
            return

        self._release_browser_handles()
        launched = 0

        for account in selected_accounts:
            handle = self._launch_browser_handle(
                account,
                target_url="https://wordstat.yandex.ru/?region=225",
                prefer_cdp=True,
            )
            if handle:
                launched += 1

        if launched:
            QMessageBox.information(
                self,
                "РЈСЃРїРµС…",
                f"Р—Р°РїСѓС‰РµРЅРѕ {launched} Р±СЂР°СѓР·РµСЂРѕРІ. РўРµРїРµСЂСЊ РјРѕР¶РЅРѕ Р·Р°РїСѓСЃРєР°С‚СЊ РїР°СЂСЃРµСЂ.",
            )
        else:
            self.log_action("вќЊ РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РїСѓСЃС‚РёС‚СЊ Р±СЂР°СѓР·РµСЂС‹")
            QMessageBox.warning(self, "РћС€РёР±РєР°", "РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РїСѓСЃС‚РёС‚СЊ Р±СЂР°СѓР·РµСЂС‹")

    def _launch_browser_handle(self, account, *, target_url: str, prefer_cdp: bool):
        """Р—Р°РїСѓСЃС‚РёС‚СЊ Р±СЂР°СѓР·РµСЂ С‡РµСЂРµР· BrowserFactory Рё РІРµСЂРЅСѓС‚СЊ handle."""
        try:
            handle = start_for_account(
                account_id=account.id,
                headless=False,
                use_cdp=prefer_cdp,
                profile_override=account.profile_path or f".profiles/{account.name}",
            )
        except Exception as exc:
            self.log_action(f"[{account.name}] вќЊ РћС€РёР±РєР° Р·Р°РїСѓСЃРєР° Р±СЂР°СѓР·РµСЂР°: {exc}")
            return None

        self._browser_handles.append(handle)

        mode = "CDP attach" if handle.kind == "cdp" else "PW persistent"
        proxy_label = handle.proxy_id or getattr(account, "proxy_id", None) or getattr(account, "proxy", None) or "-"
        self.log_action(f"[{account.name}] {mode} (proxy={proxy_label})")

        metadata = getattr(handle, "metadata", {}) or {}
        if handle.kind == "cdp":
            port = metadata.get("cdp_port") if isinstance(metadata, dict) else None
            if port:
                self.log_action(f"[{account.name}] CDP РїРѕСЂС‚: {port}")

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

        # РћС‚РєСЂС‹РІР°РµРј С†РµР»РµРІРѕР№ URL
        try:
            if handle.page:
                handle.page.goto(target_url, wait_until="domcontentloaded")
        except Exception as exc:
            self.log_action(f"[{account.name}] вљ пёЏ РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РєСЂС‹С‚СЊ {target_url}: {exc}")

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
                self.log_action(f"[{account_name}] IP С‡РµСЂРµР· РїСЂРѕРєСЃРё: {ip_value}")
            else:
                self.log_action(f"[{account_name}] РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕР»СѓС‡РёС‚СЊ IP (РїСѓСЃС‚РѕР№ РѕС‚РІРµС‚)")
        except Exception as exc:
            self.log_action(f"[{account_name}] вљ пёЏ РћС€РёР±РєР° РїСЂРѕРІРµСЂРєРё IP: {exc}")

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
        """РђРІС‚РѕР»РѕРіРёРЅ РґР»СЏ РЅРѕРІС‹С… Р°РєРєР°СѓРЅС‚РѕРІ - РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅР°СЏ Р°РІС‚РѕСЂРёР·Р°С†РёСЏ"""
        if not self._accounts:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "РќРµС‚ Р°РєРєР°СѓРЅС‚РѕРІ РґР»СЏ Р»РѕРіРёРЅР°")
            return
        
        self.log_action("Р—Р°РїСѓСЃРє РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅРѕР№ Р°РІС‚РѕСЂРёР·Р°С†РёРё РІСЃРµС… Р°РєРєР°СѓРЅС‚РѕРІ...")
        
        # РЎРїСЂР°С€РёРІР°РµРј РїРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ
        reply = QMessageBox.question(self, "РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ",
            f"Р‘СѓРґРµС‚ РІС‹РїРѕР»РЅРµРЅ РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅС‹Р№ РІС…РѕРґ РІ {len(self._accounts)} Р°РєРєР°СѓРЅС‚(РѕРІ).\n\n"
            f"РљР°Р¶РґС‹Р№ Р°РєРєР°СѓРЅС‚ Р±СѓРґРµС‚ Р°РІС‚РѕСЂРёР·РѕРІР°РЅ Р°РІС‚РѕРјР°С‚РёС‡РµСЃРєРё.\n"
            f"Р­С‚Рѕ РјРѕР¶РµС‚ Р·Р°РЅСЏС‚СЊ РЅРµСЃРєРѕР»СЊРєРѕ РјРёРЅСѓС‚.\n\n"
            f"РџСЂРѕРґРѕР»Р¶РёС‚СЊ?")
        
        if reply == QMessageBox.Yes:
            self.log_action("РќР°С‡РёРЅР°РµРј РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅСѓСЋ Р°РІС‚РѕСЂРёР·Р°С†РёСЋ...")
            # Р—Р°РїСѓСЃРєР°РµРј РїРѕСЃР»РµРґРѕРІР°С‚РµР»СЊРЅСѓСЋ Р°РІС‚РѕСЂРёР·Р°С†РёСЋ
            self._current_login_index = 0
            self._login_next_account()
    
    def _login_next_account(self):
        """Р›РѕРіРёРЅ РІ СЃР»РµРґСѓСЋС‰РёР№ Р°РєРєР°СѓРЅС‚ РёР· СЃРїРёСЃРєР°"""
        if self._current_login_index >= len(self._accounts):
            # Р’СЃРµ Р°РєРєР°СѓРЅС‚С‹ РѕР±СЂР°Р±РѕС‚Р°РЅС‹
            self.log_action("вњ… РђРІС‚РѕСЂРёР·Р°С†РёСЏ РІСЃРµС… Р°РєРєР°СѓРЅС‚РѕРІ Р·Р°РІРµСЂС€РµРЅР°!")
            QMessageBox.information(self, "Р“РѕС‚РѕРІРѕ", "РђРІС‚РѕСЂРёР·Р°С†РёСЏ РІСЃРµС… Р°РєРєР°СѓРЅС‚РѕРІ Р·Р°РІРµСЂС€РµРЅР°!")
            self.refresh()
            return
        
        account = self._accounts[self._current_login_index]
        self.log_action(f"РђРІС‚РѕСЂРёР·Р°С†РёСЏ {self._current_login_index + 1}/{len(self._accounts)}: {account.name}...")
        
        # Р—Р°РїСѓСЃРєР°РµРј Р°РІС‚РѕР»РѕРіРёРЅ РґР»СЏ С‚РµРєСѓС‰РµРіРѕ Р°РєРєР°СѓРЅС‚Р°
        self.auto_login_thread = AutoLoginThread(account)
        self.auto_login_thread.status_signal.connect(lambda msg: self.log_action(f"[{account.name}] {msg}"))
        self.auto_login_thread.finished_signal.connect(self._on_account_login_finished)
        self.auto_login_thread.start()
    
    def _on_account_login_finished(self, success: bool, message: str):
        """РћР±СЂР°Р±РѕС‚РєР° Р·Р°РІРµСЂС€РµРЅРёСЏ Р»РѕРіРёРЅР° РѕРґРЅРѕРіРѕ Р°РєРєР°СѓРЅС‚Р°"""
        account = self._accounts[self._current_login_index]
        
        if success:
            self.log_action(f"вњ… {account.name}: {message}")
        else:
            self.log_action(f"вќЊ {account.name}: {message}")
        
        # РџРµСЂРµС…РѕРґРёРј Рє СЃР»РµРґСѓСЋС‰РµРјСѓ Р°РєРєР°СѓРЅС‚Сѓ
        self._current_login_index += 1
        
        # РќРµР±РѕР»СЊС€Р°СЏ Р·Р°РґРµСЂР¶РєР° РїРµСЂРµРґ СЃР»РµРґСѓСЋС‰РёРј Р°РєРєР°СѓРЅС‚РѕРј
        QTimer.singleShot(2000, self._login_next_account)
    
    def _start_login(self, accounts, headless=False, visual_mode=False):
        """Р—Р°РїСѓСЃС‚РёС‚СЊ РїСЂРѕС†РµСЃСЃ Р»РѕРіРёРЅР°"""
        if self.login_thread and self.login_thread.isRunning():
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "РџСЂРѕС†РµСЃСЃ Р»РѕРіРёРЅР° СѓР¶Рµ Р·Р°РїСѓС‰РµРЅ")
            return
        
        # Р‘Р»РѕРєРёСЂСѓРµРј РєРЅРѕРїРєРё
        self.login_btn.setEnabled(False)
        self.login_all_btn.setEnabled(False)
        
        # РџРѕРєР°Р·С‹РІР°РµРј РїСЂРѕРіСЂРµСЃСЃ
        self.login_progress.setVisible(True)
        self.login_progress.setRange(0, 0)  # РќРµРѕРїСЂРµРґРµР»РµРЅРЅС‹Р№ РїСЂРѕРіСЂРµСЃСЃ
        
        # РЎРѕР·РґР°РµРј Рё Р·Р°РїСѓСЃРєР°РµРј РїРѕС‚РѕРє
        # visual_mode=True РґР»СЏ РІРёР·СѓР°Р»СЊРЅРѕРіРѕ РїР°СЂСЃРёРЅРіР°
        self.login_thread = LoginWorkerThread(accounts, check_only=headless, visual_mode=visual_mode)
        self.login_thread.progress_signal.connect(self.on_login_progress)
        self.login_thread.account_logged_signal.connect(self.on_account_logged)
        self.login_thread.finished_signal.connect(self.on_login_finished)
        self.login_thread.start()
        
        self.log_action(f"Р—Р°РїСѓСЃРє {len(accounts)} Р±СЂР°СѓР·РµСЂРѕРІ...")
    
    def on_login_progress(self, message):
        """РћР±СЂР°Р±РѕС‚РєР° РїСЂРѕРіСЂРµСЃСЃР° Р»РѕРіРёРЅР°"""
        self.log_action(message)
    
    def on_account_logged(self, account_id, success, message):
        """РћР±СЂР°Р±РѕС‚РєР° Р»РѕРіРёРЅР° РєРѕРЅРєСЂРµС‚РЅРѕРіРѕ Р°РєРєР°СѓРЅС‚Р°"""
        # РћР±РЅРѕРІР»СЏРµРј СЃС‚Р°С‚СѓСЃ РІ Р‘Р”
        if success:
            account_service.mark_ok(account_id)
        
        # РћР±РЅРѕРІР»СЏРµРј С‚Р°Р±Р»РёС†Сѓ
        self.refresh()
    
    def on_login_finished(self, success, message):
        """РћР±СЂР°Р±РѕС‚РєР° Р·Р°РІРµСЂС€РµРЅРёСЏ Р»РѕРіРёРЅР°"""
        self.login_progress.setVisible(False)
        self.login_btn.setEnabled(True)
        self.login_all_btn.setEnabled(True)
        
        if success:
            QMessageBox.information(self, "РЈСЃРїРµС…", message)
        else:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", message)
        
        self.log_action("Р“РѕС‚РѕРІ Рє СЂР°Р±РѕС‚Рµ")
        self.refresh()
    
    def open_browsers_for_login(self):
        """РћС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹ С‚РѕР»СЊРєРѕ РґР»СЏ С‚РµС… Р°РєРєР°СѓРЅС‚РѕРІ РіРґРµ РЅСѓР¶РµРЅ Р»РѕРіРёРЅ"""
        from pathlib import Path
        
        # Р¤РёР»СЊС‚СЂСѓРµРј Р°РєРєР°СѓРЅС‚С‹ РєРѕС‚РѕСЂС‹Рµ С‚СЂРµР±СѓСЋС‚ Р»РѕРіРёРЅР°
        accounts_to_check = []
        for acc in self._accounts:
            if acc.name != "demo_account":  # РџСЂРѕРїСѓСЃРєР°РµРј РґРµРјРѕ
                # РСЃРїРѕР»СЊР·СѓРµРј РїРѕР»РЅС‹Р№ РїСѓС‚СЊ Рє РїСЂРѕС„РёР»СЋ
                # acc.profile_path РјРѕР¶РµС‚ СЃРѕРґРµСЂР¶Р°С‚СЊ РѕС‚РЅРѕСЃРёС‚РµР»СЊРЅС‹Р№ РїСѓС‚СЊ С‚РёРїР° ".profiles/dsmismirnov"
                if acc.profile_path:
                    # Р•СЃР»Рё РїСѓС‚СЊ РЅР°С‡РёРЅР°РµС‚СЃСЏ СЃ .profiles - СЌС‚Рѕ РѕС‚РЅРѕСЃРёС‚РµР»СЊРЅС‹Р№ РїСѓС‚СЊ
                    if acc.profile_path.startswith(".profiles"):
                        profile_full_path = Path("C:/AI/yandex") / acc.profile_path
                    else:
                        profile_full_path = Path(acc.profile_path)
                else:
                    # Р•СЃР»Рё РїСѓС‚СЊ РЅРµ Р·Р°РґР°РЅ, РёСЃРїРѕР»СЊР·СѓРµРј СЃС‚Р°РЅРґР°СЂС‚РЅС‹Р№
                    profile_full_path = Path("C:/AI/yandex/.profiles") / acc.name
                
                # РџСЂРѕРІРµСЂСЏРµРј РµСЃС‚СЊ Р»Рё СЃРѕС…СЂР°РЅРµРЅРЅС‹Рµ РєСѓРєРё
                cookie_file = profile_full_path / "Default" / "Cookies"
                
                # Р”РѕР±Р°РІР»СЏРµРј РІ СЃРїРёСЃРѕРє РґР»СЏ РїСЂРѕРІРµСЂРєРё
                _, proxy_uri, proxy_id = self._build_proxy_payload(acc)
                accounts_to_check.append({
                    "account": acc,
                    "has_cookies": cookie_file.exists(),
                    "profile_path": str(profile_full_path),
                    "proxy": proxy_uri or getattr(acc, "proxy", None),
                    "proxy_id": proxy_id,
                })
        
        if not accounts_to_check:
            QMessageBox.information(self, "РРЅС„РѕСЂРјР°С†РёСЏ", "РќРµС‚ Р°РєРєР°СѓРЅС‚РѕРІ РґР»СЏ РїСЂРѕРІРµСЂРєРё")
            return
        
        # РџРѕРєР°Р·С‹РІР°РµРј РґРёР°Р»РѕРі РІС‹Р±РѕСЂР°
        msg = "РЎС‚Р°С‚СѓСЃ Р°РєРєР°СѓРЅС‚РѕРІ:\n\n"
        
        # Р”Р°Р¶Рµ РµСЃР»Рё РІСЃРµ Р°РІС‚РѕСЂРёР·РѕРІР°РЅС‹, РѕС‚РєСЂС‹РІР°РµРј Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ РІРёР·СѓР°Р»СЊРЅРѕРіРѕ РїР°СЂСЃРёРЅРіР°
        msg += "\nвљ пёЏ Р’РќРРњРђРќРР•: Р‘СЂР°СѓР·РµСЂС‹ Р±СѓРґСѓС‚ РѕС‚РєСЂС‹С‚С‹ РґР»СЏ РІРёР·СѓР°Р»СЊРЅРѕРіРѕ РїР°СЂСЃРёРЅРіР°.\n"
        msg += "Р’СЃРµ Р°РєРєР°СѓРЅС‚С‹ РґРѕР»Р¶РЅС‹ Р±С‹С‚СЊ Р°РІС‚РѕСЂРёР·РѕРІР°РЅС‹.\n"
        msg += "РћС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹?"
        
        reply = QMessageBox.question(self, "РћС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ Р»РѕРіРёРЅР°", msg)
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
                "Р“РѕС‚РѕРІРѕ",
                f"РћС‚РєСЂС‹С‚Рѕ {launched} Р±СЂР°СѓР·РµСЂРѕРІ. Р’РѕР№РґРёС‚Рµ РІСЂСѓС‡РЅСѓСЋ Рё РѕР±РЅРѕРІРёС‚Рµ СЃС‚Р°С‚СѓСЃС‹.",
            )
        else:
            QMessageBox.warning(
                self,
                "РћС€РёР±РєР°",
                "РќРµ СѓРґР°Р»РѕСЃСЊ РѕС‚РєСЂС‹С‚СЊ Р±СЂР°СѓР·РµСЂС‹ РґР»СЏ РІРёР·СѓР°Р»СЊРЅРѕРіРѕ РїР°СЂСЃРёРЅРіР°.",
            )
    
    def show_browser_status(self):
        """РџРѕРєР°Р·Р°С‚СЊ СЃС‚Р°С‚СѓСЃ Р±СЂР°СѓР·РµСЂРѕРІ"""
        if hasattr(self, 'browser_manager') and self.browser_manager:
            self.browser_manager.show_status()
        else:
            QMessageBox.information(self, "РЎС‚Р°С‚СѓСЃ", "Р‘СЂР°СѓР·РµСЂС‹ РЅРµ Р·Р°РїСѓС‰РµРЅС‹")
    
    def update_browser_status(self):
        """РћР±РЅРѕРІРёС‚СЊ СЃС‚Р°С‚СѓСЃС‹ Р·Р°Р»РѕРіРёРЅРµРЅС‹ Р»Рё Р±СЂР°СѓР·РµСЂС‹"""
        if hasattr(self, 'browser_manager') and self.browser_manager:
            QMessageBox.information(self, "РЎС‚Р°С‚СѓСЃ", "РџСЂРѕРІРµСЂРєР° СЃС‚Р°С‚СѓСЃРѕРІ...")
            # TODO: СЂРµР°Р»РёР·РѕРІР°С‚СЊ РїСЂРѕРІРµСЂРєСѓ С‡РµСЂРµР· browser_manager
        else:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "Р‘СЂР°СѓР·РµСЂС‹ РЅРµ Р·Р°РїСѓС‰РµРЅС‹")
    
    def minimize_all_browsers(self):
        """РњРёРЅРёРјРёР·РёСЂРѕРІР°С‚СЊ РІСЃРµ Р±СЂР°СѓР·РµСЂС‹"""
        if hasattr(self, 'browser_manager') and self.browser_manager:
            try:
                # TODO: СЂРµР°Р»РёР·РѕРІР°С‚СЊ РјРёРЅРёРјРёР·Р°С†РёСЋ РІ browser_manager
                QMessageBox.information(self, "Р“РѕС‚РѕРІРѕ", "Р¤СѓРЅРєС†РёСЏ РІ СЂР°Р·СЂР°Р±РѕС‚РєРµ")
            except Exception as e:
                QMessageBox.warning(self, "РћС€РёР±РєР°", str(e))
        else:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "Р‘СЂР°СѓР·РµСЂС‹ РЅРµ Р·Р°РїСѓС‰РµРЅС‹")
    
    def close_all_browsers(self):
        """Р—Р°РєСЂС‹С‚СЊ РІСЃРµ РѕС‚РєСЂС‹С‚С‹Рµ Р±СЂР°СѓР·РµСЂС‹ (Рё С‡РµСЂРµР· BrowserFactory, Рё С‡РµСЂРµР· VisualBrowserManager)."""
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
                "РџРѕРґС‚РІРµСЂР¶РґРµРЅРёРµ",
                "Р—Р°РєСЂС‹С‚СЊ РІСЃРµ Р±СЂР°СѓР·РµСЂС‹?",
                QMessageBox.Yes | QMessageBox.No,
            )

            if reply == QMessageBox.Yes:
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(self.browser_manager.close_all())
                    self.browser_manager = None
                    QMessageBox.information(self, "Р“РѕС‚РѕРІРѕ", "Р‘СЂР°СѓР·РµСЂС‹ Р·Р°РєСЂС‹С‚С‹")
                    closed = True
                except Exception as e:
                    QMessageBox.warning(self, "РћС€РёР±РєР°", f"РћС€РёР±РєР° РїСЂРё Р·Р°РєСЂС‹С‚РёРё: {e}")

        if not closed:
            QMessageBox.information(self, "РРЅС„РѕСЂРјР°С†РёСЏ", "Р‘СЂР°СѓР·РµСЂС‹ РЅРµ Р·Р°РїСѓС‰РµРЅС‹")
    
    def on_table_double_click(self, item):
        """РћР±СЂР°Р±РѕС‚С‡РёРє РґРІРѕР№РЅРѕРіРѕ РєР»РёРєР° РїРѕ СЏС‡РµР№РєРµ С‚Р°Р±Р»РёС†С‹"""
        column = self.table.currentColumn()
        
        # Р•СЃР»Рё РєР»РёРє РїРѕ РєРѕР»РѕРЅРєРµ "РљСѓРєРё" (РёРЅРґРµРєСЃ 7)
        if column == 7:
            self.edit_cookies()
        else:
            self.edit_account()
    
    def edit_cookies(self, row):
        """Р РµРґР°РєС‚РёСЂРѕРІР°С‚СЊ РєСѓРєРё РґР»СЏ Р°РєРєР°СѓРЅС‚Р°"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QLabel

        account = self._accounts[row]
        profile_path_str = self._normalize_profile_path(account.profile_path, account.name)
        profile_path = Path(profile_path_str)
        
        # РЎРѕР·РґР°РµРј РґРёР°Р»РѕРі
        dialog = QDialog(self)
        dialog.setWindowTitle("РЈРїСЂР°РІР»РµРЅРёРµ РєСѓРєР°РјРё Wordstat")
        dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(dialog)
        
        # РРЅС„РѕСЂРјР°С†РёСЏ
        info = QLabel(f"""
<b>Р’Р°Р¶РЅС‹Рµ РєСѓРєРё РґР»СЏ Wordstat:</b><br>
вЂў sessionid2 - РѕСЃРЅРѕРІРЅР°СЏ СЃРµСЃСЃРёСЏ<br>
вЂў yandex_login - Р»РѕРіРёРЅ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ<br>
вЂў yandexuid - ID РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ<br>
вЂў L - С‚РѕРєРµРЅ Р°РІС‚РѕСЂРёР·Р°С†РёРё<br>
<br>
<b>РџСЂРѕС„РёР»СЊ:</b> {account.name}<br>
<b>РџСѓС‚СЊ:</b> {profile_path_str}
        """)
        layout.addWidget(info)
        
        # РџРѕР»Рµ РґР»СЏ РІРІРѕРґР° РєСѓРєРѕРІ
        cookies_edit = QTextEdit()
        cookies_edit.setPlaceholderText(
            "Р’СЃС‚Р°РІСЊС‚Рµ РєСѓРєРё РІ С„РѕСЂРјР°С‚Рµ:\n"
            "sessionid2=value1; yandex_login=value2; L=value3"
        )
        
        # РџС‹С‚Р°РµРјСЃСЏ РїСЂРѕС‡РёС‚Р°С‚СЊ С‚РµРєСѓС‰РёРµ РєСѓРєРё (СѓРїСЂРѕС‰РµРЅРЅРѕ)
        cookies_file = profile_path / "Default" / "Cookies"
        if cookies_file.exists():
            cookies_edit.setPlainText(f"Р¤Р°Р№Р» РєСѓРєРѕРІ СЃСѓС‰РµСЃС‚РІСѓРµС‚: {cookies_file}\nР Р°Р·РјРµСЂ: {cookies_file.stat().st_size} bytes\n\n[Р”Р»СЏ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ РєСѓРєРѕРІ РёСЃРїРѕР»СЊР·СѓР№С‚Рµ Р±СЂР°СѓР·РµСЂ]")
        
        layout.addWidget(cookies_edit)
        
        # РљРЅРѕРїРєРё
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.Accepted:
            # Р—РґРµСЃСЊ РјРѕР¶РЅРѕ РґРѕР±Р°РІРёС‚СЊ Р»РѕРіРёРєСѓ СЃРѕС…СЂР°РЅРµРЅРёСЏ РєСѓРєРѕРІ
            # РќРѕ Р±РµР·РѕРїР°СЃРЅРµРµ Р»РѕРіРёРЅРёС‚СЊСЃСЏ С‡РµСЂРµР· Р±СЂР°СѓР·РµСЂ
            QMessageBox.information(self, "РРЅС„РѕСЂРјР°С†РёСЏ", 
                "Р”Р»СЏ РёР·РјРµРЅРµРЅРёСЏ РєСѓРєРѕРІ РѕС‚РєСЂРѕР№С‚Рµ Р±СЂР°СѓР·РµСЂ СЃ СЌС‚РёРј РїСЂРѕС„РёР»РµРј,\n"
                "РІРѕР№РґРёС‚Рµ РІ РЇРЅРґРµРєСЃ РІСЂСѓС‡РЅСѓСЋ РёР»Рё РёСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєСѓ 'РђРІС‚РѕР»РѕРіРёРЅ'.")

    def _update_profile(self, account_id, profile_key, account_name: Optional[str] = None):
        """РћР±РЅРѕРІРёС‚СЊ РїСЂРѕС„РёР»СЊ РґР»СЏ Р°РєРєР°СѓРЅС‚Р°"""
        normalized_name = account_name if account_name else ""
        profile_path = self._normalize_profile_path(profile_key, normalized_name)
        account_service.update_account(account_id, profile_path=profile_path)
        print(f"[Accounts] РџСЂРѕС„РёР»СЊ РґР»СЏ Р°РєРєР°СѓРЅС‚Р° {account_id} РёР·РјРµРЅС‘РЅ РЅР° {profile_path}")

    def _handle_item_changed(self, item):
        """РћС‚СЃР»РµР¶РёРІР°РµРј РёР·РјРµРЅРµРЅРёРµ РїСЂРѕС„РёР»СЏ С‡РµСЂРµР· РґРµР»РµРіР°С‚."""
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
        """РћР±СЂР°Р±РѕС‚РєР° РґРІРѕР№РЅРѕРіРѕ РєР»РёРєР° РїРѕ С‚Р°Р±Р»РёС†Рµ"""
        # Р•СЃР»Рё РєР»РёРєРЅСѓР»Рё РїРѕ РєРѕР»РѕРЅРєРµ РєСѓРєРѕРІ - РѕС‚РєСЂС‹РІР°РµРј РґРёР°Р»РѕРі СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ
        if col == 8:  # РљРѕР»РѕРЅРєР° РєСѓРєРѕРІ
            self.edit_cookies(row)
            
    def edit_cookies(self, row):
        """Р РµРґР°РєС‚РёСЂРѕРІР°С‚СЊ РєСѓРєРё РґР»СЏ Р°РєРєР°СѓРЅС‚Р°"""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QDialogButtonBox, QLabel

        account = self._accounts[row]
        profile_path_str = self._normalize_profile_path(account.profile_path, account.name)
        profile_path = Path(profile_path_str)

        dialog = QDialog(self)
        dialog.setWindowTitle("РЈРїСЂР°РІР»РµРЅРёРµ РєСѓРєР°РјРё Wordstat")
        dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(dialog)

        info = QLabel(f"""
<b>Р’Р°Р¶РЅС‹Рµ РєСѓРєРё РґР»СЏ Wordstat:</b><br>
вЂў sessionid2 - РѕСЃРЅРѕРІРЅР°СЏ СЃРµСЃСЃРёСЏ<br>
вЂў yandex_login - Р»РѕРіРёРЅ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ<br>
вЂў yandexuid - ID РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ<br>
вЂў L - С‚РѕРєРµРЅ Р°РІС‚РѕСЂРёР·Р°С†РёРё<br>
<br>
<b>РџСЂРѕС„РёР»СЊ:</b> {account.name}<br>
<b>РџСѓС‚СЊ:</b> {profile_path_str}
        """)
        layout.addWidget(info)

        cookies_edit = QTextEdit()
        cookies_edit.setPlaceholderText(
            "Р’СЃС‚Р°РІСЊС‚Рµ РєСѓРєРё РІ С„РѕСЂРјР°С‚Рµ:\n"
            "sessionid2=value1; yandex_login=value2; L=value3"
        )

        cookies_file = profile_path / "Default" / "Cookies"
        if cookies_file.exists():
            cookies_edit.setPlainText(
                f"Р¤Р°Р№Р» РєСѓРєРѕРІ СЃСѓС‰РµСЃС‚РІСѓРµС‚: {cookies_file}\n"
                f"Р Р°Р·РјРµСЂ: {cookies_file.stat().st_size} bytes\n\n"
                "[Р”Р»СЏ СЂРµРґР°РєС‚РёСЂРѕРІР°РЅРёСЏ РєСѓРєРѕРІ РёСЃРїРѕР»СЊР·СѓР№С‚Рµ Р±СЂР°СѓР·РµСЂ]"
            )

        layout.addWidget(cookies_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.Accepted:
            QMessageBox.information(
                self,
                "РРЅС„РѕСЂРјР°С†РёСЏ",
                "Р”Р»СЏ РёР·РјРµРЅРµРЅРёСЏ РєСѓРєРѕРІ РѕС‚РєСЂРѕР№С‚Рµ Р±СЂР°СѓР·РµСЂ СЃ СЌС‚РёРј РїСЂРѕС„РёР»РµРј,\n"
                "РІРѕР№РґРёС‚Рµ РІ РЇРЅРґРµРєСЃ РІСЂСѓС‡РЅСѓСЋ РёР»Рё РёСЃРїРѕР»СЊР·СѓР№С‚Рµ РєРЅРѕРїРєСѓ 'РђРІС‚РѕР»РѕРіРёРЅ'."
            )
            
    def open_chrome_with_profile(self):
        """РћС‚РєСЂС‹С‚СЊ Chrome СЃ РїСЂРѕС„РёР»РµРј РІС‹Р±СЂР°РЅРЅРѕРіРѕ Р°РєРєР°СѓРЅС‚Р°"""
        import subprocess
        
        selected = self._selected_rows()
        if not selected:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "Р’С‹Р±РµСЂРёС‚Рµ Р°РєРєР°СѓРЅС‚ РґР»СЏ РѕС‚РєСЂС‹С‚РёСЏ Chrome")
            return
            
        if len(selected) > 1:
            QMessageBox.warning(self, "Р’РЅРёРјР°РЅРёРµ", "Р’С‹Р±РµСЂРёС‚Рµ С‚РѕР»СЊРєРѕ РѕРґРёРЅ Р°РєРєР°СѓРЅС‚")
            return
            
        account = self._accounts[selected[0]]
        
        # РћРїСЂРµРґРµР»СЏРµРј РїСЂРѕС„РёР»СЊ
        base_dir = Path("C:/AI/yandex")
        profile_path = account.profile_path or f".profiles/{account.name}"
        profile_path_obj = Path(profile_path)
        if not profile_path_obj.is_absolute():
            profile_path_obj = base_dir / profile_path_obj
        profile_path = str(profile_path_obj).replace("\\", "/")
            
        # Р—Р°РїСѓСЃРєР°РµРј Chrome
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        
        try:
            subprocess.Popen([
                chrome_path,
                f"--user-data-dir={profile_path}",
                "--new-window",
                "https://wordstat.yandex.ru"
            ])
            
            self.log_action(f"Chrome Р·Р°РїСѓС‰РµРЅ СЃ РїСЂРѕС„РёР»РµРј: {profile_path.split('/')[-1]}")
            
        except Exception as e:
            QMessageBox.critical(self, "РћС€РёР±РєР°", f"РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РїСѓСЃС‚РёС‚СЊ Chrome: {str(e)}")
        
    def _get_cookies_status(self, account):
        """РџРѕР»СѓС‡РёС‚СЊ СЃС‚Р°С‚СѓСЃ РєСѓРєРѕРІ РґР»СЏ Р°РєРєР°СѓРЅС‚Р° (РёСЃРїРѕР»СЊР·СѓРµРј С„СѓРЅРєС†РёСЋ РёР· С„Р°Р№Р»Р° 42)"""
        # РСЃРїРѕР»СЊР·СѓРµРј С„СѓРЅРєС†РёСЋ get_cookies_status() РёР· services/accounts.py
        return get_cookies_status(account)




