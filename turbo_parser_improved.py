#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
УЛУЧШЕННЫЙ ТУРБО ПАРСЕР - МНОГОПОТОЧНАЯ ВЕРСИЯ
Поддерживает одновременный запуск с разными профилями
Корректная работа с прокси через модуль proxy.py
"""

import argparse
import asyncio
import json
import pathlib
import time
import sys
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Any
import logging

LOG_DIR = pathlib.Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

from playwright.async_api import async_playwright, BrowserContext, Page, Response

# Добавляем путь к модулям проекта
PROJECT_PATH = pathlib.Path(__file__).resolve().parent
if str(PROJECT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_PATH))

# Импортируем модуль прокси
try:
    from keyset.utils.proxy import parse_proxy, proxy_to_playwright  # type: ignore
    PROXY_MODULE_AVAILABLE = True
except ImportError:
    try:
        from proxy import parse_proxy, proxy_to_playwright  # type: ignore
        PROXY_MODULE_AVAILABLE = True
    except ImportError:
        print("[WARNING] proxy module not available, using fallback parser")
        PROXY_MODULE_AVAILABLE = False

try:
    from keyset.services.multiparser_manager import (
        load_cookies_from_db_to_context,
        save_cookies_to_db,
        load_cookies_from_profile_to_context,
    )
except ImportError:  # pragma: no cover - fallback for scripts
    from services.multiparser_manager import (  # type: ignore
        load_cookies_from_db_to_context,
        save_cookies_to_db,
        load_cookies_from_profile_to_context,
    )

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_DIR / 'turbo_parser.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)

# НАСТРОЙКИ
TABS_COUNT = 10  # Количество вкладок
BATCH_SIZE = 50  # Размер батча фраз
DELAY_BETWEEN_TABS = 0.3  # Задержка между загрузкой вкладок (сек)
DELAY_BETWEEN_QUERIES = 0.5  # Задержка между запросами (сек)
RESPONSE_TIMEOUT = 3000  # Таймаут ожидания ответа API (мс)
RESPONSE_WAIT_TIMEOUT = 10.0  # Максимальное ожидание ответа Wordstat (сек)
WORDSTAT_LOAD_TIMEOUT_MS = 30000  # Таймаут загрузки Wordstat (мс)
WORDSTAT_MAX_ATTEMPTS = 3  # Количество попыток загрузки вкладки
WORDSTAT_RETRY_DELAY_BASE = 1.5  # Базовая задержка между повторными попытками (сек)


def log_parsing_debug(entry: Dict[str, Any]) -> None:
    """
    Сохраняет детальные логи парсинга в JSONL файл для отладки.

    Каждая запись содержит:
      - timestamp: ISO формат времени
      - account: имя аккаунта
      - tab: номер вкладки
      - phrase: фраза
      - status: статус этапа (started, input_found, enter_pressed, api_wait, success, timeout, error)
      - message: описание
      - ws: частотность (если получена)
      - elapsed: время выполнения этапа в секундах (если применимо)
      - error: текст ошибки (если есть)
    """
    debug_log_file = LOG_DIR / 'parsing_debug.jsonl'

    try:
        with open(debug_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        logging.error(f"Ошибка записи debug лога: {e}")


def parse_proxy_fallback(uri: str) -> Optional[dict]:
    """Запасной парсер прокси если модуль недоступен"""
    import re
    
    if not uri:
        return None
    
    # Пробуем разные форматы
    patterns = [
        # http://user:pass@host:port
        r'^(\w+)://(.+):(.+)@(.+):(\d+)$',
        # user:pass@host:port
        r'^(.+):(.+)@(.+):(\d+)$',
        # http://host:port
        r'^(\w+)://(.+):(\d+)$',
        # host:port
        r'^(.+):(\d+)$',
    ]
    
    uri = uri.strip()
    
    for pattern in patterns:
        match = re.match(pattern, uri)
        if match:
            groups = match.groups()
            if len(groups) == 5:  # С авторизацией
                scheme, username, password, host, port = groups
                return {
                    "server": f"{scheme}://{host}:{port}",
                    "username": username,
                    "password": password,
                }
            elif len(groups) == 4:  # user:pass@host:port без схемы
                username, password, host, port = groups
                return {
                    "server": f"http://{host}:{port}",
                    "username": username,
                    "password": password,
                }
            elif len(groups) == 3:  # Без авторизации со схемой
                scheme, host, port = groups
                return {"server": f"{scheme}://{host}:{port}"}
            elif len(groups) == 2:  # Без авторизации и схемы
                host, port = groups
                return {"server": f"http://{host}:{port}"}
    
    logging.warning(f"Failed to parse proxy: {uri}")
    return None


def get_proxy_config(proxy_uri: Optional[str]) -> Optional[dict]:
    """Получить конфигурацию прокси"""
    if not proxy_uri:
        return None
    
    if PROXY_MODULE_AVAILABLE:
        # Используем основной модуль
        config = proxy_to_playwright(proxy_uri)
        if config:
            logging.info(f"Proxy parsed: {config.get('server', 'unknown')}")
            return config
    
    # Запасной вариант
    config = parse_proxy_fallback(proxy_uri)
    if config:
        logging.info(f"Proxy parsed (fallback): {config.get('server', 'unknown')}")
    return config


def has_yandex_cookie(cookies: List[Dict[str, Any]]) -> bool:
    """Проверить, содержат ли куки домены Яндекса."""
    for cookie in cookies:
        domain = cookie.get("domain", "") or ""
        if "yandex" in domain:
            return True
    return False


async def verify_authorization(page: Page, account_name: str, logger: logging.Logger) -> bool:
    """Убедиться, что пользователь авторизован на Wordstat."""
    try:
        current_url = page.url or ""
        logger.info(f"[{account_name}] Проверка авторизации на URL: {current_url}")

        # Если редирект на страницу логина - точно не авторизован
        if "passport.yandex" in current_url or "/auth" in current_url:
            logger.error(f"[{account_name}] ❌ Требуется авторизация (редирект на {current_url})")
            return False

        # Если мы на wordstat.yandex.ru - пробуем разные проверки
        if "wordstat.yandex.ru" in current_url:
            logger.info(f"[{account_name}] Находимся на Wordstat, проверяю элементы авторизации...")

            # Проверка 1: Кнопка "Выход"
            try:
                await page.wait_for_selector('button:has-text("Выход")', timeout=2000)
                logger.info(f"[{account_name}] ✓ Авторизация подтверждена (найдена кнопка 'Выход')")
                return True
            except Exception:
                logger.debug(f"[{account_name}] Кнопка 'Выход' не найдена")

            # Проверка 2: Элемент профиля
            try:
                profile_elem = await page.query_selector('[data-testid="profile"]')
                if profile_elem:
                    logger.info(f"[{account_name}] ✓ Элемент профиля найден")
                    return True
            except Exception:
                pass

            # Проверка 3: Поле поиска Wordstat (если есть - значит авторизован)
            try:
                search_input = await page.query_selector('input[name="text"]')
                if search_input:
                    logger.info(f"[{account_name}] ✓ Поле поиска найдено, считаем авторизованным")
                    return True
            except Exception:
                pass

            # Проверка 4: Любой элемент с классом, содержащим 'user' или 'account'
            try:
                user_elem = await page.query_selector('[class*="user"], [class*="account"]')
                if user_elem:
                    logger.info(f"[{account_name}] ✓ Элемент пользователя найден")
                    return True
            except Exception:
                pass

            # Если на wordstat.yandex.ru и нет редиректа на логин - скорее всего авторизован
            logger.info(f"[{account_name}] ✓ На Wordstat без редиректа на логин - считаем авторизованным")
            return True

        logger.warning(f"[{account_name}] ⚠️ Неожиданный URL: {current_url}")
        return False

    except Exception as exc:
        logger.error(f"[{account_name}] ⚠️ Ошибка проверки авторизации: {exc}")
        return False


def log_manual_authorization_instructions(logger: logging.Logger, account_name: str, profile_path: pathlib.Path) -> None:
    """Подсказка пользователю по ручной авторизации."""
    logger.info(f"[{account_name}] Пожалуйста, авторизуйтесь вручную в отдельном окне Chrome:")
    logger.info(f"[{account_name}]   chrome --user-data-dir=\"{profile_path}\"")
    logger.info(f"[{account_name}] После авторизации закройте окно и запустите парсинг повторно.")


def load_phrases(path: pathlib.Path) -> List[str]:
    """Загрузка фраз из файла"""
    phrases: List[str] = []
    empty_lines: List[int] = []
    first_occurrence: Dict[str, int] = {}
    duplicates: Dict[str, List[int]] = {}
    
    with path.open("r", encoding="utf-8") as f:
        for line_number, raw_line in enumerate(f, start=1):
            phrase = raw_line.strip()
            if not phrase:
                empty_lines.append(line_number)
                continue
            
            # Убираем BOM если есть
            if phrase.startswith("\ufeff"):
                phrase = phrase.lstrip("\ufeff")
            
            phrases.append(phrase)
            
            if phrase in first_occurrence:
                occurrences = duplicates.setdefault(
                    phrase, [first_occurrence[phrase]]
                )
                occurrences.append(line_number)
            else:
                first_occurrence[phrase] = line_number
    
    if empty_lines:
        listed = ", ".join(map(str, empty_lines[:5]))
        suffix = "..." if len(empty_lines) > 5 else ""
        logging.warning(
            f"Empty lines found: {listed}{suffix} "
            f"(total {len(empty_lines)} — skipped)"
        )
    
    unique_phrases_count = len(set(phrases))
    duplicate_total = len(phrases) - unique_phrases_count
    if duplicate_total:
        logging.warning(
            f"Found {duplicate_total} duplicate phrases "
            f"(unique: {unique_phrases_count})"
        )
    
    return phrases


class TurboParser:
    """Класс для управления парсером"""
    
    def __init__(
        self,
        account_name: str,
        profile_path: pathlib.Path,
        phrases: List[str],
        headless: bool = False,
        proxy_uri: Optional[str] = None,
    ):
        self.account_name = account_name
        self.profile_path = profile_path.expanduser().resolve()
        self.phrases = phrases
        self.headless = headless
        self.proxy_uri = proxy_uri
        self.region_id: int = 225
        self.results: Dict[str, Any] = {}
        self.logger = logging.getLogger(f"TurboParser.{account_name}")

    def _inject_region_into_payload(self, payload: Any) -> None:
        """
        Рекурсивно проталкиваем выбранный region_id в известные ключи запроса Wordstat,
        чтобы API гарантированно работало по нужному GEO.
        """

        region_id = self.region_id

        def _apply(node: Any) -> None:
            if isinstance(node, dict):
                for key in ("lr", "region", "regionId", "geoId"):
                    if key in node and not isinstance(node[key], (dict, list)):
                        node[key] = region_id
                for key in ("regions", "regionIds", "geoIds"):
                    if key in node and isinstance(node[key], list):
                        node[key] = [region_id]
                for value in node.values():
                    _apply(value)
            elif isinstance(node, list):
                for item in node:
                    _apply(item)

        _apply(payload)
        if isinstance(payload, dict):
            payload.setdefault("regions", [region_id])
            payload.setdefault("regionId", region_id)
            payload.setdefault("lr", region_id)
        
    async def run(self) -> Dict[str, Any]:
        """Запуск парсера"""
        total_phrases = len(self.phrases)
        unique_phrases = len(set(self.phrases))
        duplicates_count = total_phrases - unique_phrases
        
        self.logger.info("=" * 70)
        self.logger.info(f"ТУРБО-ПАРСЕР: 10 ВКЛАДОК ({self.account_name})")
        self.logger.info(f"Профиль: {self.profile_path}")
        self.logger.info(f"Регион: {self.region_id}")
        self.logger.info("=" * 70)
        self.logger.info(f"Загружено фраз: {total_phrases}")
        self.logger.info(f"[Parser] НАЧАЛО парсинга. Фраз: {len(self.phrases)}")
        
        if duplicates_count:
            self.logger.warning(
                f"Уникальных фраз: {unique_phrases} "
                f"(дубликатов: {duplicates_count})"
            )
        
        # Парсим прокси
        proxy_config = get_proxy_config(self.proxy_uri)
        if proxy_config:
            self.logger.info(f"[PROXY] Используется: {proxy_config['server']}")
        
        results_lock = asyncio.Lock()
        
        async with async_playwright() as p:
            # 1. ЗАПУСК CHROME
            self.logger.info(f"[1/6] Запуск Chrome с профилем {self.account_name}...")
            
            try:
                context: BrowserContext = await p.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_path),
                    headless=self.headless,
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
            except Exception as e:
                self.logger.error(f"Failed to launch browser: {e}")
                raise

            async def _enforce_region(route, request):
                if request.method.upper() == "POST" and "/wordstat/api" in request.url:
                    post_data = request.post_data or ""
                    if post_data:
                        try:
                            payload = json.loads(post_data)
                        except Exception:
                            payload = None
                        if isinstance(payload, dict):
                            self._inject_region_into_payload(payload)
                            await route.continue_(post_data=json.dumps(payload, ensure_ascii=False))
                            return
                await route.continue_()

            await context.route("**/wordstat/api/**", _enforce_region)

            page = context.pages[0] if context.pages else await context.new_page()
            cookies = await context.cookies()
            self.logger.info(f"[{self.account_name}] Куки в профиле: {len(cookies)} шт")

            if not has_yandex_cookie(cookies):
                self.logger.warning(f"[{self.account_name}] Куки Яндекс не найдены — пробую загрузить из БД")
                loaded_from_db = await load_cookies_from_db_to_context(context, self.account_name, self.logger)
                if loaded_from_db:
                    cookies = await context.cookies()
                    if has_yandex_cookie(cookies):
                        self.logger.info(f"[{self.account_name}] ✓ Куки загружены из БД")

                if not has_yandex_cookie(cookies):
                    self.logger.warning(f"[{self.account_name}] Куки Яндекс не найдены в БД — пробую извлечь из профиля на диске")
                    loaded_from_profile = await load_cookies_from_profile_to_context(
                        context=context,
                        account_name=self.account_name,
                        profile_path=self.profile_path,
                        logger_obj=self.logger,
                        persist=True,
                    )
                    if loaded_from_profile:
                        cookies = await context.cookies()
                        if has_yandex_cookie(cookies):
                            self.logger.info(f"[{self.account_name}] ✓ Куки восстановлены из локального профиля")

                if not has_yandex_cookie(cookies):
                    self.logger.error(f"[{self.account_name}] ✗ Куки не найдены — может потребоваться ручная авторизация")
            else:
                self.logger.info(f"[{self.account_name}] ✓ Куки найдены, продолжаем")

            self.logger.info(f"[{self.account_name}] Переход на Wordstat...")
            try:
                await page.goto(
                    "https://wordstat.yandex.ru",
                    wait_until="domcontentloaded",
                    timeout=WORDSTAT_LOAD_TIMEOUT_MS,
                )
                await page.wait_for_load_state("networkidle", timeout=10000)
            except Exception as exc:
                self.logger.error(f"[{self.account_name}] ❌ Ошибка загрузки Wordstat: {exc}")
                await context.close()
                return {}

            # Проверка авторизации - если куки есть, делаем мягкую проверку
            auth_ok = await verify_authorization(page, self.account_name, self.logger)

            # Если проверка не прошла, но у нас есть куки Яндекса - даём второй шанс
            if not auth_ok and has_yandex_cookie(cookies):
                self.logger.warning(f"[{self.account_name}] ⚠️ Строгая проверка авторизации не прошла, но куки Яндекса есть")
                self.logger.info(f"[{self.account_name}] Пытаюсь продолжить парсинг с имеющимися куками...")
                auth_ok = True  # Даём шанс попробовать с куками

            if not auth_ok:
                self.logger.error(f"[{self.account_name}] ❌ Профиль не авторизован — ожидаю ручной вход")
                log_manual_authorization_instructions(self.logger, self.account_name, self.profile_path)
                try:
                    await page.wait_for_selector('button:has-text("Выход")', timeout=600_000)
                    self.logger.info(f"[{self.account_name}] ✓ Ручная авторизация выполнена, продолжаю")
                    await save_cookies_to_db(self.account_name, context, self.logger)
                except Exception:
                    self.logger.error(f"[{self.account_name}] ❌ Ручная авторизация не выполнена за отведённое время")
                    await context.close()
                    return {}

            pages: List[Page] = [page]
            self.logger.info(f"[2/6] Создание дополнительных вкладок...")
            self.logger.info("  [OK] Вкладка 1 готова")

            async def create_tab(index: int) -> Page:
                page_new = await context.new_page()
                self.logger.info(f"  [OK] Вкладка {index} создана")
                return page_new

            if TABS_COUNT > 1:
                additional_pages = await asyncio.gather(
                    *[create_tab(i) for i in range(2, TABS_COUNT + 1)]
                )
                pages.extend(additional_pages)
            self.logger.info(f"[OK] Создано {len(pages)} вкладок\n")
            
            # 3. ЗАГРУЗКА WORDSTAT
            self.logger.info(f"[3/6] Загрузка Wordstat во всех вкладках...")
            
            async def load_wordstat(page: Page, index: int) -> bool:
                url = f"https://wordstat.yandex.ru/?region={self.region_id}"
                for attempt in range(1, WORDSTAT_MAX_ATTEMPTS + 1):
                    try:
                        await page.goto(
                            url,
                            wait_until="domcontentloaded",
                            timeout=WORDSTAT_LOAD_TIMEOUT_MS,
                        )
                        if attempt > 1:
                            self.logger.info(
                                f"  [OK] Вкладка {index + 1}: Wordstat загружен "
                                f"с {attempt}-й попытки"
                            )
                        else:
                            self.logger.info(f"  [OK] Вкладка {index + 1}: Wordstat загружен")
                        return True
                    except Exception as e:
                        error_text = str(e).strip()
                        if "\n" in error_text:
                            error_text = error_text.splitlines()[0]
                        level = "WARNING" if attempt < WORDSTAT_MAX_ATTEMPTS else "ERROR"
                        self.logger.log(
                            logging.WARNING if level == "WARNING" else logging.ERROR,
                            f"  [{level}] Вкладка {index + 1}: не удалось загрузить Wordstat "
                            f"(попытка {attempt}/{WORDSTAT_MAX_ATTEMPTS}) — {error_text}"
                        )
                        if attempt < WORDSTAT_MAX_ATTEMPTS:
                            delay = WORDSTAT_RETRY_DELAY_BASE * attempt
                            await asyncio.sleep(delay)
                return False
            
            tasks = []
            for i, page in enumerate(pages):
                tasks.append(load_wordstat(page, i))
                await asyncio.sleep(DELAY_BETWEEN_TABS)
            
            results_load = await asyncio.gather(*tasks)
            working_pages = [p for i, p in enumerate(pages) if results_load[i]]
            
            self.logger.info(
                f"[OK] Wordstat загружен на {len(working_pages)}/{TABS_COUNT} вкладках\n"
            )
            if not working_pages:
                self.logger.error("Ни одна вкладка не загрузилась, парсер остановлен.")
                await context.close()
                return {}
            
            # 4. ОБРАБОТЧИК ОТВЕТОВ
            self.logger.info("[4/6] Настройка обработчиков API...")
            
            async def handle_response(response: Response):
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
                        async with results_lock:
                            self.results[phrase] = freq
                            self.logger.debug(f"  [API] '{phrase}' = {freq}")

                        # ЛОГ: API ответ получен
                        api_log_entry = {
                            'timestamp': datetime.now().isoformat(),
                            'account': self.account_name,
                            'tab': 'API',
                            'phrase': phrase,
                            'status': 'api_response_received',
                            'message': f'API ответ получен: {freq}',
                            'ws': freq,
                            'api_url': response.url,
                            'api_status': response.status
                        }
                        log_parsing_debug(api_log_entry)

                except Exception as e:
                    self.logger.error(f"Error handling response: {e}")
            
            for page in working_pages:
                page.on("response", handle_response)
            
            # 5. ПОДГОТОВКА ВКЛАДОК
            self.logger.info(f"[5/6] Подготовка вкладок к парсингу...")
            for i, page in enumerate(working_pages):
                try:
                    await page.wait_for_selector(
                        "input[name='text'], input[placeholder]",
                        timeout=5000,
                    )
                    self.logger.info(f"  [OK] Вкладка {i + 1} готова")
                except TimeoutError:
                    self.logger.warning(f"  [!] Вкладка {i + 1} не готова")
            await asyncio.sleep(1)
            
            # 6. ПАРСИНГ
            self.logger.info(f"[6/6] Запуск парсинга {len(self.phrases)} фраз...\n")
            start_time = time.time()
            stats = {"processed": 0, "timeouts": 0, "errors": 0}
            stats_lock = asyncio.Lock()
            
            async def parse_tab(
                page: Page,
                tab_phrases: List[str],
                tab_index: int,
            ):
                for index, phrase in enumerate(tab_phrases, start=1):
                    if phrase in self.results:
                        continue

                    # Инициализируем debug лог для фразы
                    log_entry = {
                        'timestamp': datetime.now().isoformat(),
                        'account': self.account_name,
                        'tab': tab_index + 1,
                        'phrase': phrase,
                        'status': 'started',
                        'message': f'[TAB {tab_index + 1}] Начало парсинга: "{phrase}"'
                    }
                    log_parsing_debug(log_entry)

                    while True:
                        try:
                            input_selectors = [
                                "input[name='text']",
                                "input[placeholder]",
                                ".b-form-input__input",
                            ]
                            self.logger.info(
                                f"  [TAB {tab_index + 1}] ▶️ [{index}/{len(tab_phrases)}] '{phrase}'"
                            )
                            self.logger.debug(
                                f"  [TAB {tab_index + 1}] Ищу поле ввода среди {len(input_selectors)} селекторов"
                            )

                            # ЛОГ: Поиск поля ввода
                            t_input_start = time.time()
                            input_field = None
                            for selector in input_selectors:
                                try:
                                    locator = page.locator(selector)
                                    if await locator.count() > 0:
                                        input_field = locator.first
                                        elapsed_input = time.time() - t_input_start
                                        log_entry.update({
                                            'timestamp': datetime.now().isoformat(),
                                            'status': 'input_found',
                                            'message': f'Поле ввода найдено: {selector}',
                                            'selector': selector,
                                            'elapsed': round(elapsed_input, 3)
                                        })
                                        log_parsing_debug(log_entry)
                                        break
                                except Exception:
                                    continue

                            if not input_field:
                                self.logger.warning(
                                    f"  [TAB {tab_index + 1}] ⚠️ Поле ввода не найдено для '{phrase}'"
                                )
                                # ЛОГ: Поле ввода не найдено
                                log_entry.update({
                                    'timestamp': datetime.now().isoformat(),
                                    'status': 'error_no_input',
                                    'message': 'Поле ввода НЕ НАЙДЕНО',
                                    'ws': 0
                                })
                                log_parsing_debug(log_entry)
                                async with stats_lock:
                                    stats["errors"] += 1
                                async with results_lock:
                                    self.results.setdefault(phrase, 0)
                                break
                            
                            self.logger.debug(
                                f"  [TAB {tab_index + 1}] ✓ Поле ввода найдено"
                            )

                            # ЛОГ: Ввод фразы
                            t_type_start = time.time()
                            await input_field.clear()
                            self.logger.debug(
                                f"  [TAB {tab_index + 1}] Поле очищено, ввожу фразу"
                            )
                            await input_field.fill(phrase)
                            elapsed_type = time.time() - t_type_start
                            log_entry.update({
                                'timestamp': datetime.now().isoformat(),
                                'status': 'phrase_typed',
                                'message': 'Фраза введена в поле',
                                'elapsed': round(elapsed_type, 3)
                            })
                            log_parsing_debug(log_entry)

                            # ЛОГ: Нажатие Enter и отправка запроса
                            self.logger.debug(
                                f"  [TAB {tab_index + 1}] Отправляю запрос на Wordstat"
                            )
                            t_enter_start = time.time()
                            await input_field.press("Enter")
                            elapsed_enter = time.time() - t_enter_start
                            log_entry.update({
                                'timestamp': datetime.now().isoformat(),
                                'status': 'enter_pressed',
                                'message': f'Enter нажат, запрос отправлен',
                                'elapsed': round(elapsed_enter, 3)
                            })
                            log_parsing_debug(log_entry)

                            # ЛОГ: Ожидание API ответа
                            timeout = max(RESPONSE_WAIT_TIMEOUT, RESPONSE_TIMEOUT / 1000.0)
                            t_api_start = time.time()
                            response_received = False

                            log_entry.update({
                                'timestamp': datetime.now().isoformat(),
                                'status': 'api_waiting',
                                'message': f'Ожидание API ответа (timeout={timeout:.1f}s)'
                            })
                            log_parsing_debug(log_entry)

                            while time.time() - t_api_start < timeout:
                                async with results_lock:
                                    if phrase in self.results:
                                        response_received = True
                                        break
                                await asyncio.sleep(0.1)

                            elapsed_api = time.time() - t_api_start

                            if response_received:
                                value = self.results.get(phrase)
                                self.logger.info(
                                    f"  [TAB {tab_index + 1}] ✓ '{phrase}' = {value}"
                                )

                                # ЛОГ: Успешное получение результата
                                log_entry.update({
                                    'timestamp': datetime.now().isoformat(),
                                    'status': 'success',
                                    'message': f'Частотность получена: {value}',
                                    'ws': value,
                                    'elapsed': round(elapsed_api, 3),
                                    'api_received': True
                                })
                                log_parsing_debug(log_entry)

                                async with stats_lock:
                                    stats["processed"] += 1
                            else:
                                self.logger.warning(
                                    f"  [TAB {tab_index + 1}] ⏱ '{phrase}' — timeout"
                                )

                                # ЛОГ: Таймаут API
                                log_entry.update({
                                    'timestamp': datetime.now().isoformat(),
                                    'status': 'api_timeout',
                                    'message': f'API таймаут после {elapsed_api:.2f}s ожидания',
                                    'ws': 0,
                                    'elapsed': round(elapsed_api, 3),
                                    'api_received': False
                                })
                                log_parsing_debug(log_entry)

                                async with results_lock:
                                    self.results[phrase] = 0
                                self.logger.debug(
                                    f"  [TAB {tab_index + 1}] размещено значение 0 для '{phrase}' после {timeout:.1f}с ожидания"
                                )
                                async with stats_lock:
                                    stats["processed"] += 1
                                    stats["timeouts"] += 1
                            
                            async with stats_lock:
                                processed_so_far = stats["processed"]
                                timeouts_so_far = stats["timeouts"]
                                errors_so_far = stats["errors"]
                            self.logger.debug(
                                f"  [TAB {tab_index + 1}] ✓ Завершена обработка '{phrase}' "
                                f"(обработано: {processed_so_far}, таймаутов: {timeouts_so_far}, ошибок: {errors_so_far}, всего результатов: {len(self.results)})"
                            )
                            break

                        except Exception as e:
                            self.logger.error(
                                f"  [TAB {tab_index + 1}] ❌ Ошибка обработке '{phrase}': {type(e).__name__}: {e}"
                            )

                            # ЛОГ: Критическая ошибка
                            log_entry.update({
                                'timestamp': datetime.now().isoformat(),
                                'status': 'critical_error',
                                'message': f'КРИТИЧЕСКАЯ ОШИБКА: {type(e).__name__}',
                                'ws': 0,
                                'error': str(e)[:200]
                            })
                            log_parsing_debug(log_entry)

                            async with stats_lock:
                                stats["errors"] += 1
                            async with results_lock:
                                self.results[phrase] = 0
                            break
                        
                        await asyncio.sleep(DELAY_BETWEEN_QUERIES)
            
            # Распределяем фразы по вкладкам
            tab_phrases_list = []
            for i in range(len(working_pages)):
                start_idx = i * len(self.phrases) // len(working_pages)
                end_idx = (i + 1) * len(self.phrases) // len(working_pages)
                tab_phrases_list.append(self.phrases[start_idx:end_idx])
            
            # Запускаем парсинг на всех вкладках параллельно
            parse_tasks = [
                parse_tab(page, phrases, i)
                for i, (page, phrases) in enumerate(zip(working_pages, tab_phrases_list))
            ]
            await asyncio.gather(*parse_tasks)

            await save_cookies_to_db(self.account_name, context, self.logger)
            
            # Закрываем браузер
            await context.close()
            
            # Статистика
            elapsed = time.time() - start_time
            parsed_count = len(self.results)
            speed = parsed_count / elapsed if elapsed > 0 else 0

            async with stats_lock:
                processed_total = stats["processed"]
                timeouts_total = stats["timeouts"]
                errors_total = stats["errors"]
            self.logger.info("[Parser] ═════════════════════════════════════════════════════")
            self.logger.info(f"[Parser] Фраз обработано: {processed_total}")
            self.logger.info(f"[Parser] Таймаутов: {timeouts_total}")
            self.logger.info(f"[Parser] Ошибок: {errors_total}")
            self.logger.info(f"[Parser] Результатов найдено: {len(self.results)}")
            self.logger.info("[Parser] ═════════════════════════════════════════════════════")
            
            self.logger.info("=" * 70)
            self.logger.info(f"ПАРСИНГ ЗАВЕРШЕН ({self.account_name})")
            self.logger.info(f"Обработано фраз: {parsed_count}/{len(self.phrases)}")
            self.logger.info(f"Время: {elapsed:.2f} сек")
            self.logger.info(f"Скорость: {speed:.1f} фраз/сек")
            self.logger.info("=" * 70)
            
            return self.results


async def turbo_parser_10tabs(
    account_name: str,
    profile_path: pathlib.Path,
    phrases: Iterable[str],
    *,
    headless: bool = False,
    proxy_uri: Optional[str] = None,
    region_id: int = 225,
) -> Dict[str, Any]:
    """
    Главная функция парсера для обратной совместимости
    
    Args:
        account_name: имя аккаунта
        profile_path: путь к профилю Chrome
        phrases: коллекция фраз
        headless: флаг headless-режима
        proxy_uri: URI прокси
        
    Returns:
        словарь «фраза → частотность»
    """
    parser = TurboParser(
        account_name=account_name,
        profile_path=profile_path,
        phrases=list(phrases),
        headless=headless,
        proxy_uri=proxy_uri
    )
    parser.region_id = region_id
    return await parser.run()


def main():
    """Функция для тестирования"""
    parser = argparse.ArgumentParser(description="Turbo Parser 10 tabs")
    parser.add_argument("account_name", help="Account name")
    parser.add_argument("profile_path", help="Chrome profile path")
    parser.add_argument("phrases_file", help="File with phrases")
    parser.add_argument("--proxy", help="Proxy URI", default=None)
    parser.add_argument("--region", type=int, default=225, help="Wordstat region id (lr)")
    parser.add_argument("--headless", action="store_true", help="Run in headless mode")
    
    args = parser.parse_args()
    
    # Загружаем фразы
    phrases_path = pathlib.Path(args.phrases_file)
    if not phrases_path.exists():
        print(f"File not found: {phrases_path}")
        return
    
    phrases = load_phrases(phrases_path)
    
    # Создаем парсер
    parser = TurboParser(
        account_name=args.account_name,
        profile_path=pathlib.Path(args.profile_path),
        phrases=phrases,
        headless=args.headless,
        proxy_uri=args.proxy
    )
    parser.region_id = args.region
    
    # Запускаем
    results = asyncio.run(parser.run())
    
    # Сохраняем результаты
    output_file = pathlib.Path(f"results_{args.account_name}_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    
    print(f"Results saved to {output_file}")


if __name__ == "__main__":
    main()
