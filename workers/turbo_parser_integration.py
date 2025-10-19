# -*- coding: utf-8 -*-
"""
ТУРБО ПАРСЕР ИНТЕГРАЦИЯ ДЛЯ SEMTOOL
Интегрирует наш парсер 195.9 фраз/мин в KeySet
Основан на parser_final_130plus.py + рекомендации GPT
# -*- coding: utf-8 -*-
"""

import asyncio
import time
import json
import random
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import quote

from playwright.async_api import async_playwright, Page, BrowserContext
import sqlite3

from ..core.db import SessionLocal
from ..core.models import Account
from .visual_browser_manager import VisualBrowserManager, BrowserStatus
from .auto_auth_handler import AutoAuthHandler


class AIMDController:
    # -*- coding: utf-8 -*-
"""AIMD регулятор скорости для избежания банов# -*- coding: utf-8 -*-
"""
    
    def __init__(self):
        self.delay_ms = 50  # начальная задержка (уменьшена для скорости)
        self.min_delay = 30
        self.max_delay = 300
        self.success_count = 0
        self.error_count = 0
        
    def on_success(self):
        # -*- coding: utf-8 -*-
"""При успехе уменьшаем задержку# -*- coding: utf-8 -*-
"""
        self.success_count += 1
        if self.success_count >= 10:
            self.delay_ms = max(self.min_delay, self.delay_ms - 10)
            self.success_count = 0
            
    def on_error(self):
        # -*- coding: utf-8 -*-
"""При ошибке увеличиваем задержку# -*- coding: utf-8 -*-
"""
        self.error_count += 1
        self.delay_ms = min(self.max_delay, self.delay_ms * 1.5)
        
    def get_delay(self):
        # -*- coding: utf-8 -*-
"""Получить текущую задержку в секундах# -*- coding: utf-8 -*-
"""
        return self.delay_ms / 1000.0


class TurboWordstatParser:
    # -*- coding: utf-8 -*-
"""
    Турбо парсер Wordstat - 195.9 фраз/мин
    Использует технологии из наших лучших парсеров
    # -*- coding: utf-8 -*-
"""
    
    def __init__(self, account: Optional[Account] = None, headless: bool = False, visual_mode: bool = True):
        self.account = account
        self.headless = headless
        self.visual_mode = visual_mode  # Визуальный режим с несколькими браузерами
        self.browser = None
        self.context = None
        self.pages = []  # мульти-табы
        self.results = {}
        self.aimd = AIMDController()
        self.num_tabs = 1  # количество вкладок для стабильной работы
        self.num_browsers = 1  # количество видимых браузеров
        self.visual_manager = None  # Менеджер визуальных браузеров
        self.db_path = Path("C:/AI/yandex/keyset/data/keyset.db")
        self.auth_handler = AutoAuthHandler()  # Обработчик авторизации
        
        # Визуальный менеджер будет использоваться для запуска браузера
        self.visual_manager = VisualBrowserManager(num_browsers=self.num_browsers)
        
        # Загружаем данные авторизации из accounts.json если нет в аккаунте
        if self.account:
            self._load_auth_data()
        
        # Статистика
        self.total_processed = 0
        self.total_errors = 0
        self.start_time = None
    
    def _load_auth_data(self):
        # -*- coding: utf-8 -*-
"""Загружаем данные авторизации из accounts.json# -*- coding: utf-8 -*-
"""
        try:
            accounts_json_path = Path("C:/AI/yandex/keyset/configs/accounts.json")
            if not accounts_json_path.exists():
                accounts_json_path = Path("C:/AI/yandex/configs/accounts.json")
            if not accounts_json_path.exists():
                accounts_json_path = Path("C:/AI/accounts.json")
            
            if accounts_json_path.exists():
                with open(accounts_json_path, 'r', encoding='utf-8') as f:
                    accounts_data = json.load(f)
                
                # Ищем данные для нашего аккаунта
                for acc_data in accounts_data:
                    if acc_data.get('login') == self.account.name:
                        # Заполняем данные если их нет
                        if not hasattr(self.account, 'password') or not self.account.password:
                            self.account.password = acc_data.get('password', '')
                        if not hasattr(self.account, 'secret_answer') or not self.account.secret_answer:
                            self.account.secret_answer = acc_data.get('secret_answer', '')
                        if not hasattr(self.account, 'login') or not self.account.login:
                            self.account.login = acc_data.get('login', self.account.name)
                        print(f"[AUTH] Загружены данные для {self.account.name}")
                        break
        except Exception as e:
            print(f"[AUTH] Ошибка загрузки accounts.json: {e}")
        
    async def init_browser(self):
        # -*- coding: utf-8 -*-
