# -*- coding: utf-8 -*-
# ⚠️ РЕДАКТИРОВАТЬ ТОЛЬКО В UTF-8!
"""
Visual Browser Manager - CORRECTED
Uses 5 working profiles (NOT wordstat_main!)
According to keyset дорожная карта.md
"""

import asyncio
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime
from enum import Enum
from playwright.async_api import async_playwright, Page, BrowserContext
from ..services.proxy_manager import ProxyManager
from ..utils.proxy import parse_proxy
from ..utils.text_fix import WORDSTAT_FETCH_NORMALIZER_SCRIPT

class BrowserStatus(Enum):
    IDLE = "idle"
    STARTING = "starting"
    LOGGED_IN = "logged_in"
    LOGIN_REQUIRED = "login_required"
    PARSING = "parsing"
    ERROR = "error"

class BrowserInstance:
    """Single browser instance data"""
    def __init__(self, name):
        self.name = name
        # Каждый аккаунт использует СВОЙ профиль
        self.profile_path = f"C:\\AI\\yandex\\.profiles\\{name}"
        self.context = None
        self.page = None
        self.status = BrowserStatus.IDLE
        self.proxy_obj = None
        self.proxy_id: Optional[str] = None

class VisualBrowserManager:
    """Manager for multiple Chrome browsers with working profiles"""
    
    # CORRECT CONFIGURATION from keyset дорожная карта.md
    CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    # 5 WORKING PROFILES (NOT wordstat_main!)
    AUTHORIZED_PROFILES = [
        "dsmismirnov",
        "kuznepetya", 
        "vfefyodorov",
        "volkovsvolkow",
        "semenovmsemionov"
    ]
    
    def __init__(self, num_browsers: int = 3):
        self.num_browsers = min(num_browsers, len(self.AUTHORIZED_PROFILES))
        self.browsers = {}
        self.playwright = None
        self.proxy_manager = ProxyManager.instance()
        
    async def start_browser(self, browser_id: int, account_name: str,
                           profile_path: str, proxy: Optional[str] = None,
                           proxy_id: Optional[str] = None):
        """Start Chrome with specified profile"""
        
        base_dir = Path("C:/AI/yandex")

        if not profile_path or profile_path == ".profiles/demo_account":
            profile_path_obj = base_dir / ".profiles" / account_name
        else:
            profile_path_obj = Path(profile_path)
            if not profile_path_obj.is_absolute():
                profile_path_obj = base_dir / profile_path_obj

        profile_path = str(profile_path_obj).replace("\\", "/")
        
        print(f"[Browser {browser_id}] Starting Chrome for account: {account_name}")
        print(f"[Browser {browser_id}] Using profile: {profile_path}")
        
        browser_instance = BrowserInstance(account_name)
        browser_instance.profile_path = profile_path
        
        try:
            proxy_obj = None
            proxy_config: Optional[Dict[str, str]] = None

            if proxy_id:
                proxy_obj = self.proxy_manager.acquire(proxy_id)
                if proxy_obj:
                    proxy_config = proxy_obj.playwright_config()
                    server_value = proxy_config.get("server")
                    if server_value and "://" not in server_value:
                        proxy_config["server"] = f"http://{server_value}"

            if proxy_config is None and proxy:
                parsed = parse_proxy(proxy)
                if parsed:
                    server_value = parsed.get("server")
                    if server_value and "://" not in server_value:
                        parsed["server"] = f"http://{server_value}"
                    proxy_config = parsed

            if proxy_config:
                print(
                    f"[Browser {browser_id}] Proxy: {proxy_config.get('server')} "
                    f"(user: {proxy_config.get('username', 'none')})"
                )
            else:
                print(f"[Browser {browser_id}] Proxy: not set")

            # Используем launch_persistent_context с прокси (правильный способ из файла 41!)
            browser_instance.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                channel="chrome",  # Системный Chrome
                headless=False,
                proxy=proxy_config,  # ← ВАЖНО: прокси на уровне Playwright API!
                viewport={"width": 1280, "height": 900},
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--start-maximized',
                    '--no-first-run',
                    '--no-default-browser-check'
                ]
            )
            await browser_instance.context.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            for existing_page in browser_instance.context.pages:
                await existing_page.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
                try:
                    await existing_page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
                except Exception:
                    pass
            browser_instance.proxy_obj = proxy_obj
            browser_instance.proxy_id = proxy_obj.id if proxy_obj else proxy_id
            
            # Получаем или создаем страницу
            if browser_instance.context.pages:
                browser_instance.page = browser_instance.context.pages[0]
            else:
                browser_instance.page = await browser_instance.context.new_page()
            
            # Открываем Wordstat
            await browser_instance.page.goto("https://wordstat.yandex.ru/?region=225", wait_until="networkidle")
            browser_instance.status = BrowserStatus.LOGGED_IN
            print(f"[Browser {browser_id}] Chrome started with Playwright")
                
            self.browsers[browser_id] = browser_instance
            return browser_instance
            
        except Exception as e:
            print(f"[Browser] Error: {e}")
            browser_instance.status = BrowserStatus.ERROR
            if proxy_obj:
                self.proxy_manager.release(proxy_obj)
            return browser_instance
    
    async def start_all_browsers(self, accounts: List[Dict]) -> None:
        """Start browsers for multiple accounts ПАРАЛЛЕЛЬНО"""
        
        print(f"\n[VISUAL] Starting {self.num_browsers} browsers ПАРАЛЛЕЛЬНО...")
        
        # Start playwright (Playwright сам управляет процессами)
        self.playwright = await async_playwright().start()
        
        # Подготавливаем задачи для параллельного запуска
        tasks = []
        for i in range(self.num_browsers):
            if i < len(accounts):
                account = accounts[i]
                account_name = account.get('name', self.AUTHORIZED_PROFILES[i])
                profile_path = account.get('profile_path', f".profiles/{account_name}")
                proxy = account.get('proxy')
                proxy_id = account.get('proxy_id')
            else:
                # Use from authorized profiles if not enough accounts
                account_name = self.AUTHORIZED_PROFILES[i]
                profile_path = f".profiles/{account_name}"
                proxy = None
                proxy_id = None
            
            # Добавляем задачу в список (НЕ ЖДЕМ!)
            task = self.start_browser(
                browser_id=i,
                account_name=account_name,
                profile_path=profile_path,
                proxy=proxy,
                proxy_id=proxy_id
            )
            tasks.append(task)
        
        # Запускаем ВСЕ браузеры ПАРАЛЛЕЛЬНО!
        await asyncio.gather(*tasks, return_exceptions=True)
        
        print("\n" + "="*60)
        print(f"  {self.num_browsers} BROWSERS STARTED")
        print("="*60)
        for i, (browser_id, browser) in enumerate(self.browsers.items()):
            print(f"  [{i}] {browser.name}: READY")
        print("="*60 + "\n")
    
    async def close_all(self):
        """Close all browsers"""
        for browser_id, browser_instance in self.browsers.items():
            try:
                if browser_instance.context:
                    await browser_instance.context.close()
                    print(f"[Browser {browser_id}] Closed")
            except Exception:
                pass
            finally:
                if browser_instance.proxy_obj:
                    self.proxy_manager.release(browser_instance.proxy_obj)
                    browser_instance.proxy_obj = None
        
        if self.playwright:
            await self.playwright.stop()
            print("[Playwright] Stopped")
        
        self.browsers = {}
    
    def calculate_window_position(self, browser_id: int) -> Dict[str, int]:
        """Window position (only one browser)"""
        return {'x': 0, 'y': 0, 'width': 1920, 'height': 1080}
    
    async def check_login_status(self, page: Page) -> bool:
        """Check if logged in"""
        try:
            await page.goto("https://wordstat.yandex.ru/", wait_until="networkidle")
            await page.wait_for_timeout(2000)
            return "passport" not in page.url
        except:
            return False

    async def wait_for_all_logins(self, timeout: int = 300, poll_delay: float = 3.0) -> bool:
        """Poll launched browsers until each confirms Wordstat login or timeout expires."""
        if not self.browsers:
            print("[VISUAL] No browsers were launched; nothing to wait for")
            return False

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while loop.time() < deadline:
            pending = []
            for browser_id, browser in self.browsers.items():
                if not browser.page:
                    pending.append(browser_id)
                    continue

                try:
                    authorized = await self.check_login_status(browser.page)
                except Exception as exc:  # noqa: BLE001
                    print(f"[Browser {browser_id}] Login check failed: {exc}")
                    browser.status = BrowserStatus.ERROR
                    continue

                if authorized:
                    if browser.status != BrowserStatus.LOGGED_IN:
                        print(f"[Browser {browser_id}] Login confirmed")
                    browser.status = BrowserStatus.LOGGED_IN
                else:
                    browser.status = BrowserStatus.LOGIN_REQUIRED
                    pending.append(browser_id)

            if not pending:
                return True

            await asyncio.sleep(poll_delay)

        print("[VISUAL] Timeout waiting for logins")
        return False

    def show_status(self) -> None:
        """Print current status of managed browsers to stdout."""
        if not self.browsers:
            print("[VISUAL] Browsers are not running")
            return

        print("\n[VISUAL] Browser statuses:")
        for browser_id, browser in self.browsers.items():
            status = browser.status.value if hasattr(browser.status, "value") else str(browser.status)
            print(f"  [{browser_id}] {browser.name}: {status} ({browser.profile_path})")
        print()
