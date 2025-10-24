"""
Умный автологин для Яндекса на основе решения GPT из файла новое/39
Обрабатывает все варианты форм авторизации и правильно работает с прокси
"""
import re
import asyncio
import json
from pathlib import Path
from datetime import datetime
from playwright.async_api import async_playwright, expect
from PySide6.QtCore import QObject, Signal

try:
    from ..utils.proxy import proxy_to_playwright  # type: ignore
except ImportError:  # pragma: no cover - fallback when running as script
    try:
        from utils.proxy import proxy_to_playwright  # type: ignore
    except ImportError:  # pragma: no cover
        proxy_to_playwright = None

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOGIN_LOG_FILE = LOG_DIR / "autologin_debug.log"


def _log_debug(message: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if not LOGIN_LOG_FILE.exists():
            LOGIN_LOG_FILE.touch()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with LOGIN_LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(f"[{timestamp}] {message}\n")
    except Exception:
        pass


class YandexSmartLogin(QObject):
    """Умный автологин с обработкой всех вариантов форм Яндекса"""
    
    # Qt сигналы для GUI
    status_update = Signal(str)
    progress_update = Signal(int)
    secret_question_required = Signal(str, str)
    login_completed = Signal(bool, str)
    
    def __init__(self):
        super().__init__()
        self.secret_answer = None
        self._context = None  # Сохраняем контекст чтобы браузер не закрылся
        
    def set_secret_answer(self, answer):
        """Установить ответ на секретный вопрос"""
        self.secret_answer = answer
        
    async def login(self, account_name, profile_path, proxy=None):
        """
        Основная функция умного логина
        Обрабатывает 3 типа форм: новая (2 шага), легаси, challenge
        """
        try:
            _log_debug(f"login start account={account_name} profile={profile_path} proxy={proxy}")
            self.status_update.emit(f"[START] Запуск автологина для {account_name}...")
            self.progress_update.emit(10)
            
            # Загружаем данные аккаунта из конфига
            config_path = Path("C:/AI/yandex/configs/accounts.json")
            if not config_path.exists():
                raise Exception("Файл accounts.json не найден")
                
            with open(config_path, 'r', encoding='utf-8') as f:
                accounts = json.load(f)
                account_data = next((a for a in accounts if a["login"] == account_name), None)
                if not account_data:
                    raise Exception(f"Аккаунт {account_name} не найден в конфиге")
                
            login = account_data['login']
            password = account_data['password']
            secret_answer = account_data.get('secret', self.secret_answer)
            
            # ВАЖНО: Добавляем задержку перед запуском чтобы не вызвать капчу!
            await asyncio.sleep(5)  # Ждем 5 секунд перед запуском
            
            # НЕ используем async with чтобы браузер не закрылся автоматически!
            self._playwright = await async_playwright().start()
            p = self._playwright
            
            try:
                # Правильная обработка прокси через Playwright
                proxy_config = None
                if proxy:
                    self.status_update.emit("[PROXY] Настройка прокси...")
                    _log_debug(f"raw proxy value received: {proxy}")
                    try:
                        if callable(proxy_to_playwright):
                            proxy_config = proxy_to_playwright(proxy)
                        else:
                            proxy_config = None
                    except Exception as exc:  # pragma: no cover - diagnostic only
                        proxy_config = None
                        self.status_update.emit(f"[WARNING] Ошибка разбора прокси: {exc}")
                        _log_debug(f"proxy parse error: {exc}")

                    if proxy_config and proxy_config.get("server"):
                        server_label = proxy_config.get("server", "")
                        user_label = proxy_config.get("username")
                        label_suffix = f" (user: {user_label})" if user_label else ""
                        self.status_update.emit(f"[OK] Прокси настроен: {server_label}{label_suffix}")
                        _log_debug(f"normalized proxy value: {proxy_config}")
                    else:
                        self.status_update.emit("[WARNING] Не удалось распознать прокси — запуск без прокси")
                        _log_debug("proxy parsing failed; running without proxy")
                        proxy_config = None
                else:
                    _log_debug("no proxy provided; running without proxy")
                
                # Запускаем Chrome с persistent context
                # Playwright сам обработает прокси авторизацию!
                self.status_update.emit("[BROWSER] Запуск браузера...")
                self.progress_update.emit(20)
                
                self.status_update.emit(f"[CONTEXT] Создание persistent context для {profile_path}")
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=profile_path,
                    channel="chrome",  # Используем установленный Chrome
                    proxy=proxy_config,  # Прокси передаем через Playwright!
                    headless=False,
                    args=[
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",  # Предотвращает закрытие из-за нехватки памяти
                        "--no-sandbox"  # Может помочь с стабильностью
                    ],
                    ignore_default_args=["--enable-automation"]
                )
                _log_debug(f"launch_persistent_context completed for {account_name} proxy={proxy_config}")
                self.status_update.emit(f"[CONTEXT] Контекст создан, браузер запущен")
                
                # Используем существующую страницу или создаем новую
                if context.pages:
                    page = context.pages[0]
                    self.status_update.emit(f"[PAGE] Используем существующую страницу")
                else:
                    page = await context.new_page()
                    self.status_update.emit(f"[PAGE] Создана новая страница")
                
                # Добавляем обработчик закрытия страницы для диагностики
                page.on("close", lambda: self.status_update.emit("[WARNING] Страница была закрыта!"))
                
                # СРАЗУ ПЕРЕХОДИМ НА WORDSTAT, а не оставляем about:blank!
                try:
                    self.status_update.emit(f"[NAVIGATE] Переход на wordstat.yandex.ru...")
                    await page.goto("https://wordstat.yandex.ru", wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)  # Даем странице загрузиться
                    self.status_update.emit(f"[NAVIGATE] Текущий URL: {page.url}")
                except Exception as e:
                    self.status_update.emit(f"[WARNING] Не удалось перейти на wordstat: {str(e)}")
                    self.status_update.emit(f"[WARNING] Текущий URL: {page.url}")
                
                # Данные аккаунта уже загружены выше
                # password и secret_answer уже определены
                
                # Ждем загрузки и проверяем авторизацию
                self.status_update.emit("[CHECK] Проверка авторизации...")
                self.progress_update.emit(30)
                
                # Даем странице загрузиться
                await asyncio.sleep(3)
                current_url = page.url
                
                # ПРОВЕРЯЕМ РЕАЛЬНО ЛИ АВТОРИЗОВАН по элементам на странице
                is_authorized = False
                try:
                    # Если есть поле поиска Wordstat - значит авторизован
                    search_input = page.locator('input[name="words"], input.b-form-input__input')
                    if await search_input.count() > 0:
                        self.status_update.emit(f"[CHECK] Найдено поле поиска Wordstat - аккаунт авторизован")
                        is_authorized = True
                    else:
                        self.status_update.emit(f"[CHECK] Поле поиска не найдено - нужна авторизация")
                except:
                    pass
                
                # Если авторизован - выходим
                if is_authorized and "wordstat.yandex" in current_url:
                    self.status_update.emit(f"[OK] {account_name} уже авторизован в Wordstat!")
                    self.progress_update.emit(100)
                    self.login_completed.emit(True, "Уже авторизован")
                    self._context = context  # Сохраняем контекст
                    return True
                
                # НЕ АВТОРИЗОВАН - нужно залогиниться
                self.status_update.emit(f"[AUTH] Требуется авторизация для {account_name}")
                
                # Проверяем куда нас редиректнуло
                current_url = page.url
                
                # ОБРАБОТКА СТРАНИЦЫ ВЫБОРА АККАУНТА /pwl-yandex
                if "/pwl-yandex" in current_url or "/auth/list" in current_url:
                    self.status_update.emit("[PWL] Страница выбора аккаунта...")
                    
                    # СНАЧАЛА проверяем - может наш аккаунт уже есть в списке?
                    try:
                        # Ищем наш аккаунт в списке
                        account_selector = f'a[href*="{account_name}"], div:has-text("{account_name}"), span:has-text("{account_name}")'
                        existing_account = page.locator(account_selector).first
                        
                        if await existing_account.count() > 0:
                            self.status_update.emit(f"[PWL] Нашел аккаунт {account_name} в списке, выбираю его...")
                            await existing_account.click()
                            await page.wait_for_load_state("domcontentloaded")
                            await asyncio.sleep(3)
                            
                            # Проверяем - перешли ли на wordstat?
                            if "wordstat.yandex" in page.url:
                                self.status_update.emit(f"[OK] Авторизован через выбор аккаунта!")
                                self.progress_update.emit(100)
                                self.login_completed.emit(True, "Авторизован через выбор")
                                self._context = context
                                return True
                        else:
                            # Аккаунта нет в списке - нужно добавить новый
                            self.status_update.emit("[PWL] Аккаунт не найден в списке, добавляю новый...")
                            add_btn = page.locator('a[href*="/auth/add"], a:has-text("Добавить"), button:has-text("Добавить")')
                            if await add_btn.count() > 0:
                                await add_btn.first.click()
                                await page.wait_for_load_state("domcontentloaded")
                                await asyncio.sleep(2)
                    except Exception as e:
                        self.status_update.emit(f"[PWL] Ошибка при выборе аккаунта: {e}")
                        pass
                
                # Если не на паспорте - переходим туда МЕДЛЕННО
                elif "passport.yandex" not in current_url:
                    await asyncio.sleep(3)  # Еще задержка
                    await page.goto("https://passport.yandex.ru/auth?retpath=https://wordstat.yandex.ru", 
                                  wait_until="domcontentloaded", timeout=60000)
                
                # Ждем загрузки страницы и проверяем URL
                await page.wait_for_load_state("domcontentloaded")
                await asyncio.sleep(1)  # Даем время на возможные редиректы
                
                # Проверяем текущий URL
                current_url = page.url
                # self.status_update.emit(f"[DEBUG] Текущий URL: {current_url}")
                
                # НЕ СЧИТАЕМ что авторизован сразу! Нужно пройти авторизацию!
                # Закомментирую эту проверку - пусть всегда идет на авторизацию
                # if current_url.startswith("https://wordstat.yandex"):
                #     self.status_update.emit(f"[OK] {account_name} уже авторизован!")
                #     self.progress_update.emit(100)
                #     self.login_completed.emit(True, "Аккаунт уже авторизован")
                #     # НЕ ЗАКРЫВАЕМ БРАУЗЕР! Он должен остаться открытым!
                #     return True
                

                
                # Если не на паспорте - что-то пошло не так
                if "passport.yandex" not in current_url:
                    self.status_update.emit(f"[WARNING] Неожиданный URL: {current_url}")
                    # Но продолжаем - может форма все равно есть
                

                
                # УМНАЯ ОБРАБОТКА ФОРМ (из решения GPT)
                self.status_update.emit("[DETECT] Определение типа формы авторизации...")
                self.progress_update.emit(40)
                
                # Детект типа формы
                await page.wait_for_load_state("domcontentloaded")
                is_new_form = await page.locator("#passp-field-login").count() > 0
                is_legacy = (not is_new_form) and await page.get_by_role(
                    "textbox", name=re.compile("логин", re.I)
                ).count() > 0
                
                # Если никакой формы не найдено - возможно уже авторизован или страница выбора?
                if not is_new_form and not is_legacy:
                    self.status_update.emit("[WARNING] Форма логина не найдена, проверяем страницу...")
                    current_url = page.url
                    
                    # Проверяем - может это страница выбора аккаунта?
                    if "/pwl-yandex" in current_url or "/auth/list" in current_url:
                        self.status_update.emit("[PWL] Обнаружена страница выбора аккаунта...")
                        
                        # Ищем кнопку "Добавить аккаунт"
                        add_btn = page.locator('a[href*="/auth/add"], button:has-text("Добавить"), a:has-text("Другой")')
                        if await add_btn.count() > 0:
                            self.status_update.emit("[PWL] Нажимаю 'Добавить аккаунт'...")
                            await add_btn.first.click()
                            await page.wait_for_load_state("domcontentloaded")
                            await asyncio.sleep(3)
                            
                            # После клика проверяем форму снова
                            is_new_form = await page.locator("#passp-field-login").count() > 0
                            if not is_new_form:
                                is_legacy = await page.get_by_role("textbox", name=re.compile("логин", re.I)).count() > 0
                    
                    # Если уже авторизован
                    elif current_url.startswith("https://wordstat.yandex") or "ya.ru" in current_url:
                        self.status_update.emit(f"[OK] {account_name} уже авторизован!")
                        self.progress_update.emit(100)
                        self.login_completed.emit(True, "Аккаунт уже авторизован")
                        # НЕ ЗАКРЫВАЕМ БРАУЗЕР!
                        return True
                    
                    # Если все еще не нашли форму - ошибка
                    if not is_new_form and not is_legacy:
                        self.status_update.emit(f"[ERROR] Неизвестная страница: {current_url}")
                        # НЕ вызываем raise - просто возвращаем False
                        self.login_completed.emit(False, f"Не найдена форма логина на {current_url}")
                        return False
                
                # 1. НОВАЯ ФОРМА (два шага)
                if is_new_form:
                    self.status_update.emit("[FORM] Обнаружена новая форма (2 шага)")
                    self.progress_update.emit(50)
                    
                    # ВАЖНО: Добавляем задержку перед вводом чтобы не вызвать капчу
                    await asyncio.sleep(3)
                    
                    # Вводим логин МЕДЛЕННО
                    await page.fill("#passp-field-login", account_name, timeout=30000)
                    
                    # Синхронизированный клик с ожиданием навигации
                    await asyncio.gather(
                        page.wait_for_url(re.compile(r"auth/(password|challenge|verify|welcome|profile)", re.I), 
                                        timeout=20000),
                        page.locator('button[type=submit], button:has-text("Войти")').click()
                    )
                    
                    # Вводим пароль если есть поле
                    if await page.locator("#passp-field-passwd").count():
                        self.status_update.emit("[PASSWORD] Ввод пароля...")
                        self.progress_update.emit(60)
                        
                        await page.fill("#passp-field-passwd", password)
                        
                        await asyncio.gather(
                            page.wait_for_url(re.compile(r"(challenge|finish|id\.yandex|profile|success|wordstat)", re.I), 
                                            timeout=20000),
                            page.locator('button[type=submit], button:has-text("Войти")').click()
                        )
                
                # 2. ЛЕГАСИ ФОРМА (оба поля сразу)
                elif is_legacy:
                    self.status_update.emit("[FORM] Обнаружена легаси форма")
                    self.progress_update.emit(50)
                    
                    form = page.locator("form")
                    login_field = form.get_by_role("textbox", name=re.compile("логин", re.I))
                    if await login_field.count() > 0:
                        await login_field.fill(account_name)
                    
                    password_field = form.locator('input[type="password"]')
                    if await password_field.count() > 0:
                        await password_field.fill(password)
                    
                    await asyncio.gather(
                        page.wait_for_url(re.compile(r"(challenge|finish|id\.yandex|profile|welcome|wordstat)", re.I), 
                                        timeout=20000),
                        form.get_by_role("button", name=re.compile("войти", re.I)).click()
                    )
                
                # Ждем результата
                await asyncio.sleep(2)
                self.progress_update.emit(70)
                
                # 3. ОБРАБОТКА CHALLENGE (секретный вопрос в iframe)
                current_url = page.url
                has_challenge_frame = await page.locator(
                    'iframe[src*="challenge"], iframe[name*="passp:challenge"]'
                ).count() > 0
                
                if has_challenge_frame or re.search(r"auth/challenge", page.url, re.I):
                    self.status_update.emit("[CHALLENGE] Обнаружен секретный вопрос...")
                    self.progress_update.emit(80)
                    
                    # Работаем с iframe через frameLocator
                    ch = page.frame_locator('iframe[src*="challenge"], iframe[name*="passp:challenge"]')
                    
                    # Получаем текст вопроса
                    try:
                        question_elem = ch.locator('.challenge-form__question')
                        if await question_elem.count():
                            question_text = await question_elem.inner_text()
                        else:
                            question_text = "Введите ответ на секретный вопрос"
                    except:
                        question_text = "Введите ответ на секретный вопрос"
                    
                    # Определяем ответ
                    answer_to_use = secret_answer or self.secret_answer
                    
                    if not answer_to_use:
                        # Запрашиваем у пользователя
                        self.secret_question_required.emit(question_text, account_name)
                        
                        # Ждем ответа
                        for _ in range(60):  # 60 секунд на ответ
                            if self.secret_answer:
                                answer_to_use = self.secret_answer
                                self.secret_answer = None
                                break
                            await asyncio.sleep(1)
                        else:
                            raise Exception("Не получен ответ на секретный вопрос")
                    
                    # Находим поле ввода и вводим ответ
                    answer_input = ch.get_by_label(re.compile("Ответ на контрольный вопрос", re.I)).or_(
                        ch.get_by_role("textbox")
                    )
                    
                    # Ждем пока поле станет редактируемым
                    await expect(answer_input).to_be_editable()
                    await answer_input.fill(answer_to_use)
                    
                    # Нажимаем продолжить
                    await ch.get_by_role("button", name=re.compile("Продолжить|Continue", re.I)).click()
                
                # Финальная проверка
                await asyncio.sleep(3)
                self.progress_update.emit(90)
                
                current_url = page.url
                
                # Проверяем успешность авторизации
                if any(current_url.startswith(f"https://{x}") for x in ["ya.ru", "id.yandex", "wordstat.yandex"]):
                    self.status_update.emit(f"[SUCCESS] Успешная авторизация {account_name}!")
                    
                    # Если не на wordstat - переходим туда
                    if not current_url.startswith("https://wordstat.yandex"):
                        await page.goto("https://wordstat.yandex.ru")
                        await page.wait_for_load_state("networkidle")
                    
                    self.progress_update.emit(100)
                    self.login_completed.emit(True, "Авторизация успешна")
                    
                    # Оставляем браузер открытым для дальнейшей работы
                    await asyncio.sleep(2)
                    
                    # ВАЖНО: Сохраняем контекст чтобы браузер не закрылся!
                    self._context = context
                    self.status_update.emit(f"[SUCCESS] Браузер остается открытым для {account_name}")
                    return True
                else:
                    # Авторизация не удалась, но браузер оставляем открытым
                    self._context = context
                    self.status_update.emit(f"[FAILED] Авторизация не завершена: {current_url}")
                    raise Exception(f"Не удалось авторизоваться. Страница: {current_url}")
            
            except Exception as e:
                # При ошибке тоже сохраняем контекст
                if 'context' in locals():
                    self._context = context
                raise
                    
        except Exception as e:
            import traceback
            full_error = traceback.format_exc()
            self.status_update.emit(f"[ERROR] Ошибка: {str(e)}")
            self.status_update.emit(f"[TRACEBACK] {full_error}")
            print(f"ПОЛНАЯ ОШИБКА:\n{full_error}")
            self.login_completed.emit(False, str(e))
            # НЕ закрываем контекст - пусть браузер остается открытым даже при ошибке
            return False