"""Инициализация браузера - ИСПОЛЬЗУЕМ VisualBrowserManager# -*- coding: utf-8 -*-
"""
        # Этот метод больше не используется, так как запуск браузера происходит в parse_batch_visual
        # или должен быть выполнен до вызова parse_batch_cdp (если он будет сохранен)
        pass
        
    async def setup_tabs(self):
        # -*- coding: utf-8 -*-
"""Настройка всех вкладок СРАЗУ (из финального парсера)# -*- coding: utf-8 -*-
"""
        # Этот метод больше не используется, так как VisualBrowserManager управляет вкладками
        pass
        
    async def close_browser(self):
        # -*- coding: utf-8 -*-
"""Закрытие браузера# -*- coding: utf-8 -*-
"""
        if self.visual_manager:
            await self.visual_manager.close_all()
            
        print("[TURBO] Все браузеры закрыты.")
    
    async def wait_wordstat_ready(self, page):
        # -*- coding: utf-8 -*-
"""Ожидание полной загрузки Wordstat (из файла 46)# -*- coding: utf-8 -*-
"""
        try:
            # 1) Базовая загрузка документа
            await page.wait_for_load_state('domcontentloaded', timeout=30000)
            
            # 2) Проверяем, не перебросило ли на паспорт
            current_url = page.url
            if "passport.yandex" in current_url or "passport.ya.ru" in current_url:
                print(f"[AUTH] Обнаружена страница авторизации!")
                
                # Попытаемся авторизоваться
                if self.auth_handler and self.account:
                    account_data = {
                        'login': self.account.login if hasattr(self.account, 'login') else self.account.name,
                        'password': self.account.password if hasattr(self.account, 'password') else '',
                        'secret_answer': self.account.secret_answer if hasattr(self.account, 'secret_answer') else ''
                    }
                    
                    success = await self.auth_handler.handle_auth_redirect(page, account_data)
                    if success:
                        print(f"[AUTH] Авторизация успешна")
                        # После авторизации переходим на wordstat
                        await page.goto("https://wordstat.yandex.ru", wait_until="domcontentloaded", timeout=30000)
                    else:
                        print(f"[AUTH] Ошибка авторизации")
            
            # 3) Ждём URL Wordstat
            await page.wait_for_url("**/wordstat.yandex.ru/**", timeout=30000)
            
            # 4) Дождаться сетевой активности для SPA
            try:
                await page.wait_for_load_state('networkidle', timeout=15000)
            except:
                pass  # Может не дождаться networkidle, это не критично
            
            # 5) Явный DOM-гейт - ждём поле поиска
            search_selectors = [
                'input[type="search"]',
                '[role="searchbox"]',
                'input.b-form-input__input',
                'input[name="text"]'
            ]
            
            for selector in search_selectors:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    break
                except:
                    continue
            
        except Exception as e:
            print(f"[WAIT] Ошибка ожидания загрузки Wordstat: {e}")
    
    async def handle_response(self, response, tab_id):
        # -*- coding: utf-8 -*-
