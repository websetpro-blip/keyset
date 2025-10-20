"""
РАБОЧИЙ ТУРБО ПАРСЕР - 526.3 фраз/мин
Адаптирован из turbo_parser_10tabs.py для интеграции с KeySet GUI
"""

import asyncio
import json
import time
import re
from playwright.async_api import async_playwright
from ..utils.text_fix import WORDSTAT_FETCH_NORMALIZER_SCRIPT, fix_mojibake

# НАСТРОЙКИ
TABS_COUNT = 10
DELAY_BETWEEN_TABS = 0.3
DELAY_BETWEEN_QUERIES = 0.5

_WORDSTAT_ENCODINGS = ("utf-8", "windows-1251", "cp1251", "latin-1")


async def _parse_wordstat_json(response):
    try:
        raw = await response.body()
    except Exception:
        raw = b""

    content_type = ""
    try:
        content_type = response.headers.get("content-type", "")
    except Exception:
        content_type = ""

    encodings = []
    match = re.search(r"charset=([^;]+)", content_type or "", flags=re.IGNORECASE)
    if match:
        enc = match.group(1).strip().lower()
        if enc:
            encodings.append(enc)
    for enc in _WORDSTAT_ENCODINGS:
        if enc not in encodings:
            encodings.append(enc)

    for encoding in encodings:
        try:
            text = raw.decode(encoding, errors="strict")
            return json.loads(text)
        except Exception:
            continue
    return None


def _normalize_wordstat_payload(data):
    table = data.get("table")
    if not isinstance(table, dict):
        return
    table_data = table.get("tableData")
    if not isinstance(table_data, dict):
        return

    def _norm(entries):
        normalized = []
        for item in entries or []:
            phrase = ""
            count = 0
            if isinstance(item, dict):
                phrase = (
                    item.get("text")
                    or item.get("phrase")
                    or item.get("key")
                    or item.get("title")
                    or ""
                )
                count = item.get("value") or item.get("count") or item.get("freq") or 0
            elif isinstance(item, (list, tuple)) and item:
                phrase = str(item[0] or "")
                count = item[1] if len(item) > 1 else 0
            elif isinstance(item, str):
                phrase = item
                count = 0
            try:
                value = int(str(count).replace(" ", ""))
            except Exception:
                value = 0
            phrase = phrase.strip()
            if phrase:
                normalized.append({"phrase": phrase, "count": value})
        return normalized

    if not table.get("items"):
        table["items"] = _norm(table_data.get("popular"))
    if not table.get("related"):
        table["related"] = _norm(table_data.get("associations") or table_data.get("similar"))


def _extract_phrase_from_request(response):
    try:
        payload = response.request.post_data
    except Exception:
        payload = None
    if not payload:
        return None
    try:
        blob = json.loads(payload)
        phrase = blob.get("searchValue") or blob.get("query") or ""
        phrase = phrase.strip() if isinstance(phrase, str) else ""
        return phrase or None
    except Exception:
        return None


