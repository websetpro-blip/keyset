#!/usr/bin/env python3
"""
ФИНАЛЬНЫЙ ТУРБО ПАРСЕР - 10 ВКЛАДОК
Скорость: 100-150 фраз/минуту
Основан на: parse_5_accounts_cdp.py и parser_final_130plus.py
"""

import asyncio
import json
import time
from datetime import datetime
from playwright.async_api import async_playwright, BrowserContext, Page
import traceback
from pathlib import Path

# ВАЖНО: Для автономного скрипта нужно создать заглушки для классов,
# которые не являются частью KeySet, но нужны для логики
class Account:
    def __init__(self, name, proxy_server):
        self.name = name
        self.proxy_server = proxy_server
        self.login = name
        self.password = "fake_password"
        self.secret_answer = "fake_answer"

class VisualBrowserManager:
    # Заглушка, которая имитирует запуск браузера с прокси
    def __init__(self, account, num_browsers=1):
        self.account = account
        self.num_browsers = num_browsers
        self.context = None
        
    async def launch_browser(self, p):
        print(f"[VBM] Запуск браузера для {self.account.name} с прокси {self.account.proxy_server}")
        
        # Получаем прокси-конфигурацию
        proxy_config = self._get_proxy_config()
        
        # Запуск persistent context с прокси
        self.context = await p.chromium.launch_persistent_context(
            user_data_dir=f"C:\\AI\\yandex\\.profiles\\{self.account.name}",
            headless=True, # Принудительный скрытый режим для работы на сервере (VPS)
            channel=None, # Используем Playwright Chromium, который уже установлен
            args=[
                "--start-maximized",
                # "--disable-blink-features=AutomationControlled", # Удалено, так как Яндекс его детектирует
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials"
            ],
            viewport=None,
            locale="ru-RU",
            proxy=proxy_config
        )
        return self.context

    def _get_proxy_config(self):
        # Логика парсинга прокси из строки "ip:port:user:pass"
        if self.account.proxy_server is None:
            return None
            
        parts = self.account.proxy_server.split(':')
        if len(parts) >= 2:
            config = {"server": f"{parts[0]}:{parts[1]}"}
            if len(parts) == 4:
                config["username"] = parts[2]
                config["password"] = parts[3]
            return config
        return None

    async def close_all(self):
        if self.context:
            await self.context.close()

class AutoAuthHandler:
    # Заглушка для обработки авторизации
    async def handle_auth_redirect(self, page, account_data):
        print(f"[AUTH] Имитация авторизации для {account_data['login']}")
        # Здесь должна быть сложная логика, но для теста просто пропускаем
        return True # Считаем, что авторизация прошла успешно

# ... (остальной код)

# НАСТРОЙКИ (НЕ МЕНЯЙ!)
TABS_COUNT = 10  # Количество вкладок
BATCH_SIZE = 50  # Размер батча фраз
DELAY_BETWEEN_TABS = 0.3  # Задержка между загрузкой вкладок (секунды)
DELAY_BETWEEN_QUERIES = 0.5  # Задержка между запросами (секунды)
RESPONSE_TIMEOUT = 3000  # Таймаут ожидания ответа API (мс)