"""Перехват XHR ответов от Wordstat API# -*- coding: utf-8 -*-
"""
        try:
            if "/wordstat/api" in response.url and response.status == 200:
                content_type = response.headers.get("content-type", "")
                if "application/json" in content_type:
                    # 1. Читаем ответ как байты для явного декодирования
                    try:
                        raw_body = await response.body()
                    except Exception as e:
                        print(f"[Tab {tab_id}] ERROR reading response body: {e}")
                        return
                    
                    # 2. Явное декодирование CP1251 -> UTF-8
                    try:
                        text = raw_body.decode("cp1251")
                        print(f"[Tab {tab_id}] INFO: Decoded body from cp1251")
                    except UnicodeDecodeError:
                        text = raw_body.decode("utf-8", "ignore")
                    
                    # 3. Парсинг JSON
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError as e:
                        print(f"[Tab {tab_id}] CRITICAL: Cannot parse JSON: {e}")
                        traceback.print_exc()
                        return
                    
                    # 4. Нормализация структуры (для совместимости со старым UI)
                    if 'data' in data and 'table' in data['data']:
                        tbl = data['data']['table']
                        tdata = tbl.get("tableData") or {}
                        
                        popular = tdata.get("popular") or []
                        assoc   = tdata.get("associations") or []
                        
                        # «старое» поле, которое ждёт фронт
                        # Если популяр есть, используем его, иначе ищем старое items
                        items = popular or tbl.get("items") or []
                        related = assoc
                        
                        # Обновляем структуру данных для дальнейшей обработки
                        tbl['items'] = items
                        tbl['related'] = related
                        
                        # ВАЖНО: totalValue теперь в data.totalValue, а не в data.data.totalValue
                        if 'totalValue' in data:
                             data['data']['totalValue'] = data['totalValue']
                        
                        # Если totalValue отсутствует, ищем его в items
                        if 'totalValue' not in data['data'] and items:
                            data['data']['totalValue'] = items[0].get('frequency', 0)
                        
                        # Устанавливаем частотность
                        frequency = data['data'].get('totalValue')
                    
                    # Извлекаем данные о частотности

                        
                        # Получаем запрос из request body
                        request_body = response.request.post_data
                        if request_body:
                            # Важно: request_body может быть в виде url-encoded строки,
                            # но для Yandex Wordstat это обычно JSON
                            try:
                                request_data = json.loads(request_body)
                                query = request_data.get("searchValue", "").strip()
                            except json.JSONDecodeError:
                                # Если не JSON, возможно это url-encoded строка
                                # В данном случае, мы ожидаем JSON, поэтому логируем ошибку
                                print(f"[Tab {tab_id}] WARNING: Request body is not JSON for {response.url}")
                                query = None
                            
                            if query:
                                self.results[query] = frequency
                                self.total_processed += 1
                                self.aimd.on_success()
                                print(f"[Tab {tab_id}] OK {query} = {frequency:,}")
        except Exception as e:
            pass  # Игнорируем ошибки парсинга ответов
    
    async def process_tab_worker(self, page, phrases, tab_id):
        # -*- coding: utf-8 -*-
"""Воркер для обработки фраз на одной вкладке (рабочая версия из parse_5_accounts_cdp.py)# -*- coding: utf-8 -*-
"""
        tab_results = []
        results_lock = asyncio.Lock()
        
        # Настраиваем обработчик ответов для перехвата частотностей
        async def handle_response(response):
            # -*- coding: utf-8 -*-
