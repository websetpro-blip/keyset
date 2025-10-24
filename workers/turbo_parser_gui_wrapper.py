#!/usr/bin/env python3
"""
GUI-обертка над рабочим turbo_parser_10tabs.py.
Добавляет callbacks для real-time отображения в GUI.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Callable, Optional, Dict, List, Any

from playwright.async_api import async_playwright, BrowserContext, Page

try:
    from ..utils.proxy import proxy_to_playwright
except ImportError:
    # Fallback для прямого запуска
    import sys
    from pathlib import Path as _Path
    base_dir = _Path(__file__).resolve().parent.parent
    if str(base_dir) not in sys.path:
        sys.path.append(str(base_dir))
    from utils.proxy import proxy_to_playwright

# Настройки (из оригинального парсера)
TABS_COUNT = 10
DELAY_BETWEEN_TABS = 0.3
DELAY_BETWEEN_QUERIES = 0.5
RESPONSE_TIMEOUT = 3000


class TurboParserGUI:
    """
    GUI-обертка над рабочим turbo_parser_10tabs.py.
    Добавляет callbacks для real-time отображения в GUI.
    """

    def __init__(
        self,
        on_result: Optional[Callable[[str, dict], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
        on_log: Optional[Callable[[str], None]] = None
    ):
        self.on_result = on_result
        self.on_progress = on_progress
        self.on_log = on_log
        
        self.results = {}
        self.results_lock = asyncio.Lock()
        self.is_running = False
        self.context: Optional[BrowserContext] = None
        self.pages: List[Page] = []
        self.processed_count = 0
        self.total_phrases = 0

    def _log(self, message: str):
        """Отправка лога в GUI."""
        if self.on_log:
            self.on_log(message)
        else:
            print(message)

    def _emit_result(self, phrase: str, result: dict):
        """Отправка результата в GUI."""
        if self.on_result:
            self.on_result(phrase, result)

    def _emit_progress(self, current: int, total: int):
        """Отправка прогресса в GUI."""
        if self.on_progress:
            self.on_progress(current, total)

    async def parse_phrases(
        self,
        account: str,
        profile_path: str,
        phrases: List[str],
        modes: dict,
        region: int = 225,
        proxy_uri: Optional[str] = None
    ) -> Dict[str, dict]:
        """
        Главный метод парсинга с callbacks.
        
        Args:
            account: Имя аккаунта
            profile_path: Путь к Chrome-профилю
            phrases: Список фраз для парсинга
            modes: {"ws": True, "qws": False, "bws": False}
            region: ID региона Яндекс
            proxy_uri: Прокси в формате http://user:pass@host:port
        
        Returns:
            Dict[phrase, {ws, qws, bws}]
        """
        self.is_running = True
        self.results = {}
        self.processed_count = 0
        self.total_phrases = len(phrases)
        
        try:
            self._log(f"[СТАРТ] Парсинг {len(phrases)} фраз для аккаунта {account}")
            
            # Парсинг прокси
            proxy_config = None
            if proxy_uri:
                proxy_config = proxy_to_playwright(proxy_uri)
                if proxy_config:
                    self._log(f"[PROXY] Используется: {proxy_config['server']}")
                else:
                    self._log(f"[PROXY] Не удалось разобрать прокси: {proxy_uri}")
            
            async with async_playwright() as p:
                # 1. ЗАПУСК CHROME (логика из turbo_parser_10tabs.py)
                self._log(f"[1/6] Запуск Chrome с профилем {account}...")
                self.context = await p.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    headless=False,
                    channel="chrome",
                    proxy=proxy_config,
                    args=[
                        "--start-maximized",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-features=IsolateOrigins,site-per-process",
                        "--disable-site-isolation-trials",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    viewport=None,
                    locale="ru-RU",
                )

                # 2. СОЗДАНИЕ ВКЛАДОК
                self._log(f"[2/6] Создание {TABS_COUNT} вкладок...")
                
                async def create_tab(index: int) -> Page:
                    page = await self.context.new_page()
                    self._log(f"  [OK] Вкладка {index + 1} создана")
                    return page

                self.pages = await asyncio.gather(
                    *[create_tab(i) for i in range(TABS_COUNT)]
                )
                self._log(f"[OK] Создано {len(self.pages)} вкладок")

                # 3. ЗАГРУЗКА WORDSTAT
                self._log(f"[3/6] Загрузка Wordstat во всех вкладках...")
                
                async def load_wordstat(page: Page, index: int) -> bool:
                    try:
                        await page.goto(
                            "https://wordstat.yandex.ru/?region=225",
                            wait_until="domcontentloaded",
                            timeout=15000,
                        )
                        # УЛУЧШЕНИЕ: ждём затухания сети
                        await page.wait_for_load_state("networkidle", timeout=5000)
                        self._log(f"  [OK] Вкладка {index + 1}: Wordstat загружен")
                        return True
                    except Exception as e:
                        self._log(f"  [ERROR] Вкладка {index + 1}: {e}")
                        return False

                tasks = []
                for i, page in enumerate(self.pages):
                    tasks.append(load_wordstat(page, i))
                    await asyncio.sleep(DELAY_BETWEEN_TABS)

                results_load = await asyncio.gather(*tasks)
                working_pages = [p for i, p in enumerate(self.pages) if results_load[i]]

                self._log(f"[OK] Wordstat загружен на {len(working_pages)}/{TABS_COUNT} вкладках")
                
                if not working_pages:
                    self._log("[ERROR] Ни одна вкладка не загрузилась, парсер остановлен.")
                    return {}

                # 4. ОБРАБОТЧИК ОТВЕТОВ (с callbacks)
                self._log("[4/6] Настройка обработчиков API...")

                async def handle_response(response):
                    if "/wordstat/api" not in response.url or response.status != 200:
                        return
                    
                    try:
                        data = await response.json()
                        post_data = response.request.post_data
                        phrase = None
                        
                        if post_data:
                            try:
                                payload = json.loads(post_data)
                                phrase = payload.get("searchValue")
                            except json.JSONDecodeError:
                                pass

                        freq = (
                            data.get("totalValue")
                            or data.get("data", {}).get("totalValue")
                            or 0
                        )
                        
                        if phrase:
                            async with self.results_lock:
                                if phrase not in self.results:
                                    # Формируем результат для GUI
                                    result = {
                                        "ws": freq if modes.get("ws", True) else 0,
                                        "qws": 0,  # TODO: реализовать "WS"
                                        "bws": 0,  # TODO: реализовать !WS
                                        "timestamp": time.time()
                                    }
                                    self.results[phrase] = result
                                    
                                    # Отправляем результат в GUI
                                    self._emit_result(phrase, result)
                                    
                                    # Обновляем прогресс
                                    self.processed_count += 1
                                    self._emit_progress(self.processed_count, self.total_phrases)
                                    
                                    self._log(f"    [+] {phrase}: {freq:,}")
                    except Exception:
                        pass

                for page in working_pages:
                    page.on("response", handle_response)
                self._log("[OK]")

                # 5. ПОДГОТОВКА ВКЛАДОК
                self._log(f"[5/6] Подготовка вкладок к парсингу...")
                for i, page in enumerate(working_pages):
                    try:
                        await page.wait_for_selector(
                            "input[name='text'], input[placeholder]",
                            timeout=5000,
                        )
                        self._log(f"  [OK] Вкладка {i + 1} готова")
                    except TimeoutError:
                        self._log(f"  [!] Вкладка {i + 1} не готова")
                await asyncio.sleep(1)

                # 6. ПАРСИНГ (улучшенная логика)
                self._log(f"[6/6] Запуск парсинга {len(phrases)} фраз...")
                start_time = time.time()

                async def parse_tab(
                    page: Page,
                    tab_phrases: List[str],
                    tab_index: int,
                ):
                    for phrase in tab_phrases:
                        if not self.is_running:
                            break
                            
                        # Проверяем, не обработана ли уже фраза
                        async with self.results_lock:
                            if phrase in self.results:
                                continue
                        
                        try:
                            input_selectors = [
                                "input[name='text']",
                                "input[placeholder]",
                                ".b-form-input__input",
                            ]
                            input_field = None
                            for selector in input_selectors:
                                try:
                                    locator = page.locator(selector)
                                    if await locator.count() > 0:
                                        input_field = locator.first
                                        break
                                except Exception:
                                    continue

                            if not input_field:
                                continue

                            await input_field.clear()
                            await input_field.fill(phrase)
                            
                            # УЛУЧШЕНИЕ: правильное ожидание навигации
                            try:
                                # Пробуем ждать навигацию
                                async with page.expect_navigation(wait_until="domcontentloaded", timeout=5000):
                                    await input_field.press("Enter")
                            except Exception:
                                # Если навигации не было - просто жмём Enter
                                await input_field.press("Enter")
                                await page.wait_for_load_state("networkidle", timeout=5000)

                            # УЛУЧШЕНИЕ: ждём конкретный XHR ответ
                            response_received = False
                            try:
                                await page.wait_for_response(
                                    lambda r: "/wordstat/api" in r.url and r.status == 200,
                                    timeout=3000
                                )
                                response_received = True
                            except Exception:
                                pass

                            # Если нет ответа - reload (редко)
                            if not response_received:
                                async with self.results_lock:
                                    if phrase not in self.results:
                                        self._log(f"  [WARN] [Tab {tab_index + 1}] нет ответа для {phrase}")
                                        await page.reload(wait_until="domcontentloaded", timeout=10000)
                                        await page.wait_for_load_state("networkidle", timeout=5000)

                            await asyncio.sleep(DELAY_BETWEEN_QUERIES)
                            
                        except Exception as exc:
                            self._log(f"  [ERROR] [Tab {tab_index + 1}] {phrase}: {exc}")
                            continue

                # Распределяем фразы по вкладкам
                chunks: List[List[str]] = []
                chunk_size = max(1, len(phrases) // len(working_pages))
                for i in range(len(working_pages)):
                    start_idx = i * chunk_size
                    if i == len(working_pages) - 1:
                        chunks.append(phrases[start_idx:])
                    else:
                        chunks.append(phrases[start_idx:start_idx + chunk_size])

                self._log("[OK] Распределение фраз по вкладкам:")
                for i, chunk in enumerate(chunks):
                    self._log(f"  * Вкладка {i + 1}: {len(chunk)} фраз")

                # Запуск парсинга параллельно
                parsing_tasks = []
                for i, (page, chunk) in enumerate(zip(working_pages, chunks)):
                    if chunk:
                        parsing_tasks.append(parse_tab(page, chunk, i))

                await asyncio.gather(*parsing_tasks)
                await asyncio.sleep(2)  # ждём последние ответы API

                # СТАТИСТИКА
                elapsed = time.time() - start_time
                self._log(f"[TIME] Время работы: {elapsed:.1f} секунд")
                self._log(f"[OK] Обработано: {len(self.results)}/{len(phrases)} фраз")
                if elapsed > 0:
                    speed = len(self.results)/(elapsed/60)
                    self._log(f"[SPEED] Скорость: {speed:.1f} фраз/минуту")

                return self.results

        except Exception as e:
            self._log(f"[ERROR] {str(e)}")
            raise
        finally:
            self.is_running = False
            if self.context:
                await self.context.close()

    async def stop(self):
        """Остановка парсинга."""
        self.is_running = False
        if self.context:
            await self.context.close()
        self._log("[STOP] Парсинг остановлен")