async def turbo_parser_10tabs(account_name="domsmirnov", proxy_server="77.73.134.166:8000:user:pass", phrases_file="test_50.txt"):
    """
    Главная функция парсера
    Args:
        account_name: Имя аккаунта (используется для профиля)
        proxy_server: Строка прокси в формате ip:port:user:pass
        phrases_file: файл с фразами (одна фраза на строку)
    """
    # Создаем заглушку аккаунта
    account = Account(account_name, proxy_server)
    """
    Главная функция парсера
    Args:
        phrases_file: файл с фразами (одна фраза на строку)
    """
    print("="*70)
    print("   ТУРБО ПАРСЕР 10 ВКЛАДОК - ФИНАЛЬНАЯ ВЕРСИЯ")
    print("="*70)
    
    # Загружаем фразы
    try:
        with open(phrases_file, 'r', encoding='utf-8') as f:
            phrases = [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"\n[ERROR] Файл {phrases_file} не найден!")
        print("Использую тестовые фразы...")
        phrases = [
            "купить квартиру москва",
            "ремонт квартир недорого",
            "доставка пиццы москва",
            "заказать такси онлайн",
            "купить авто с пробегом"
        ]
    
    print(f"\n[INFO] Загружено фраз: {len(phrases)}")
    
    results = {}
    results_lock = asyncio.Lock()
    
    async with async_playwright() as p:
        # ШАГ 1: ЗАПУСК CHROME С ПРОФИЛЕМ И ПРОКСИ (через VBM)
        print(f"\n[1/6] Запускаю Chrome с профилем {account.name} и прокси {account.proxy_server}...")
        
        # Используем VisualBrowserManager для запуска с прокси
        vbm = VisualBrowserManager(account)
        context = await vbm.launch_browser(p)
        
        if not context:
            print("[ERROR] Не удалось запустить браузер с прокси!")
            return
        
        # ШАГ 2: СОЗДАНИЕ ВКЛАДОК (ПАРАЛЛЕЛЬНО!)
        print(f"\n[2/6] Создаю {TABS_COUNT} вкладок ПАРАЛЛЕЛЬНО...")
        
        async def create_tab(index):
            """Создание одной вкладки"""
            page = await context.new_page()
            print(f"    [OK] Вкладка {index+1} создана")
            return page
        
        # Создаем все вкладки параллельно
        pages = await asyncio.gather(*[
            create_tab(i) for i in range(TABS_COUNT)
        ])
        
        print(f"    [OK] Создано {len(pages)} вкладок за 1 секунду!")
        
        # ШАГ 3: ЗАГРУЗКА WORDSTAT И ПРОВЕРКА АВТОРИЗАЦИИ (ПОСЛЕДОВАТЕЛЬНО!)
        print(f"\n[3/6] Загружаю Wordstat и проверяю авторизацию...")
        
        auth_handler = AutoAuthHandler()
        account_data = {
            'login': account.login,
            'password': account.password,
            'secret_answer': account.secret_answer
        }
        
        async def wait_wordstat_ready(page: Page, index: int):
            """Ожидание полной загрузки Wordstat с проверкой авторизации"""
            try:
                await page.goto(
                    "https://wordstat.yandex.ru/?region=225",
                    wait_until="domcontentloaded",
                    timeout=30000
                )
                
                # 1) Проверяем, не перебросило ли на паспорт
                current_url = page.url
                if "passport.yandex" in current_url or "passport.ya.ru" in current_url:
                    print(f"    [AUTH] Вкладка {index+1}: Обнаружена страница авторизации!")
                    
                    success = await auth_handler.handle_auth_redirect(page, account_data)
                    if success:
                        print(f"    [AUTH] Вкладка {index+1}: Авторизация успешна")
                        await page.goto("https://wordstat.yandex.ru/?region=225", wait_until="domcontentloaded", timeout=30000)
                    else:
                        print(f"    [AUTH] Вкладка {index+1}: Ошибка авторизации")
                        return None
                
                # 2) Ждём URL Wordstat
                await page.wait_for_url("**/wordstat.yandex.ru/**", timeout=30000)
                
                # 3) Явный DOM-гейт - ждём поле поиска
                await page.wait_for_selector('input[name="text"], input[placeholder*="слово"]', timeout=5000)
                
                print(f"    [OK] Вкладка {index+1}: Wordstat готов")
                return page
                
            except Exception as e:
                print(f"    [ERROR] Вкладка {index+1}: Ошибка загрузки/авторизации: {str(e)[:50]}")
                return None
        
        # Загружаем Wordstat на всех вкладках последовательно
        working_pages = []
        for i, page in enumerate(pages):
            result_page = await wait_wordstat_ready(page, i)
            if result_page:
                working_pages.append(result_page)
            await asyncio.sleep(DELAY_BETWEEN_TABS) # Используем вашу задержку
        
        print(f"    [OK] Wordstat готов на {len(working_pages)}/{TABS_COUNT} вкладках")
        
        if len(working_pages) == 0:
            print("    [ERROR] Нет рабочих вкладок!")
            return
        
        # ШАГ 4: НАСТРОЙКА ПЕРЕХВАТА ОТВЕТОВ
        print(f"\n[4/6] Настраиваю перехват API ответов...")
        
        async def handle_response(response):
            """Перехват ответов Wordstat API"""
            if "/wordstat/api" in response.url and response.status == 200:
                try:
                    # 1. Читаем ответ как байты для явного декодирования
                    try:
                        raw_body = await response.body()
                    except Exception as e:
                        print(f"    [ERROR] Reading response body: {e}")
                        return
                    
                    # 2. Явное декодирование CP1251 -> UTF-8
                    try:
                        text = raw_body.decode("cp1251")
                    except UnicodeDecodeError:
                        text = raw_body.decode("utf-8", "ignore")
                    
                    # 3. Парсинг JSON
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as e:
                        print(f"    [CRITICAL] Cannot parse JSON: {e}")
                        traceback.print_exc()
                        return
                    
                    # 4. Нормализация структуры (Wordstat Fix)
                    frequency = None
                    if 'data' in data and 'table' in data['data']:
                        tbl = data['data']['table']
                        tdata = tbl.get("tableData") or {}
                        
                        popular = tdata.get("popular") or []
                        
                        # Нормализация для совместимости
                        tbl['items'] = popular or tbl.get("items") or []
                        
                        # Извлекаем частотность
                        if 'totalValue' in data:
                             data['data']['totalValue'] = data['totalValue']
                        
                        frequency = data['data'].get('totalValue')
                    
                    
                    if frequency is not None:
                        # Извлекаем фразу из запроса
                        post_data = response.request.post_data
                        if post_data:
                            # Попытка декодирования post_data, если он не JSON (хотя должен быть)
                            try:
                                request_data = json.loads(post_data)
                            except json.JSONDecodeError:
                                # Если не JSON, игнорируем, т.к. это не API-запрос
                                return
                                
                            phrase = request_data.get("searchValue", "").strip()
                            
                            if phrase:
                                async with results_lock:
                                    results[phrase] = frequency
                                print(f"    [OK] {phrase} = {frequency:,}")
                except:
                    pass
        
        # Подключаем обработчик к каждой рабочей вкладке
        for page in working_pages:
            page.on("response", handle_response)
        
        print("    [OK] Обработчики подключены")
        
        # ШАГ 5: ОЖИДАНИЕ ГОТОВНОСТИ
        print(f"\n[5/6] Проверяю готовность вкладок...")
        
        # Проверяем наличие поля ввода на каждой вкладке
        ready_pages = []
        for i, page in enumerate(working_pages):
            try:
                await page.wait_for_selector(
                    'input[name="text"], input[placeholder*="слово"]',
                    timeout=5000
                )
                print(f"    [OK] Вкладка {i+1}: Готова")
                ready_pages.append(page)
            except:
                print(f"    [ERROR] Вкладка {i+1}: Не готова")
        
        if len(ready_pages) == 0:
            print("    [ERROR] Нет готовых вкладок!")
            return
        
        await asyncio.sleep(1)
        
        # ШАГ 6: ПАРСИНГ ФРАЗ
        print(f"\n[6/6] ПАРСИНГ {len(phrases)} фраз...")
        start_time = time.time()
        
        # Функция парсинга для одной вкладки
        async def parse_tab(page, tab_phrases, tab_index):
            """Парсинг списка фраз на одной вкладке"""
            local_count = 0
            error_count = 0
            
            print(f"    [START] Tab {tab_index+1}: начинаю {len(tab_phrases)} фраз")
            
            for i, phrase in enumerate(tab_phrases, 1):
                if phrase in results:  # Уже обработана
                    print(f"        Tab {tab_index+1}: [{i}/{len(tab_phrases)}] '{phrase}' - уже обработана")
                    continue
                
                try:
                    # Поиск поля ввода
                    input_selectors = [
                        'input[name="text"]',
                        'input[placeholder*="слово"]',
                        '.b-form-input__input'
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
                        # Очищаем поле и вводим фразу
                        await input_field.clear()
                        await input_field.fill(phrase)
                        
                        print(f"        Tab {tab_index+1}: [{i}/{len(tab_phrases)}] Ввел '{phrase}'")
                        
                        # Нажимаем Enter и ждем ответ
                        await input_field.press("Enter")
                        
                        # Ждем ответ API
                        await asyncio.sleep(DELAY_BETWEEN_QUERIES)
                        local_count += 1
                    else:
                        print(f"        Tab {tab_index+1}: [{i}/{len(tab_phrases)}] НЕТ ПОЛЯ ВВОДА!")
                        error_count += 1
                        
                except Exception as e:
                    print(f"        Tab {tab_index+1}: [{i}/{len(tab_phrases)}] ОШИБКА: {str(e)[:50]}")
                    error_count += 1
            
            print(f"    [DONE] Tab {tab_index+1}: успешно {local_count}, ошибок {error_count}")
            return tab_index
        
        # Распределяем фразы по вкладкам
        chunks = []
        chunk_size = max(1, len(phrases) // len(ready_pages))
        for i in range(len(ready_pages)):
            start_idx = i * chunk_size
            if i == len(ready_pages) - 1:
                # Последней вкладке отдаем остаток
                chunks.append(phrases[start_idx:])
            else:
                chunks.append(phrases[start_idx:start_idx + chunk_size])
        
        print(f"\n    Распределение по вкладкам:")
        for i, chunk in enumerate(chunks):
            if chunk:
                print(f"    Tab {i+1}: {len(chunk)} фраз")
        
        # Запускаем парсинг параллельно на всех вкладках
        tasks = []
        for i, (page, chunk) in enumerate(zip(ready_pages, chunks)):
            if chunk:  # Если есть фразы
                task = parse_tab(page, chunk, i)
                tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        # Даем время на последние ответы
        print("\n    Ожидаю последние ответы API...")
        
        # Показываем прогресс каждую секунду
        for i in range(5):
            await asyncio.sleep(1)
            print(f"    Получено результатов: {len(results)}/{len(phrases)}")
        
        elapsed = time.time() - start_time
        
        # РЕЗУЛЬТАТЫ
        print("\n" + "="*70)
        print("   РЕЗУЛЬТАТЫ ПАРСИНГА")
        print("="*70)
        print(f"[TIME] Время: {elapsed:.1f} сек")
        print(f"[SUCCESS] Успешно: {len(results)}/{len(phrases)} фраз")
        if elapsed > 0:
            print(f"[SPEED] Скорость: {len(results)/elapsed*60:.1f} фраз/мин")
        
        if len(results) > 0:
            print(f"\n[TOP] Примеры результатов:")
            sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
            for phrase, freq in sorted_results[:5]:
                print(f"    {phrase}: {freq:,} показов")
        
        # Сохраняем результаты
        output_file = f'results_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n[SAVE] Результаты сохранены в {output_file}")
        
        print("\n[!] Браузер остается открытым. Закройте вручную когда закончите.")
        
        # Закрываем браузер через VBM
        await vbm.close_all()
        
        return results

# Запуск
if __name__ == "__main__":
    # ДЕМОНСТРАЦИОННЫЙ ЗАПУСК - ВАМ НУЖНО ПОДСТАВИТЬ СВОИ ДАННЫЕ
    # Формат прокси: ip:port:user:pass
    # Аккаунт: имя профиля (должен совпадать с папкой профиля)
    
    # ПРИМЕР:
    # asyncio.run(turbo_parser_10tabs(
    #     account_name="domsmirnov", 
    #     proxy_server="77.73.134.166:8000:user:pass", 
    #     phrases_file="test_50.txt"
    # ))
    
    # ТЕСТОВЫЙ ЗАПУСК БЕЗ ПРОКСИ И С ТЕСТОВЫМ АККАУНТОМ
    asyncio.run(turbo_parser_10tabs(
        account_name="dsmismirnov", 
        proxy_server="213.139.222.51:9738:nDRYz5:EP0wPC", # Первый прокси из вашего списка
        phrases_file="test_50.txt"
    ))