"""Перехватываем ответы API и извлекаем частотности# -*- coding: utf-8 -*-
"""
            if "/wordstat/api" in response.url and response.status == 200:
                try:
                    data = await response.json()
                    
                    # Извлекаем частотность из структуры данных
                    frequency = None
                    if 'data' in data and isinstance(data['data'], dict) and 'totalValue' in data['data']:
                        frequency = data['data']['totalValue']
                    elif 'totalValue' in data:
                        frequency = data['totalValue']
                    
                    if frequency is not None:
                        # Получаем маску из тела POST запроса
                        post_data = response.request.post_data
                        if post_data:
                            request_data = json.loads(post_data)
                            phrase = request_data.get("searchValue", "").strip()
                            
                            if phrase:
                                async with results_lock:
                                    self.results[phrase] = frequency
                                    tab_results.append({'query': phrase, 'frequency': frequency})
                                    self.total_processed += 1
                                    self.aimd.on_success()
                                print(f"[Tab {tab_id}] OK: {phrase} = {frequency:,} показов")
                except Exception as e:
                    pass  # Игнорируем ошибки парсинга
        
        # Подключаем обработчик к странице
        page.on("response", handle_response)
        
        # Загружаем и ждем полной готовности Wordstat
        if "wordstat.yandex.ru" not in page.url:
            print(f"[Tab {tab_id}] Открываю Wordstat...")
            try:
                await page.goto("https://wordstat.yandex.ru", timeout=15000)
                # Ждем полной загрузки страницы
                await page.wait_for_load_state('domcontentloaded')
                # networkidle может долго ждать, используем с малым таймаутом
                try:
                    await page.wait_for_load_state('networkidle', timeout=3000)
                except:
                    pass  # Не критично если не дождались
            except Exception as e:
                print(f"[Tab {tab_id}] Ошибка при открытии: {e}")
                return tab_results
        
        # Убеждаемся, что поле ввода доступно перед началом
        print(f"[Tab {tab_id}] Проверяю готовность страницы...")
        try:
            await page.wait_for_selector('input[placeholder*="слово"], input[name="text"]', timeout=10000)
            print(f"[Tab {tab_id}] Wordstat готов к работе!")
        except:
            print(f"[Tab {tab_id}] Поле ввода не найдено, страница не готова")
            return tab_results
        
        # Обрабатываем каждую фразу
        for phrase in phrases:
            if phrase in self.results:
                continue
            
            try:
                # Ищем поле ввода с разными селекторами
                input_field = None
                selectors = [
                    'input[name="text"]',
                    'input[placeholder*="слово"]',
                    '.b-form-input__input',
                    'input[type="text"]'
                ]
                
                for selector in selectors:
                    try:
                        if await page.locator(selector).count() > 0:
                            input_field = page.locator(selector).first
                            break
                    except:
                        continue
                
                if input_field:
                    # Очищаем и вводим фразу
                    await input_field.clear()
                    await input_field.fill(phrase)
                    
                    # Имитируем нажатие Enter. Нам не нужно ждать ответа,
                    # так как мы его перехватываем через handle_response.
                    await input_field.press("Enter")
                    
                    # Ждем ответ (минимальная задержка)
                    await asyncio.sleep(self.aimd.get_delay())
                else:
                    print(f"[Tab {tab_id}] Не найдено поле ввода для '{phrase}'")
                    
            except Exception as e:
                print(f"[Tab {tab_id}] Ошибка для '{phrase}': {str(e)[:50]}")
                self.aimd.on_error()
                
                # При ошибке пробуем перезагрузить страницу
                try:
                    await page.reload()
                    await asyncio.sleep(2)
                except:
                    pass
        
        # Даем время на последние ответы
        await asyncio.sleep(2)
        
        print(f"[Tab {tab_id}] Завершено: обработано {len(tab_results)} фраз")
        return tab_results
    
    async def parse_batch_visual(self, queries: List[str], region: int = 225):
        # -*- coding: utf-8 -*-
