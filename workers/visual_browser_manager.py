"""
ВИЗУАЛЬНЫЙ МЕНЕДЖЕР БРАУЗЕРОВ
Управление несколькими браузерами с визуальным интерфейсом
Как в DirectParser - видим все браузеры, логинимся где нужно
"""

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

from playwright.async_api import async_playwright, Browser, BrowserContext, Page


def _resolve_chrome_executable() -> Optional[str]:
    """Find installed Chrome executable."""
    candidates = [
        Path(r"C:/Program Files/Google/Chrome/Application/chrome.exe"),
        Path(r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
        Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    # Try to locate via default installation root
    base = Path("C:/Program Files/Google").glob("**/chrome.exe")
    for item in base:
        return str(item)
    return None


class BrowserStatus(Enum):
    """Статусы браузеров"""
    NOT_STARTED = "Не запущен"
    STARTING = "Запускается..."
    LOGIN_REQUIRED = "Требуется логин"
    LOGGED_IN = "Залогинен"
    PARSING = "Парсинг..."
    ERROR = "Ошибка"
    IDLE = "Ожидание"


@dataclass
class BrowserInstance:
    """Информация об экземпляре браузера"""
    id: int
    name: str
    profile_path: str
    proxy: Optional[str]
    status: BrowserStatus
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    last_activity: Optional[datetime] = None
    phrases_parsed: int = 0
    errors: int = 0


class VisualBrowserManager:
    """
    Менеджер визуальных браузеров
    - Запускает браузеры в видимом режиме
    - Управляет позиционированием окон
    - Отслеживает статусы
    - Позволяет логиниться параллельно
    """
    
    # ВАЖНО: Используем РЕАЛЬНЫЕ профили аккаунтов с авторизацией!
    # Каждый аккаунт имеет свой профиль браузера
    AUTHORIZED_PROFILES = [
        "dsmismirnov",        # Основной аккаунт (авторизован)
        "kuznepetya",         # Дополнительный аккаунт 
        "vfefyodorov",        # Дополнительный аккаунт
        "volkovsvolkow",      # Дополнительный аккаунт
        "semenovmsemionov"    # Дополнительный аккаунт
    ]
    
    # НЕ ИСПОЛЬЗУЕМ:
    # "wordstat_main" - старый тестовый профиль
    
    def __init__(self, num_browsers: int = 3):
        self.num_browsers = min(num_browsers, len(self.AUTHORIZED_PROFILES))  # Не больше чем есть профилей
        self.browsers: Dict[int, BrowserInstance] = {}
        self.playwright = None
        self.screen_width = 1920
        self.screen_height = 1080
        # Браузеры будут запускаться максимизированными
        self.browser_width = self.screen_width
        self.browser_height = self.screen_height
        
    def calculate_window_position(self, browser_id: int) -> Dict[str, int]:
        """Рассчитать позицию окна браузера на экране"""
        # Правильное расположение окон для видимости всех браузеров
        positions = [
            {'x': 0, 'y': 0, 'width': 960, 'height': 1080},      # Левая половина
            {'x': 960, 'y': 0, 'width': 960, 'height': 1080},    # Правая половина
            {'x': 0, 'y': 540, 'width': 960, 'height': 540},     # Нижний левый
            {'x': 960, 'y': 540, 'width': 960, 'height': 540},   # Нижний правый
            {'x': 480, 'y': 270, 'width': 960, 'height': 540}    # Центр
        ]
        
        if browser_id < len(positions):
            return positions[browser_id]
        else:
            # Для дополнительных браузеров - каскадное расположение
            cascade_offset = 50
            x_offset = browser_id * cascade_offset
            y_offset = browser_id * cascade_offset
            
            return {
                'x': x_offset,
                'y': y_offset,
                'width': self.browser_width - 100,  # Немного меньше для видимости других окон
                'height': self.browser_height - 100
            }
    
    async def start_browser(self, browser_id: int, account_name: str, 
                           profile_path: str, proxy: Optional[str] = None) -> BrowserInstance:
        """Запустить браузер с визуальным интерфейсом"""
        
        browser_instance = BrowserInstance(
            id=browser_id,
            name=account_name,
            profile_path=profile_path,
            proxy=proxy,
            status=BrowserStatus.STARTING,
            phrases_parsed=0,
            errors=0
        )
        
        self.browsers[browser_id] = browser_instance
        
        # Рассчитываем позицию окна
        pos = self.calculate_window_position(browser_id)
        
        # Настройки прокси
        print(f"[Browser {browser_id}] Raw proxy value: {proxy}")
        proxy_config = None
        if proxy:
            try:
                # Поддержка разных форматов прокси
                if isinstance(proxy, dict):
                    # Если прокси передан как словарь
                    proxy_config = {
                        "server": f"http://{proxy['server']}",
                        "username": proxy.get('username', ''),
                        "password": proxy.get('password', '')
                    }
                else:
                    # Если прокси передан как строка
                    proxy_str = str(proxy)
                    
                    # Убираем префикс http:// или https://
                    proxy_str = proxy_str.replace("http://", "").replace("https://", "")
                    
                    # Формат: user:pass@ip:port
                    if "@" in proxy_str:
                        auth, server = proxy_str.split("@")
                        if ":" in auth:
                            user, password = auth.split(":", 1)
                            proxy_config = {
                                "server": f"http://{server}",
                                "username": user,
                                "password": password
                            }
                        else:
                            proxy_config = {"server": f"http://{server}"}
                    else:
                        # Простой формат: ip:port
                        proxy_config = {"server": f"http://{proxy_str}"}
                
                print(f"[Browser {browser_id}] Proxy configured: {proxy_config['server']}")
                if 'username' in proxy_config:
                    print(f"[Browser {browser_id}] Auth: {proxy_config['username']}:***")
            except Exception as e:
                print(f"[Browser {browser_id}] Error configuring proxy: {e}")
                print(f"[Browser {browser_id}] Proxy string was: {proxy}")
        
        # Запускаем браузер
        try:
            # ВАЖНО: Используем правильные профили из BROWSER_SETTINGS.md!
            # Обрабатываем путь к профилю
            profile_path_obj = Path(profile_path)
            
            # ВСЕГДА используем абсолютные пути к профилям
            if not profile_path_obj.is_absolute():
                # Конвертируем относительный путь в абсолютный
                if profile_path.startswith(".profiles"):
                    # Правильный путь: C:\AI\yandex\.profiles\accountname
                    profile_path_obj = Path("C:/AI/yandex") / profile_path
                else:
                    profile_path_obj = Path("C:/AI/yandex/.profiles") / profile_path.replace(".profiles/", "")
            
            # Преобразуем в строку с прямыми слешами
            unique_profile = str(profile_path_obj.absolute()).replace("\\", "/")
            print(f"[Browser {browser_id}] Using profile: {unique_profile}")
            
            # Проверяем что профиль существует
            if not Path(unique_profile).exists():
                print(f"[Browser {browser_id}] ERROR: Profile doesn't exist at: {unique_profile}")
                print(f"[Browser {browser_id}] Creating new profile directory...")
                Path(unique_profile).mkdir(parents=True, exist_ok=True)
                # НЕ создаем новый профиль! Используем существующий на основе имени
                fallback_profile = Path("C:/AI/yandex/.profiles") / account_name
                if fallback_profile.exists():
                    unique_profile = str(fallback_profile.absolute()).replace("\\", "/")
                    print(f"[Browser {browser_id}] Using fallback profile: {unique_profile}")
                else:
                    print(f"[Browser {browser_id}] ERROR: No existing profile found for {account_name}!")
                    return browser_instance
            
            # Параметры браузера - БЕЗ инкогнито, чтобы сохранялись куки!
            browser_args = [
                f'--window-position={pos["x"]},{pos["y"]}',
                f'--window-size={pos["width"]},{pos["height"]}',
                '--disable-blink-features=AutomationControlled',
                '--start-maximized',  # Все браузеры максимизированы
                '--no-first-run',
                '--no-default-browser-check',
                '--disable-popup-blocking',
                # НЕ добавляем --incognito чтобы сохранялись куки!
                # НЕ добавляем --user-data-dir т.к. playwright сам управляет им
            ]
            
            # Убираем пустые аргументы
            browser_args = [arg for arg in browser_args if arg]
            
            # Если есть прокси - добавляем его
            if proxy_config:
                # Убираем --no-proxy-server если есть прокси
                browser_args = [arg for arg in browser_args if arg != '--no-proxy-server']
                print(f"[Browser {browser_id}] Используется прокси: {proxy_config['server']}")
            else:
                print(f"[Browser {browser_id}] Прокси не используется")
            
            launch_kwargs = {
                "user_data_dir": unique_profile,
                "headless": False,  # ВАЖНО: видимый режим
                "proxy": proxy_config if proxy_config else None,  # Прокси только если задан
                "viewport": {'width': pos['width'], 'height': pos['height']},
                "no_viewport": False,  # Используем viewport
                "ignore_https_errors": True,
                "bypass_csp": True,  # Обход CSP
                "args": browser_args,
            }

            chrome_path = Path(r"C:/Program Files/Google/Chrome/Application/chrome.exe")
            if chrome_path.exists():
                launch_kwargs["executable_path"] = str(chrome_path)
                print(f"[Browser {browser_id}] Using Chrome executable at {launch_kwargs['executable_path']}")
            else:
                launch_kwargs["channel"] = "chrome"
                print(f"[Browser {browser_id}] Chrome executable not found, falling back to channel='chrome'")

            context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
            
            browser_instance.context = context
            browser_instance.status = BrowserStatus.LOGIN_REQUIRED
            
            # Создаем первую страницу
            page = await context.new_page()
            browser_instance.page = page
            
            # Устанавливаем размер viewport для страницы
            await page.set_viewport_size({
                'width': pos['width'], 
                'height': pos['height']
            })
            
            # Переходим на Wordstat
            await page.goto("https://wordstat.yandex.ru", wait_until="domcontentloaded", timeout=30000)
            
            # Обработка панели с куками Яндекса
            await asyncio.sleep(5)  # Ждем полную загрузку страницы и появление панели
            try:
                # Проверяем наличие панели с куками по тексту или классу
                cookie_found = False
                
                # Яндекс использует специфичные селекторы для панели с куками
                cookie_selectors = [
                    # Основные селекторы Яндекса
                    'button[data-id="button-all"]',  # Кнопка "Принять все"
                    'button[data-id="accept-all"]',
                    '.cookie-informer button',
                    '.gdpr-popup__button',
                    '.notification__button',
                    # Текстовые селекторы
                    'button:has-text("Принять")',
                    'button:has-text("Принять все")',
                    'button:has-text("Хорошо")',
                    'button:has-text("Согласен")',
                    'button:has-text("ОК")',
                    'button:has-text("Accept")',
                    # Классы кнопок Яндекса
                    'button.Button2_view_action',
                    'button.Button2_type_submit',
                    'button.Button_view_action',
                ]
                
                for selector in cookie_selectors:
                    try:
                        # Проверяем видимость кнопки
                        cookie_button = await page.wait_for_selector(selector, 
                                                                     timeout=1000, 
                                                                     state='visible')
                        if cookie_button:
                            # Кликаем по кнопке
                            await cookie_button.click()
                            print(f"[Browser {browser_id}] Cookie panel accepted via: {selector}")
                            cookie_found = True
                            await asyncio.sleep(2)  # Ждем закрытия панели
                            break
                    except:
                        continue
                
                if not cookie_found:
                    print(f"[Browser {browser_id}] No cookie panel found")
                    
            except Exception as e:
                print(f"[Browser {browser_id}] Cookie panel processing: {str(e)[:50]}")
            
            # Проверяем статус логина
            await asyncio.sleep(2)
            is_logged = await self.check_login_status(page)
            
            if is_logged:
                browser_instance.status = BrowserStatus.LOGGED_IN
                print(f"[Browser {browser_id}] [OK] Already logged in")
            else:
                browser_instance.status = BrowserStatus.LOGIN_REQUIRED
                print(f"[Browser {browser_id}] [!] Login required")
            
            browser_instance.last_activity = datetime.now()
            return browser_instance
            
        except Exception as e:
            print(f"[Browser {browser_id}] Ошибка запуска: {e}")
            browser_instance.status = BrowserStatus.ERROR
            return browser_instance
    
    async def check_login_status(self, page: Page) -> bool:
        """Проверить, залогинен ли пользователь"""
        try:
            # Ищем элементы, которые есть только у залогиненного пользователя
            login_indicators = [
                'input[name="text"]',  # Поле поиска Wordstat
                '.b-form-input__input',
                '.b-word-statistics-search'
            ]
            
            for selector in login_indicators:
                try:
                    element = await page.wait_for_selector(selector, timeout=3000)
                    if element:
                        return True
                except:
                    continue
            
            # Проверяем наличие кнопки логина (значит не залогинен)
            login_buttons = [
                'a[href*="passport.yandex"]',
                '.button_theme_passport',
                'text=Войти'
            ]
            
            for selector in login_buttons:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        return False
                except:
                    continue
                    
            return False
            
        except Exception as e:
            print(f"[Login Check] Ошибка проверки: {e}")
            return False
    
    async def cleanup_hanging_browsers(self):
        """Очистить висящие процессы браузеров"""
        import subprocess
        try:
            # Завершаем все процессы Chrome
            subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"], capture_output=True)
            print("[CLEANUP] Висящие процессы Chrome завершены")
        except:
            pass
            
    async def start_all_browsers(self, accounts: List[Dict]) -> None:
        """Запустить все браузеры последовательно"""
        # Очищаем висящие процессы
        await self.cleanup_hanging_browsers()
        
        # Запускаем playwright
        self.playwright = await async_playwright().start()
        
        # Запускаем браузеры ПОСЛЕДОВАТЕЛЬНО с паузой между ними
        for i in range(self.num_browsers):
            print(f"\n[VISUAL] Запуск браузера {i+1}/{self.num_browsers}...")
            
            # ПРАВИЛЬНОЕ ИСПОЛЬЗОВАНИЕ АККАУНТОВ!
            # Если переданы аккаунты - используем их
            if i < len(accounts) and accounts[i].get('name'):
                account = accounts[i]
                account_name = account['name']
                
                # Правильный путь к профилю - всегда абсолютный!
                if account.get('profile_path'):
                    profile_path = account['profile_path']
                    # Конвертируем относительный путь в абсолютный
                    if not profile_path.startswith('C:'):
                        profile_path = f"C:/AI/yandex/{profile_path}"
                else:
                    profile_path = f"C:/AI/yandex/.profiles/{account_name}"
                
                proxy = account.get('proxy')
            else:
                # Если аккаунт не передан - берем из авторизованных профилей
                if i < len(self.AUTHORIZED_PROFILES):
                    account_name = self.AUTHORIZED_PROFILES[i]
                    profile_path = f"C:/AI/yandex/.profiles/{account_name}"
                else:
                    print(f"[ERROR] Не хватает профилей для браузера {i}")
                    continue
                proxy = None
            
            print(f"[VISUAL] Using profile: {account_name}")
            print(f"[VISUAL] Profile path: {profile_path}")
            
            # Проверяем что профиль существует
            if not Path(profile_path).exists():
                print(f"[WARNING] Профиль не найден: {profile_path}")
                print(f"[INFO] Создаем новый профиль...")
            
            await self.start_browser(
                browser_id=i,
                account_name=account_name,
                profile_path=profile_path,
                proxy=proxy
            )
            
            # Пауза между запусками для стабильности
            if i < self.num_browsers - 1:
                await asyncio.sleep(2)
        
        print(f"\n{'='*60}")
        print(f"  ЗАПУЩЕНО {len(self.browsers)} БРАУЗЕРОВ")
        print(f"{'='*60}")
        
        for browser_id, browser in self.browsers.items():
            status_icon = "[OK]" if browser.status == BrowserStatus.LOGGED_IN else "[!]"
            print(f"  [{browser_id}] {browser.name}: {status_icon} {browser.status.value}")
        
        print(f"{'='*60}\n")
    
    async def wait_for_all_logins(self, timeout: int = 300) -> bool:
        """
        Ожидание логина во всех браузерах
        Пользователь должен вручную залогиниться в каждом окне
        """
        print("\n[!] REQUIRES LOGIN IN BROWSERS:")
        print("1. Залогиньтесь в каждом открытом окне браузера")
        print("2. После логина парсер автоматически определит это")
        print(f"3. Ожидание до {timeout} секунд...\n")
        
        start_time = time.time()
        logged_in = set()
        
        while time.time() - start_time < timeout:
            # Проверяем статус каждого браузера
            for browser_id, browser in self.browsers.items():
                if browser_id in logged_in:
                    continue
                
                if browser.page:
                    is_logged = await self.check_login_status(browser.page)
                    if is_logged:
                        browser.status = BrowserStatus.LOGGED_IN
                        logged_in.add(browser_id)
                        print(f"[OK] Browser {browser_id} ({browser.name}) - LOGGED IN")
            
            # Если все залогинены - выходим
            if len(logged_in) == len(self.browsers):
                print("\n[OK] ALL BROWSERS LOGGED IN!")
                return True
            
            # Показываем прогресс
            remaining = len(self.browsers) - len(logged_in)
            if remaining > 0:
                print(f"\rОжидание логина в {remaining} браузерах... ", end="")
            
            await asyncio.sleep(2)
        
        print(f"\n[!] Timeout! Logged in {len(logged_in)}/{len(self.browsers)} browsers")
        return len(logged_in) > 0
    
    async def minimize_all_browsers(self):
        """Минимизировать все браузеры для фоновой работы"""
        for browser_id, browser in self.browsers.items():
            if browser.page:
                try:
                    # Минимизация через JavaScript
                    await browser.page.evaluate("window.minimize ? window.minimize() : null")
                    print(f"[Browser {browser_id}] Минимизирован")
                except:
                    pass
    
    async def parse_phrase_on_browser(self, browser_id: int, phrase: str) -> Optional[int]:
        """Парсить фразу на конкретном браузере"""
        browser = self.browsers.get(browser_id)
        if not browser or browser.status != BrowserStatus.LOGGED_IN:
            return None
        
        try:
            browser.status = BrowserStatus.PARSING
            page = browser.page
            
            # Вводим фразу
            input_selectors = [
                'input[name="text"]',
                'input[type="search"]',
                '.b-form-input__input'
            ]
            
            for selector in input_selectors:
                try:
                    input_field = await page.query_selector(selector)
                    if input_field:
                        await input_field.click()
                        await page.keyboard.press("Control+A")
                        await page.keyboard.press("Delete")
                        await input_field.type(phrase, delay=50)
                        await page.keyboard.press("Enter")
                        break
                except:
                    continue
            
            # Ждем результат
            await asyncio.sleep(1.5)
            
            # Извлекаем частотность
            freq_selectors = [
                '.b-word-statistics-info__td:has-text("показов в месяц")',
                'td:has-text("показов")',
                '.b-word-statistics__info-wrapper'
            ]
            
            for selector in freq_selectors:
                try:
                    element = await page.wait_for_selector(selector, timeout=3000)
                    if element:
                        text = await element.inner_text()
                        # Извлекаем число из текста
                        import re
                        numbers = re.findall(r'[\d\s]+', text)
                        if numbers:
                            freq = int(numbers[0].replace(' ', '').replace('\xa0', ''))
                            browser.phrases_parsed += 1
                            browser.status = BrowserStatus.IDLE
                            return freq
                except:
                    continue
            
            browser.errors += 1
            browser.status = BrowserStatus.IDLE
            return None
            
        except Exception as e:
            print(f"[Browser {browser_id}] Ошибка парсинга: {e}")
            browser.errors += 1
            browser.status = BrowserStatus.ERROR
            return None
    
    async def parse_batch_parallel(self, phrases: List[str]) -> Dict[str, int]:
        """Парсить батч фраз параллельно на всех браузерах"""
        results = {}
        
        # Распределяем фразы по браузерам
        browser_ids = [b_id for b_id, b in self.browsers.items() 
                      if b.status in [BrowserStatus.LOGGED_IN, BrowserStatus.IDLE]]
        
        if not browser_ids:
            print("[!] No available browsers for parsing")
            return results
        
        # Парсим по частям
        for i in range(0, len(phrases), len(browser_ids)):
            batch = phrases[i:i+len(browser_ids)]
            tasks = []
            
            for j, phrase in enumerate(batch):
                browser_id = browser_ids[j % len(browser_ids)]
                task = self.parse_phrase_on_browser(browser_id, phrase)
                tasks.append((phrase, task))
            
            # Ждем завершения батча
            for phrase, task in tasks:
                freq = await task
                if freq is not None:
                    results[phrase] = freq
                    print(f"[OK] {phrase}: {freq:,}")
                else:
                    print(f"[ERROR] {phrase}: error")
        
        return results
    
    async def close_all(self):
        """Закрыть все браузеры корректно"""
        print("[MANAGER] Закрываю все браузеры...")
        
        # Закрываем все контексты
        for browser_id, browser in self.browsers.items():
            try:
                if browser.context:
                    # Закрываем все страницы
                    pages = browser.context.pages
                    for page in pages:
                        try:
                            await page.close()
                        except:
                            pass
                    
                    # Закрываем контекст
                    await browser.context.close()
                    browser.context = None
                    browser.status = BrowserStatus.NOT_STARTED
                    print(f"[Browser {browser_id}] Закрыт")
            except Exception as e:
                print(f"[Browser {browser_id}] Ошибка при закрытии: {e}")
        
        # Останавливаем playwright
        if self.playwright:
            try:
                await self.playwright.stop()
                self.playwright = None
                print("[MANAGER] Playwright остановлен")
            except:
                pass
        
        # Очищаем список браузеров
        self.browsers.clear()
        print("[OK] All browsers closed")


# Пример использования
async def test_visual_manager():
    """Тестовый запуск визуального менеджера"""
    
    # Тестовые аккаунты
    accounts = [
        {"name": "Account1", "profile_path": ".profiles/account1", "proxy": None},
        {"name": "Account2", "profile_path": ".profiles/account2", "proxy": None},
        {"name": "Account3", "profile_path": ".profiles/account3", "proxy": None},
    ]
    
    # Тестовые фразы
    phrases = [
        "купить квартиру",
        "ремонт квартир",
        "заказать пиццу",
        "доставка еды",
        "такси москва"
    ]
    
    # Создаем менеджер
    manager = VisualBrowserManager(num_browsers=3)
    
    try:
        # Запускаем браузеры
        await manager.start_all_browsers(accounts)
        
        # Ждем логина
        logged_in = await manager.wait_for_all_logins(timeout=300)
        
        if logged_in:
            # Минимизируем для фоновой работы
            await manager.minimize_all_browsers()
            
            # Парсим фразы
            results = await manager.parse_batch_parallel(phrases)
            
            print(f"\n{'='*60}")
            print(f"  РЕЗУЛЬТАТЫ ПАРСИНГА")
            print(f"{'='*60}")
            for phrase, freq in results.items():
                print(f"  {phrase}: {freq:,}")
            print(f"{'='*60}")
        
    finally:
        await manager.close_all()


if __name__ == "__main__":
    asyncio.run(test_visual_manager())