async def parse_wordstat(phrases, log_callback=None):
    """
    РАБОЧИЙ парсер Wordstat - 526.3 фраз/мин
    
    Args:
        phrases: список фраз для парсинга
        log_callback: функция для логирования (опционально)
    
    Returns:
        dict: {фраза: частота}
    """
    def log(msg):
        if log_callback:
            log_callback(msg)
        else:
            print(msg)
    
    results = {}
    results_lock = asyncio.Lock()
    
    async with async_playwright() as p:
        # 1. ЗАПУСК CHROME
        log("[1/6] Запуск Chrome с профилем wordstat_main...")
        context = await p.chromium.launch_persistent_context(
            user_data_dir="C:\\AI\\yandex\\.profiles\\wordstat_main",
            headless=False,
            channel="chrome",
            args=[
                '--start-maximized',
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process',
                '--disable-site-isolation-trials'
            ],
            viewport=None,
            locale='ru-RU'
        )
        await context.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
        for existing in context.pages:
            await existing.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            try:
                await existing.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            except Exception:
                pass
        
        # 2. СОЗДАНИЕ ВКЛАДОК
        log(f"[2/6] Создание {TABS_COUNT} вкладок...")
        
        async def create_tab(index):
            page = await context.new_page()
            try:
                await page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            except Exception:
                pass
            log(f"  [OK] Вкладка {index+1} создана")
            return page
        
        pages = await asyncio.gather(*[create_tab(i) for i in range(TABS_COUNT)])
        log(f"[OK] создано {len(pages)} вкладок")
        
        # 3. ЗАГРУЗКА WORDSTAT
        log(f"[3/6] Загрузка Wordstat во всех вкладках...")
        
        async def load_wordstat(page, index):
            try:
                await page.goto(
                    "https://wordstat.yandex.ru/?region=225",
                    wait_until="domcontentloaded",
                    timeout=15000
                )
                log(f"  [OK] Вкладка {index+1}: Wordstat загружен")
                return True
            except Exception as e:
                log(f"  [ERROR] Вкладка {index+1}: {str(e)[:30]}...")
                return False
        
        tasks = []
        for i, page in enumerate(pages):
            tasks.append(load_wordstat(page, i))
            await asyncio.sleep(DELAY_BETWEEN_TABS)
        
        results_load = await asyncio.gather(*tasks)
        working_pages = [p for i, p in enumerate(pages) if results_load[i]]
        
        log(f"[OK] Wordstat загружен на {len(working_pages)}/{TABS_COUNT} вкладках")
        
        if len(working_pages) == 0:
            log("[ERROR] Ни одна вкладка не загрузилась!")
            return {}
        
        # 4. УСТАНОВКА ОБРАБОТЧИКОВ API
        log(f"[4/6] Установка обработчиков API...")
        
        async def handle_response(response):
            if "/wordstat/api" not in response.url or response.status != 200:
                return
            data = await _parse_wordstat_json(response)
            if not data:
                return
            _normalize_wordstat_payload(data)

            phrase = fix_mojibake(_extract_phrase_from_request(response) or "")
            items = (data.get("table") or {}).get("items") or []
            if not phrase and items:
                phrase = fix_mojibake(items[0].get("phrase") or "").strip()
            if not phrase:
                return

            freq = data.get("totalValue")
            if freq is None and items:
                freq = items[0].get("count") or items[0].get("value")

            try:
                frequency = int(str(freq).replace(" ", "")) if freq is not None else None
            except Exception:
                frequency = None

            if frequency is None:
                return

            async with results_lock:
                results[phrase] = frequency
            log(f"    [+] {phrase}: {frequency:,}")
        
        for page in working_pages:
            page.on("response", handle_response)
        
        log("[OK]")
        
        # 5. ПОДГОТОВКА ВКЛАДОК
        log(f"[5/6] Подготовка вкладок к парсингу...")
        for i, page in enumerate(working_pages):
            try:
                await page.wait_for_selector(
                    "input[name='text'], input[placeholder]",
                    timeout=5000
                )
                log(f"  [OK] Вкладка {i+1} готова")
            except:
                log(f"  [!] Вкладка {i+1} не готова")
        await asyncio.sleep(1)
        
        # 6. ПАРСИНГ
        log(f"[6/6] Запуск парсинга {len(phrases)} фраз...")
        start_time = time.time()
        
        async def parse_tab(page, tab_phrases, tab_index):
            for phrase in tab_phrases:
                if phrase in results:
                    continue
                
                try:
                    input_selectors = [
                        "input[name='text']",
                        "input[placeholder]",
                        ".b-form-input__input"
                    ]
                    
                    input_field = None
                    for selector in input_selectors:
                        try:
                            if await page.locator(selector).count() > 0:
                                input_field = page.locator(selector).first
                                break
                        except:
                            continue
                    
                    if input_field:
                        await input_field.clear()
                        await input_field.fill(phrase)
                        await input_field.press("Enter")
                        captured = False
                        for _ in range(30):
                            if phrase in results:
                                captured = True
                                break
                            await asyncio.sleep(DELAY_BETWEEN_QUERIES)
                        if not captured:
                            log(f"  [WARN] [Tab {tab_index+1}] нет ответа для {phrase}")
              
                except Exception as e:
                    log(f"  [ERROR] [Tab {tab_index+1}] {phrase}: {e}")
                    return
            
            return tab_index
        
        # Распределение фраз по вкладкам
        chunks = []
        chunk_size = len(phrases) // len(working_pages)
        
        for i in range(len(working_pages)):
            start_idx = i * chunk_size
            if i == len(working_pages) - 1:
                chunks.append(phrases[start_idx:])
            else:
                chunks.append(phrases[start_idx:start_idx + chunk_size])
        
        log("[OK] Распределение фраз по вкладкам:")
        for i, chunk in enumerate(chunks):
            log(f"  * Вкладка {i+1}: {len(chunk)} фраз")
        
        # Запуск парсинга параллельно
        tasks = []
        for i, (page, chunk) in enumerate(zip(working_pages, chunks)):
            if chunk:
                task = parse_tab(page, chunk, i)
                tasks.append(task)
        
        await asyncio.gather(*tasks)
        await asyncio.sleep(2)
        
        # СТАТИСТИКА
        elapsed = time.time() - start_time
        log(f"[TIME] Время работы: {elapsed:.1f} секунд")
        log(f"[OK] Обработано: {len(results)}/{len(phrases)} фраз")
        speed = len(results)/(elapsed/60) if elapsed > 0 else 0
        log(f"[SPEED] Скорость: {speed:.1f} фраз/минуту")
        
        return results