"""Парсинг батча фраз в визуальном режиме с несколькими браузерами# -*- coding: utf-8 -*-
"""
        self.start_time = time.time()
        
        # Подготавливаем аккаунты для браузеров - БЕРЕМ ИЗ БАЗЫ ДАННЫХ!
        accounts = []
        
        # Импортируем сервис аккаунтов для получения данных из БД
        from ..services import accounts as account_service
        
        # Получаем все аккаунты из базы данных
        all_accounts_db = account_service.list_accounts()
        
        # Фильтруем demo_account и конвертируем в нужный формат
        all_accounts = []
        for acc in all_accounts_db:
            if acc.name != "demo_account":
                # Берем профиль из БД!
                profile_path = acc.profile_path or f".profiles/{acc.name}"
                # Делаем полным путем если относительный
                if not profile_path.startswith("C:"):
                    profile_path = f"C:/AI/yandex/{profile_path}"
                
                all_accounts.append({
                    "name": acc.name,
                    "profile_path": profile_path,
                    "proxy": acc.proxy
                })
        
        if self.account:
            # Добавляем основной аккаунт первым
            profile_path = self.account.profile_path or f".profiles/{self.account.name}"
            if not profile_path.startswith("C:"):
                profile_path = f"C:/AI/yandex/{profile_path}"
            
            accounts.append({
                "name": self.account.name,
                "profile_path": profile_path,
                "proxy": self.account.proxy
            })
        
        # Добавляем остальные аккаунты до нужного количества браузеров
        for acc in all_accounts:
            if len(accounts) >= self.num_browsers:
                break
            # Пропускаем уже добавленный основной аккаунт
            if not any(a["name"] == acc["name"] for a in accounts):
                accounts.append(acc)
        
        try:
            # Запускаем браузеры в видимом режиме
            print(f"\n[VISUAL] Запуск {self.num_browsers} браузеров...")
            await self.visual_manager.start_all_browsers(accounts)
            
            # Ждем пока пользователь залогинится
            print("\n[!] ВАЖНО: Залогиньтесь в каждом открытом браузере!")
            print("После логина парсинг начнется автоматически.\n")
            
            # Получаем страницы для перехвата ответов (ВАЖНО: VisualManager должен иметь метод для этого)
            self.pages = [b.page for b in self.visual_manager.browsers.values() if b.page]
            
            # Настраиваем перехват ответов на всех вкладках
            for i, page in enumerate(self.pages):
                page.on("response", lambda response, tab_id=i: asyncio.create_task(
                    self.handle_response(response, tab_id)
                ))
            
            logged_in = await self.visual_manager.wait_for_all_logins(timeout=300)
            
            if not logged_in:
                print("[VISUAL] Ошибка: не удалось залогиниться")
                return []
            
            # Минимизируем браузеры для фоновой работы
            print("\n[VISUAL] Минимизация браузеров...")
            await self.visual_manager.minimize_all_browsers()
            
            # Парсим фразы
            print(f"\n[VISUAL] Начинаем парсинг {len(queries)} фраз...")
            
            # Теперь используем страницы для перехвата ответов
            results_dict = await self.parse_batch_parallel(queries)
            
            # Преобразуем результаты
            results = []
            for phrase, freq in results_dict.items():
                results.append({
                    'query': phrase,
                    'frequency': freq,
                    'timestamp': datetime.now().isoformat()
                })
                self.total_processed += 1
            
            # Сохраняем в БД
            await self.save_to_db(results)
            
            # Статистика
            elapsed = time.time() - self.start_time
            speed = len(results) / elapsed * 60 if elapsed > 0 else 0
            
            print(f"\n{'='*70}")
            print(f"   РЕЗУЛЬТАТЫ ВИЗУАЛЬНОГО ПАРСИНГА")
            print(f"{'='*70}")
            print(f"  Время: {elapsed:.1f} сек")
            print(f"  Обработано: {len(results)}/{len(queries)}")
            print(f"  Успех: {len(results)/len(queries)*100:.1f}%")
            print(f"  СКОРОСТЬ: {speed:.1f} фраз/мин")
            print(f"  Браузеров использовано: {self.num_browsers}")
            print(f"{'='*70}")
            
            return results
            
        finally:
            if self.visual_manager:
                await self.visual_manager.close_all()
    
    async def parse_batch(self, queries: List[str], region: int = 225):
        # -*- coding: utf-8 -*-
"""Парсинг батча фраз с мульти-табами# -*- coding: utf-8 -*-
"""
        # Если включен визуальный режим - используем visual manager
        if self.visual_mode and not self.headless:
            return await self.parse_batch_visual(queries, region)
        
        self.start_time = time.time()
        all_results = []  # Инициализируем результаты до try
        
        try:
            # Инициализация
            await self.init_browser()
            await self.setup_tabs()
        
            # Распределяем фразы по табам
            tab_phrases = [[] for _ in range(self.num_tabs)]
            for i, phrase in enumerate(queries):
                tab_idx = i % self.num_tabs
                tab_phrases[tab_idx].append(phrase)
            
            print(f"[TURBO] Распределено {len(queries)} фраз по {self.num_tabs} табам")
            
            # Запускаем воркеры параллельно
            tasks = []
            for i in range(self.num_tabs):
                if tab_phrases[i]:
                    page = self.pages[i]
                    tasks.append(self.process_tab_worker(page, tab_phrases[i], i))
            
            # Ждем завершения всех воркеров
            results = await asyncio.gather(*tasks, return_exceptions=True)  # return_exceptions чтобы не падать на ошибках
            
            # Собираем все результаты
            for tab_results in results:
                if tab_results and not isinstance(tab_results, Exception):
                    all_results.extend(tab_results)
            
            # Статистика
            elapsed = time.time() - self.start_time
            speed = len(all_results) / elapsed * 60 if elapsed > 0 else 0
            
            print(f"\n{'='*70}")
            print(f"   РЕЗУЛЬТАТЫ ТУРБО ПАРСИНГА")
            print(f"{'='*70}")
            print(f"  Время: {elapsed:.1f} сек")
            print(f"  Обработано: {len(all_results)}/{len(queries)}")
            print(f"  Успех: {len(all_results)/len(queries)*100:.1f}%" if queries else "0%")
            print(f"  СКОРОСТЬ: {speed:.1f} фраз/мин")
            print(f"{'='*70}")
            
        except Exception as e:
            print(f"[TURBO] КРИТИЧЕСКАЯ ОШИБКА в parse_batch: {e}")
            import traceback
            traceback.print_exc()
        
        return all_results
    
    async def save_to_db(self, results: List[Dict]):
        # -*- coding: utf-8 -*-
"""Сохранение результатов в БД KeySet# -*- coding: utf-8 -*-
"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for result in results:
            cursor.execute(# -*- coding: utf-8 -*-
"""
                INSERT OR REPLACE INTO freq_results 
                (mask, region, freq_total, freq_exact, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            # -*- coding: utf-8 -*-
""", (
                result['query'],
                225,  # регион РФ
                result['frequency'],
                result['frequency'],
                'ok',
                result['timestamp']
            ))
        
        conn.commit()
        conn.close()
        print(f"[TURBO] Сохранено {len(results)} результатов в БД")
    
    async def close(self):
        # -*- coding: utf-8 -*-
"""Отключение от CDP браузера (НЕ закрываем Chrome - он остается работать)# -*- coding: utf-8 -*-
"""
        try:
            # При CDP подключении мы НЕ закрываем Chrome!
            # Просто отключаемся
            print("[TURBO] Отключаюсь от Chrome CDP...")
            
            if hasattr(self, 'playwright'):
                await self.playwright.stop()
            
            print("[TURBO] Отключение завершено. Chrome остается работать для следующих запусков.")
        except Exception as e:
            print(f"[TURBO] Ошибка при отключении: {e}")


# Дополнительные модули из рекомендаций GPT

class ForecastParser:
    # -*- coding: utf-8 -*-
"""Парсер прогноза бюджета через web интерфейс Директа# -*- coding: utf-8 -*-
"""
    
    async def parse_forecast(self, phrases: List[str], region: int = 225):
        # -*- coding: utf-8 -*-
"""Получить прогноз бюджета для фраз# -*- coding: utf-8 -*-
"""
        # TODO: Реализовать парсинг страницы прогноза Директа
        pass


class SuggestParser:
    # -*- coding: utf-8 -*-
"""Парсер подсказок Яндекса для расширения семантики# -*- coding: utf-8 -*-
"""
    
    async def get_suggestions(self, seed_phrase: str) -> List[str]:
        # -*- coding: utf-8 -*-
"""Получить подсказки для фразы# -*- coding: utf-8 -*-
"""
        # TODO: Использовать API подсказок Яндекса
        pass


class PhraseClusterer:
    # -*- coding: utf-8 -*-
"""Кластеризация фраз и генерация минус-слов# -*- coding: utf-8 -*-
"""
    
    def cluster_phrases(self, phrases: List[str], threshold: float = 0.6):
        # -*- coding: utf-8 -*-
"""Кластеризация похожих фраз# -*- coding: utf-8 -*-
"""
        # TODO: Реализовать через pymorphy2 + TF-IDF
        pass
    
    def generate_minus_words(self, clusters: Dict):
        # -*- coding: utf-8 -*-
"""Генерация кросс-минус слов между кластерами# -*- coding: utf-8 -*-
"""
        # TODO: Найти пересечения между кластерами
        pass


# Главная функция для интеграции в KeySet
async def run_turbo_parser(queries: List[str], account: Optional[Account] = None, headless: bool = False):
    # -*- coding: utf-8 -*-
"""
    Запуск турбо парсера из GUI KeySet
    
    Args:
        queries: список фраз для парсинга
        account: аккаунт с профилем и прокси
        headless: фоновый режим
    
    Returns:
        Список результатов с частотностями
    # -*- coding: utf-8 -*-
"""
    parser = TurboWordstatParser(account=account, headless=headless)
    
    try:
        results = await parser.parse_batch(queries)
        await parser.save_to_db(results)
        return results
    finally:
        await parser.close()


if __name__ == "__main__":
    # Тестовый запуск
    test_queries = [
        "купить квартиру москва",
        "ремонт квартир",
        "заказать пиццу",
        "доставка еды",
        "такси москва"
    ]
    
    asyncio.run(run_turbo_parser(test_queries, headless=False))
