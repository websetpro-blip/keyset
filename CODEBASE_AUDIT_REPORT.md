# KeySet Codebase Audit Report
Дата: 2024-01-15
Ветка: main/master
Всего файлов Python: 121
Всего строк кода: 32,852

## Executive Summary

Проведён комплексный аудит кодовой базы KeySet - desktop-приложения для парсинга Yandex Wordstat/Direct на Python 3 с PySide6, Playwright, SQLAlchemy. 

**Общее состояние:** Проект функционален, но имеет существенный технический долг. Обнаружены критические проблемы с обработкой ошибок, хардкодными путями, утечками ресурсов и безопасностью.

**Критичные проблемы (требуют немедленного внимания):**
- 18+ файлов с bare `except:` без обработки конкретных исключений
- Hardcoded абсолютные пути `C:/AI/yandex` в 24 файлах
- Потенциальные утечки ресурсов браузеров/контекстов Playwright
- Отсутствие проверок на None в критических местах
- Хранение credentials в plaintext (accounts.json)
- Минимальное тестовое покрытие (< 5%)

**Архитектурные проблемы:**
- Нарушение разделения UI/domain/infra в некоторых модулях
- Дублирование логики автологина в 5+ воркерах
- Backup-файлы (.bak, _old, _backup) в production коде

---

## 1. Архитектура

### Структура проекта

```
keyset/
├── app/              # UI слой (PySide6 виджеты, вкладки, диалоги)
│   ├── tabs/         # Вкладки интерфейса
│   ├── dialogs/      # Модальные окна
│   └── widgets/      # Переиспользуемые компоненты
├── services/         # Бизнес-логика (парсеры, менеджеры, фабрики)
├── workers/          # QThread воркеры для async операций
├── core/             # Инфраструктура (БД, модели, настройки)
├── utils/            # Вспомогательные функции
├── tools/            # Утилиты и скрипты
├── scripts/          # Миграции БД
└── solvers/          # Решатели капчи
```

**Положительно:**
- Чёткое разделение UI (app/) от domain logic (services/)
- Выделенная папка для QThread воркеров
- Централизованная БД логика в core/

### Проблемы

#### 🔴 Критично

1. **Hardcoded пути разработчика в 24 файлах**
   - `app/main.py:324` - `WORKSPACE_ROOT = Path(r"C:/AI/yandex")`
   - `workers/auto_login_worker.py:32` - `self.accounts_file = Path("C:/AI/yandex/configs/accounts.json")`
   - `workers/auto_login_worker.py:132` - `profile_path = str(Path("C:/AI/yandex") / profile_path)`
   - `services/chrome_launcher.py` - хардкодный базовый путь
   - **Последствие:** Приложение не запустится на других машинах/путях

2. **Backup файлы в production**
   - `app/accounts_tab_extended_old.py` (1659 lines)
   - `app/accounts_tab_extended_custom_backup.py` (1815 lines)
   - `app/main_full_backup.py` (1869 lines)
   - `app/keys_panel_dark_backup.py` (380 lines)
   - `workers/visual_browser_manager_OLD.py` (669 lines)
   - **Последствие:** Раздувание репозитория, путаница какой файл актуален

3. **Циклические импорты (потенциальные)**
   - `services/` модули импортируют `core.models`
   - `workers/` импортируют `services/` и `app/`
   - Try/except импорты указывают на проблемы структуры:
     ```python
     # services/frequency.py:9-14
     try:
         from ..core.db import SessionLocal
     except ImportError:
         from core.db import SessionLocal
     ```

#### 🟡 Важно

4. **Tight coupling UI и domain логики**
   - `app/accounts_tab_extended.py:2014 lines` - гигантская вкладка с бизнес-логикой
   - Логика автологина дублируется в UI и воркерах
   - Прямые импорты сервисов в виджеты

5. **Дублирование кода автологина**
   - `workers/auto_login_worker.py` (597 lines)
   - `workers/auto_login_cdp.py`
   - `workers/auto_login_correct.py`
   - `workers/yandex_smart_login.py` (465 lines)
   - `workers/wordstat_auth_checker.py`
   - **5 разных реализаций логина Яндекса!**

### Рекомендации

1. **Немедленно:**
   - Вынести все пути в `.env` или `config/settings.json`
   - Использовать `Path(__file__).parent.parent` для относительных путей
   - Удалить все `*_old.py`, `*_backup.py`, `.bak` файлы из VCS

2. **В ближайшее время:**
   - Объединить логику автологина в единый сервис `services/auth.py`
   - Рефакторить `accounts_tab_extended.py` - вынести логику в сервисы
   - Исправить try/except импорты - использовать абсолютные импорты

3. **Техдолг:**
   - Внедрить dependency injection для сервисов
   - Добавить интерфейсы (Protocols) для абстракций
   - Разбить большие модули на подмодули

---

## 2. Качество кода

### Метрики

- **Средний размер функции:** ~25 строк
- **Функций >100 строк:** ~15-20 (оценка)
- **Классов >500 строк:** 6 файлов >500 строк
- **Дубликатов кода:** Высокий уровень (автологин, парсинг)

### Top-10 проблемных файлов

1. `app/accounts_tab_extended.py:2014 lines` - монолитная вкладка
2. `app/main_full_backup.py:1869 lines` - backup файл в репозитории
3. `app/accounts_tab_extended_custom_backup.py:1815 lines` - дубликат
4. `app/accounts_tab_extended_old.py:1659 lines` - устаревший код
5. `services/multiparser_manager.py:777 lines` - сложный менеджер
6. `workers/visual_browser_manager.py:697 lines` - менеджер браузеров
7. `workers/visual_browser_manager_OLD.py:669 lines` - старая версия
8. `services/browser_factory.py:648 lines` - фабрика с кучей логики
9. `workers/auto_login_worker.py:597 lines` - длинный воркер
10. `app/turbo_tab_qt.py:508 lines` - вкладка турбо-парсера

### Проблемы code smells

#### 🔴 Критично

1. **Magic numbers и hardcoded values**
   ```python
   # workers/visual_browser_manager.py:84
   self.num_browsers = min(num_browsers, len(self.AUTHORIZED_PROFILES))
   # Хардкодные имена профилей в коде:
   AUTHORIZED_PROFILES = ["dsmismirnov", "kuznepetya", "vfefyodorov", ...]
   ```

2. **Комментарии вместо чистого кода**
   ```python
   # app/accounts_tab_extended.py:5-9
   # ПРАВИЛО №1: НЕ ЛОМАТЬ ТО ЧТО РАБОТАЕТ!
   # - Не удалять рабочие функции
   # - Не изменять работающую логику
   # - Не трогать то, что пользователь не просил менять
   ```
   **Проблема:** Защитное программирование из-за страха что-то сломать

3. **Commented out code**
   - `app/accounts_tab_extended.py:44` - `# Старый worker больше не используется`
   - Множество закомментированных строк по всему коду

#### 🟡 Важно

4. **Длинные функции**
   - `workers/auto_login_worker.py:75-598` - метод `auto_login` ~500 строк
   - `app/accounts_tab_extended.py` - методы >100 строк

5. **Глубокая вложенность (>4 уровней)**
   ```python
   # workers/auto_login_worker.py - множество вложенных try/except/if
   try:
       if condition:
           try:
               for item in items:
                   if nested_condition:
                       try:
                           ...
   ```

6. **God objects**
   - `AccountsTabExtended` - делает всё: UI, логика, валидация, файлы
   - `VisualBrowserManager` - управление, позиционирование, статусы, парсинг

### Рекомендации

1. **Немедленно:**
   - Удалить закомментированный код
   - Вынести hardcoded значения в константы/конфиги
   - Удалить backup файлы

2. **В ближайшее время:**
   - Разбить функции >100 строк на подфункции
   - Применить Extract Method рефакторинг для дубликатов
   - Снизить вложенность через early returns

3. **Техдолг:**
   - Установить линтеры (ruff, pylint) с ограничением сложности
   - Внедрить pre-commit hooks
   - Code review процесс

---

## 3. Обработка ошибок

### Критичные места без обработки

#### 🔴 Критично: Bare except statements

Найдено **18 файлов с голыми `except:`** - перехватывают все исключения включая SystemExit, KeyboardInterrupt.

**Примеры:**

1. `workers/visual_browser_manager_OLD.py` - **9 bare excepts**
   ```python
   # Line ~250
   except:
       pass
   ```

2. `workers/auto_login_worker.py` - **9 bare excepts**
   ```python
   # Line ~200
   except:
       search_field = None
   ```

3. `workers/session_frequency_runner.py`
   ```python
   except:
       self.status.emit("Ошибка браузера")
   ```

4. `services/frequency.py`, `services/direct.py`, `services/forecast_ui.py`
   - Bare excepts в критических операциях БД

5. `workers/full_pipeline_worker.py` - в pipeline обработке

**Последствия:**
- Скрываются реальные ошибки
- Невозможно debug
- Могут перехватываться Ctrl+C (KeyboardInterrupt)
- Маскируются баги

#### 🟡 Важно: Отсутствие обработки ошибок

1. **Файловые операции без try/except**
   ```python
   # app/main.py:96
   accounts = json.loads(accounts_file.read_text(encoding="utf-8"))
   # Нет проверки существования файла, обработки JSON ошибок
   ```

2. **Сетевые операции**
   - Большинство Playwright операций обёрнуты, но некоторые нет
   - Отсутствуют retry механизмы для network errors

3. **БД операции**
   ```python
   # services/frequency.py:29
   with SessionLocal() as session:
       # Нет обработки IntegrityError, OperationalError
       session.commit()
   ```

#### 🟢 Желательно: Логирование ошибок

1. **Минимальное логирование**
   - Много `print()` вместо `logging`
   - Отсутствует structured logging
   - Нет rotation логов

2. **Неинформативные сообщения об ошибках**
   ```python
   except Exception as e:
       self.status.emit(f"Ошибка браузера")
       # Потеряна информация о типе ошибки, стек трейс
   ```

### Рекомендации

1. **Немедленно исправить все bare except:**
   ```python
   # Было:
   except:
       pass
   
   # Стало:
   except (PlaywrightError, TimeoutError) as e:
       logger.error(f"Browser error: {e}", exc_info=True)
       raise
   ```

2. **Добавить обработку файловых операций:**
   ```python
   try:
       accounts = json.loads(accounts_file.read_text(encoding="utf-8"))
   except FileNotFoundError:
       logger.warning(f"Accounts file not found: {accounts_file}")
       return []
   except json.JSONDecodeError as e:
       logger.error(f"Invalid JSON in accounts file: {e}")
       return []
   ```

3. **Внедрить централизованное логирование:**
   ```python
   # core/logging.py
   import logging
   from logging.handlers import RotatingFileHandler
   
   def setup_logging():
       logger = logging.getLogger("keyset")
       handler = RotatingFileHandler("logs/keyset.log", maxBytes=10MB)
       logger.addHandler(handler)
   ```

---

## 4. Потенциальные баги

### Высокий приоритет

#### 🔴 Критично

1. **Утечки ресурсов Playwright**
   
   **Проблема:** Браузеры/контексты не всегда закрываются при ошибках
   
   ```python
   # workers/visual_browser_manager.py:160-170
   self.context = await self.playwright.chromium.launch_persistent_context(...)
   # Нет гарантии закрытия при exception
   
   # workers/auto_login_worker.py:128
   self.playwright = await async_playwright().start()
   # Если ошибка до close - утечка процесса
   ```
   
   **Последствия:**
   - Зависшие процессы Chrome
   - Утечка памяти
   - Блокировка портов
   
   **Исправление:**
   ```python
   async def auto_login(...):
       playwright = None
       context = None
       try:
           playwright = await async_playwright().start()
           context = await playwright.chromium.launch_persistent_context(...)
           # ... логика ...
       finally:
           if context:
               await context.close()
           if playwright:
               await playwright.stop()
   ```

2. **Race conditions в многопоточном коде**
   
   ```python
   # app/accounts_tab_extended.py - доступ к self.browsers из разных потоков
   # workers/ - модификация shared state без locks
   ```
   
   **Проблема:** QThread воркеры модифицируют общие словари без синхронизации

3. **None dereference без проверок**
   
   ```python
   # app/main.py:298
   self.accounts.accounts_changed.connect(self.parsing.refresh_profiles)
   # Если refresh_profiles отсутствует - AttributeError
   
   # Частично решено hasattr проверками, но не везде
   ```

4. **Неправильная работа с путями**
   
   ```python
   # workers/auto_login_worker.py:136
   profile_path = profile_path.replace("\\", "/")
   # Работает только на Windows, ломается на Linux/Mac
   ```

5. **Отсутствие валидации proxy формата**
   
   ```python
   # services/proxy_check.py:47-80
   # Сложный парсинг proxy с множеством if/else
   # Может упасть на невалидном формате
   ```

#### 🟡 Важно

6. **SQLite concurrent access issues**
   
   ```python
   # core/db.py - отсутствует WAL mode для SQLite
   # При параллельных записях могут быть SQLITE_BUSY ошибки
   ```

7. **Отсутствие таймаутов**
   
   ```python
   # Многие Playwright операции без timeout
   await page.goto("https://wordstat.yandex.ru")
   # Может висеть вечно при проблемах с сетью
   ```

8. **Encoding issues**
   
   ```python
   # run_keyset.pyw:10
   os.environ['PYTHONIOENCODING'] = 'utf-8'
   # Попытка решить проблемы с кодировкой глобально
   ```

9. **Неправильная работа с asyncio в QThread**
   
   ```python
   # app/accounts_tab_extended.py:108
   loop = asyncio.new_event_loop()
   asyncio.set_event_loop(loop)
   # Создание новых event loops в потоках может привести к багам
   ```

10. **Отсутствие retry логики**
    
    - Парсинг может упасть при временном network error
    - Нет автоматических повторов запросов

### Средний приоритет

11. **Хардкодные селекторы**
    
    ```python
    # workers/auto_login_worker.py:190-195
    search_selectors = [
        'input[name="text"]',
        'input[placeholder*="слово"]',
        # ...
    ]
    # При изменении вёрстки Яндекса сломается
    ```

12. **Import порядок и циркулярные импорты**
    
    - Try/except импорты маскируют проблемы
    - Потенциальные циркулярные зависимости

### Рекомендации

1. **Немедленно:**
   - Добавить context managers для всех Playwright операций
   - Включить WAL mode для SQLite:
     ```python
     @event.listens_for(Engine, "connect")
     def set_sqlite_pragma(dbapi_conn, connection_record):
         cursor = dbapi_conn.cursor()
         cursor.execute("PRAGMA journal_mode=WAL")
         cursor.close()
     ```
   - Добавить таймауты для всех network операций

2. **В ближайшее время:**
   - Внедрить locks для shared state в многопоточном коде
   - Добавить валидацию входных данных (proxy, paths)
   - Реализовать retry механизм с exponential backoff

3. **Техдолг:**
   - Использовать pathlib вместо string операций с путями
   - Вынести селекторы в конфигурацию
   - Добавить type hints везде для раннего обнаружения багов

---

## 5. Производительность

### Узкие места

#### 🟡 Важно

1. **Синхронные операции в UI потоке**
   
   ```python
   # app/main.py:276
   qss.read_text(encoding="utf-8")
   # Чтение файла в главном потоке при старте
   ```

2. **Неэффективные БД запросы**
   
   ```python
   # services/frequency.py:30-47
   for mask in normalized:
       stmt = select(FrequencyResult).where(...)
       existing = session.scalars(stmt).first()
       # N+1 query problem
   ```
   
   **Исправление:**
   ```python
   # Batch select
   existing_masks = session.scalars(
       select(FrequencyResult).where(
           FrequencyResult.mask.in_(normalized),
           FrequencyResult.region == region
       )
   ).all()
   ```

3. **Отсутствие кэширования**
   
   - Конфиги читаются при каждом обращении
   - Нет кэша для proxy списка
   - Селекторы создаются каждый раз

4. **Неоптимальные циклы**
   
   ```python
   # app/accounts_tab_extended.py - множество циклов по таблице
   for i in range(self.table.rowCount()):
       # ... операции с каждой строкой
   ```

#### 🟢 Желательно

5. **Избыточные логи**
   
   - Множество `print()` в production коде
   - Вывод в stdout замедляет GUI

6. **Отсутствие батчинга**
   
   - Парсинг фраз по одной вместо батчами
   - Экспорт данных без буферизации

### Рекомендации

1. **В ближайшее время:**
   - Исправить N+1 queries через batch операции
   - Кэшировать конфиги:
     ```python
     from functools import lru_cache
     
     @lru_cache(maxsize=1)
     def load_config():
         return json.loads(CONFIG_PATH.read_text())
     ```
   - Переместить file I/O в фоновые потоки

2. **Техдолг:**
   - Добавить connection pooling для БД
   - Реализовать lazy loading для больших таблиц
   - Использовать async I/O где возможно

---

## 6. Безопасность

### Уязвимости

#### 🔴 Критично

1. **Hardcoded credentials в тестовых файлах**
   
   ```python
   # services/proxy_check.py:206-211
   test_proxies = [
       "http://Nuj2eh:M6FEcS@213.139.221.13:9620",
       "http://Nuj2eh:M6FEcS@213.139.223.16:9739",
       # ... реальные прокси креды в коде!
   ]
   ```

2. **Plaintext хранение паролей**
   
   - `C:/AI/yandex/configs/accounts.json` - пароли в plain text
   - Нет шифрования credentials
   - Cookies хранятся в БД без защиты

3. **Отсутствие валидации путей (Path Traversal)**
   
   ```python
   # app/accounts_tab_extended.py:87
   profile_path = self.profile_edit.text().strip() or f".profiles/{name}"
   # Пользователь может ввести ../../../etc/passwd
   ```

4. **Небезопасное использование eval/exec**
   
   - Не обнаружено в проверенных файлах ✅

5. **SQL Injection риски**
   
   ✅ **Хорошо:** Используется SQLAlchemy ORM - защита от SQL injection
   
   Но найдены raw SQL запросы:
   ```python
   # core/db.py:73
   conn.execute(text('PRAGMA table_info(accounts)'))
   # Безопасно, т.к. нет user input
   ```

#### 🟡 Важно

6. **Небезопасное логирование sensitive data**
   
   ```python
   # workers/auto_login_worker.py:86
   print(f"[AutoLogin] Прокси: {proxy}")
   # Логирует прокси с паролями в stdout
   ```

7. **Отсутствие rate limiting**
   
   - Нет ограничения частоты запросов к Яндекс
   - Может привести к бану аккаунтов

8. **Небезопасная десериализация**
   
   ```python
   # Pickle не используется ✅
   # JSON используется везде - безопасно ✅
   ```

9. **Прокси credentials в логах**
   
   ```python
   # services/browser_factory.py:86-98
   def _mask_proxy_uri(uri: Optional[str]) -> Optional[str]:
       # Есть функция маскировки, но не всегда используется
   ```

### Рекомендации

1. **Немедленно:**
   - Удалить hardcoded прокси из `proxy_check.py:206`
   - Зашифровать `accounts.json`:
     ```python
     from cryptography.fernet import Fernet
     
     def encrypt_credentials(data: dict) -> bytes:
         key = load_or_generate_key()
         f = Fernet(key)
         return f.encrypt(json.dumps(data).encode())
     ```
   - Валидировать пути:
     ```python
     def safe_profile_path(user_input: str, base_dir: Path) -> Path:
         path = (base_dir / user_input).resolve()
         if not path.is_relative_to(base_dir):
             raise ValueError("Path traversal attempt")
         return path
     ```

2. **В ближайшее время:**
   - Внедрить secrets management (keyring library)
   - Добавить rate limiting для Яндекс запросов
   - Маскировать все credentials в логах
   - Добавить `.gitignore` для `configs/accounts.json`

3. **Техдолг:**
   - Security audit зависимостей (pip-audit)
   - Внедрить SAST инструменты (bandit, semgrep)
   - Code signing для релизов

---

## 7. Зависимости

### Анализ requirements.txt

```txt
PySide6==6.8.0.2        # GUI framework - актуальная версия ✅
playwright==1.48.0       # Браузерная автоматизация - новая ✅
nltk==3.9.1             # NLP для кластеризации - актуальная ✅
sqlalchemy==2.0.36      # ORM - современная 2.x ✅
aiohttp==3.11.10        # Async HTTP - последняя ✅
aiohttp-socks==0.10.1   # SOCKS proxy support
xmindparser>=1.0.8      # Парсинг mind maps
pymorphy2>=0.9.1        # Морфология русского языка
pyperclip>=1.8.2        # Буфер обмена
```

**Проблемы:**

#### 🟡 Важно

1. **Неполный requirements.txt**
   
   Отсутствуют зависимости, которые импортируются:
   - `cryptography` (если будет добавлено шифрование)
   - Development зависимости (pytest, black, ruff)

2. **Отсутствие версионирования**
   
   - `xmindparser>=1.0.8` - может сломаться на major версии
   - Лучше использовать `~=1.0.8` или точные версии

3. **Устаревшие зависимости**
   
   ✅ Все основные зависимости актуальные

### Неиспользуемые импорты

Примеры найдены через анализ:

```python
# app/main.py:8
import importlib  # Используется ✅

# app/accounts_tab_extended.py:21
from itertools import cycle  # Проверить использование

# Множество импортов которые могут не использоваться в backup файлах
```

**Рекомендация:** Запустить `ruff check --select F401` для поиска unused imports

### Циклические импорты

Обнаружены try/except импорты в 6+ файлах:

```python
# services/frequency.py:9-14
try:
    from ..core.db import SessionLocal
except ImportError:
    from core.db import SessionLocal
```

**Проблема:** Указывает на неправильную структуру пакета

### Рекомендации

1. **Немедленно:**
   - Добавить точное версионирование:
     ```txt
     PySide6==6.8.0.2
     playwright~=1.48.0
     ```
   - Создать `requirements-dev.txt`:
     ```txt
     pytest>=7.4.0
     pytest-qt>=4.2.0
     pytest-asyncio>=0.21.0
     ruff>=0.1.0
     black>=23.0.0
     mypy>=1.7.0
     ```

2. **В ближайшее время:**
   - Исправить структуру импортов - убрать try/except
   - Добавить `.python-version` файл
   - Использовать `pyproject.toml` вместо `requirements.txt`

3. **Техдолг:**
   - Настроить Dependabot для автообновлений
   - Регулярный `pip-audit` для уязвимостей
   - Lock-файл зависимостей (poetry.lock или requirements.lock)

---

## 8. Тестирование

### Текущее состояние

**Покрытие: ~0-5%** (критично низкое)

Найдено всего **4 тестовых файла:**

1. `test_batch_dialog.py` (2400 bytes) - тест диалога
2. `test_db_accounts.py` (1765 bytes) - тест БД
3. `test_integration.py` (7455 bytes) - интеграционный тест
4. `scripts/test_semtool_startup.py` - тест запуска

**Отсутствуют тесты для:**

#### 🔴 Критично

- ❌ Парсеры (workers/frequency_runner.py, workers/deep_runner.py)
- ❌ Автологин (5 разных реализаций без тестов!)
- ❌ БД операции (services/frequency.py, services/direct.py)
- ❌ Экспорт данных (services/)
- ❌ Прокси менеджер (services/proxy_manager.py)

#### 🟡 Важно

- ❌ Утилиты (utils/)
- ❌ Модели данных (core/models.py)
- ❌ Валидация входных данных
- ❌ Обработка ошибок

### Тестируемость кода

**Проблемы:**

1. **Tight coupling** - сложно мокировать зависимости
2. **God objects** - классы делают слишком много
3. **Hardcoded dependencies** - нет DI
4. **Global state** - использование глобальных переменных
5. **Side effects** - функции читают файлы напрямую

**Пример нетестируемого кода:**

```python
# workers/auto_login_worker.py:32-33
self.accounts_file = Path("C:/AI/yandex/configs/accounts.json")
self.load_accounts_data()
# Невозможно протестировать без реального файла
```

### Рекомендации

1. **Немедленно:**
   - Написать тесты для критичных модулей:
     ```python
     # tests/test_frequency_service.py
     def test_enqueue_masks():
         result = enqueue_masks(["test mask"], region=225)
         assert result > 0
     
     # tests/test_proxy_check.py
     @pytest.mark.asyncio
     async def test_proxy_validation():
         result = await test_proxy("http://1.2.3.4:8080")
         assert "error" in result
     ```

2. **В ближайшее время:**
   - Настроить pytest + pytest-qt + pytest-asyncio
   - Добавить fixtures для БД и моки для Playwright
   - Цель: довести покрытие до 40-50%
   - CI/CD с автозапуском тестов

3. **Техдолг:**
   - Рефакторить код для тестируемости
   - Внедрить DI контейнер
   - Стремиться к 70%+ покрытию
   - Property-based testing для парсеров (hypothesis)

---

## 9. Документация

### Текущее состояние

**Docstrings: ~30-40% функций**

**Положительные моменты:**

- ✅ Есть README.md (10466 bytes)
- ✅ Множество markdown гайдов в корне
- ✅ Модульные docstrings во многих файлах

**Проблемы:**

#### 🟡 Важно

1. **Отсутствуют docstrings в критичных функциях**
   
   ```python
   # services/frequency.py:19
   def enqueue_masks(masks: Iterable[str], region: int) -> int:
       """Add masks into freq_results, resetting non-ok rows to queued."""
       # Есть docstring ✅
   
   # app/accounts_tab_extended.py:90
   class AutoLoginThread(QThread):
       """Поток для автоматической авторизации аккаунта"""
       # Есть docstring ✅
   
   # Но многие вспомогательные функции без docstrings
   ```

2. **Неконсистентный стиль**
   
   - Смесь русского и английского
   - Разные форматы (Google style / NumPy style)
   - Отсутствие типов в docstrings (используются type hints)

3. **Устаревшая документация**
   
   ```python
   # app/accounts_tab_extended.py:44
   # Старый worker больше не используется, теперь CDP подход
   # Комментарий не удалён - путаница
   ```

4. **Слишком много markdown файлов в корне**
   
   - 35+ .md файлов в корне проекта
   - Неясная иерархия документации
   - Дублирование (README.md, README_NEW.md, README_FULL_PIPELINE.md)

#### 🟢 Желательно

5. **Отсутствие API документации**
   
   - Нет Sphinx/MkDocs генерации
   - Нет документации архитектуры (кроме markdown)
   - Отсутствуют диаграммы (sequence, class diagrams)

6. **Комментарии на русском и английском вперемешку**
   
   ```python
   # Создаем папку профиля если не существует
   Path(profile_path).mkdir(parents=True, exist_ok=True)
   
   # Calculate window position
   pos = self.calculate_window_position(browser_id)
   ```

### README актуальность

`README.md` (10KB) содержит:
- ✅ Описание проекта
- ✅ Установка зависимостей
- ✅ Базовое использование
- ❌ Отсутствуют скриншоты
- ❌ Неполная документация API
- ❌ Нет troubleshooting секции

### Рекомендации

1. **В ближайшее время:**
   - Объединить/удалить дублирующиеся README
   - Переместить документацию в `docs/` директорию
   - Добавить docstrings для всех public функций:
     ```python
     def enqueue_masks(masks: Iterable[str], region: int) -> int:
         """Добавить маски в очередь парсинга частотностей.
         
         Args:
             masks: Список масок для парсинга
             region: ID региона Яндекса (225 = Россия)
         
         Returns:
             Количество добавленных новых масок
         
         Example:
             >>> enqueue_masks(["купить телефон"], region=225)
             1
         """
     ```

2. **Техдолг:**
   - Настроить Sphinx для автогенерации документации
   - Стандартизировать язык (только русский или английский)
   - Добавить архитектурные диаграммы (PlantUML/Mermaid)
   - Contributing guidelines

---

## 10. Специфичные проблемы KeySet

### Playwright/Браузеры

#### 🔴 Критично

1. **Утечки browser/context**
   
   ```python
   # workers/visual_browser_manager.py:160
   self.context = await self.playwright.chromium.launch_persistent_context(...)
   
   # Нет гарантии закрытия:
   # - При exception в середине работы
   # - При прерывании пользователем
   # - При crash приложения
   ```
   
   **Последствия:**
   - Зависшие процессы chrome.exe
   - Утечка памяти (~500MB на браузер)
   - Блокировка user-data-dir

2. **Некорректное позиционирование окон**
   
   ```python
   # workers/visual_browser_manager.py:93-117
   def calculate_window_position(self, browser_id: int):
       # Hardcoded позиции для 1920x1080
       # Не работает на других разрешениях
   ```

3. **Отсутствие cleanup при завершении**
   
   - Нет shutdown hooks для закрытия браузеров
   - При Ctrl+C остаются процессы

#### 🟡 Важно

4. **Хрупкие селекторы**
   
   ```python
   # workers/auto_login_worker.py:190-195
   search_selectors = [
       'input[name="text"]',
       'input[placeholder*="слово"]',
       # ... hardcoded селекторы Яндекса
   ]
   ```
   
   **Проблема:** При изменении вёрстки Яндекса сломается весь парсинг

5. **Отсутствие stealth режима**
   
   - Базовая защита от detection есть
   - Но нет полноценного stealth (fingerprint randomization)

### QThread воркеры

#### 🔴 Критично

1. **Неправильная работа с asyncio в QThread**
   
   ```python
   # app/accounts_tab_extended.py:108-111
   def run(self):
       loop = asyncio.new_event_loop()
       asyncio.set_event_loop(loop)
       loop.run_until_complete(self._run_async())
   ```
   
   **Проблема:** Создание event loop в каждом потоке может привести к:
   - Утечкам памяти
   - Deadlocks при взаимодействии потоков
   - Неправильному завершению

2. **Отсутствие graceful shutdown**
   
   - При закрытии приложения потоки не останавливаются корректно
   - Нет `terminate()` или `wait()` вызовов

#### 🟡 Важно

3. **Race conditions в shared state**
   
   ```python
   # app/accounts_tab_extended.py
   # Доступ к self.browsers из GUI потока и worker потоков без locks
   ```

4. **Сигналы без защиты типов**
   
   ```python
   status_signal = Signal(str)
   # Может быть передан None или другой тип - нет валидации
   ```

### Парсинг Wordstat

#### 🔴 Критично

1. **Отсутствие retry логики**
   
   - При network error парсинг падает
   - Нет автоматических повторов

2. **Хардкодные таймауты**
   
   ```python
   await asyncio.sleep(2)  # Магические числа по всему коду
   ```

3. **Нет обработки капчи**
   
   - Есть поле `captcha_key` в модели
   - Но реальная интеграция с RuCaptcha/CapMonster не полная

#### 🟡 Важно

4. **Отсутствие rate limiting**
   
   - Может привести к бану аккаунтов
   - Нет задержек между запросами

5. **Проблемы с кодировками**
   
   ```python
   # run_keyset.pyw:10
   os.environ['PYTHONIOENCODING'] = 'utf-8'
   # Костыль вместо правильной обработки
   ```

### SQLite

#### 🔴 Критично

1. **Отсутствие WAL mode**
   
   ```python
   # core/db.py - не включен Write-Ahead Logging
   # При concurrent access могут быть SQLITE_BUSY ошибки
   ```

2. **Нет обработки concurrent access**
   
   - Несколько потоков пишут в БД одновременно
   - Отсутствуют retry для SQLITE_BUSY

#### 🟡 Важно

3. **Транзакции не используются везде**
   
   ```python
   # services/frequency.py:29-48
   with SessionLocal() as session:
       for mask in normalized:
           # ... операции
       session.commit()
   # Нет явного BEGIN/COMMIT, полагается на autocommit
   ```

4. **Миграции вручную**
   
   ```python
   # core/db.py:22-80
   def ensure_schema():
       # Ручные ALTER TABLE вместо Alembic
   ```

### Кодировки

#### 🟡 Важно

1. **UTF-8 BOM проблемы**
   
   ```python
   # app/main.py:1
   # -*- coding: utf-8 -*-
   # С BOM маркером в некоторых файлах
   ```

2. **Работа с русскими символами**
   
   - В целом корректная (используется UTF-8)
   - Но есть костыли в нескольких местах

### Рекомендации

1. **Немедленно (Playwright):**
   ```python
   class BrowserContextManager:
       async def __aenter__(self):
           self.playwright = await async_playwright().start()
           self.context = await self.playwright.chromium.launch_persistent_context(...)
           return self.context
       
       async def __aexit__(self, *args):
           await self.context.close()
           await self.playwright.stop()
   ```

2. **Немедленно (SQLite):**
   ```python
   # core/db.py
   from sqlalchemy import event, Engine
   
   @event.listens_for(Engine, "connect")
   def set_sqlite_pragma(dbapi_conn, connection_record):
       cursor = dbapi_conn.cursor()
       cursor.execute("PRAGMA journal_mode=WAL")
       cursor.execute("PRAGMA busy_timeout=5000")
       cursor.close()
   ```

3. **В ближайшее время:**
   - Внедрить retry decorator для парсинга
   - Добавить graceful shutdown для всех QThread
   - Использовать QMutex для shared state
   - Вынести селекторы в YAML конфиг

4. **Техдолг:**
   - Мигрировать на Alembic для миграций БД
   - Внедрить stealth режим для Playwright
   - Добавить мониторинг утечек ресурсов

---

## Приоритизация исправлений

### 🔴 Критично (немедленно)

1. **Исправить все bare except → конкретные исключения**
   - Файлов: 18
   - Риск: Скрытые баги, невозможность debug
   - Время: 4-6 часов

2. **Убрать hardcoded пути `C:/AI/yandex`**
   - Файлов: 24
   - Риск: Приложение не запустится у пользователей
   - Время: 2-3 часа

3. **Исправить утечки Playwright браузеров**
   - Файлов: 10+
   - Риск: Утечка памяти, зависшие процессы
   - Время: 6-8 часов

4. **Удалить hardcoded прокси credentials из кода**
   - Файл: `services/proxy_check.py:206`
   - Риск: Утечка credentials в репозиторий
   - Время: 10 минут

5. **Включить SQLite WAL mode**
   - Файл: `core/db.py`
   - Риск: SQLITE_BUSY ошибки при параллельной работе
   - Время: 30 минут

6. **Добавить context managers для всех ресурсов**
   - Риск: Утечки файлов, соединений, браузеров
   - Время: 4-5 часов

### 🟡 Важно (в ближайшее время)

7. **Удалить backup файлы из репозитория**
   - 6+ файлов по 500-2000 строк
   - Риск: Путаница, раздутый репозиторий
   - Время: 1 час

8. **Объединить 5 реализаций автологина в одну**
   - Файлов: 5
   - Риск: Дублирование багов, сложность поддержки
   - Время: 8-12 часов

9. **Рефакторить `accounts_tab_extended.py` (2014 lines)**
   - Риск: God object, tight coupling
   - Время: 16-20 часов

10. **Исправить N+1 queries в БД**
    - Риск: Производительность
    - Время: 2-3 часа

11. **Добавить валидацию путей (Path Traversal защита)**
    - Риск: Безопасность
    - Время: 2-3 часа

12. **Зашифровать хранение паролей**
    - Риск: Credentials в plaintext
    - Время: 4-6 часов

13. **Написать тесты для критичных модулей**
    - Цель: 40% покрытие
    - Риск: Регрессии при изменениях
    - Время: 20-30 часов

14. **Исправить try/except импорты**
    - Файлов: 6+
    - Риск: Циклические зависимости
    - Время: 2-3 часа

### 🟢 Желательно (техдолг)

15. **Настроить линтеры и pre-commit hooks**
    - ruff, black, mypy
    - Время: 2-3 часа

16. **Добавить retry механизм для парсинга**
    - Время: 4-5 часов

17. **Внедрить централизованное логирование**
    - Заменить print() на logging
    - Время: 6-8 часов

18. **Мигрировать на Alembic для БД**
    - Вместо ручных миграций
    - Время: 4-6 часов

19. **Создать Sphinx документацию**
    - Время: 8-10 часов

20. **Добавить CI/CD pipeline**
    - GitHub Actions с тестами, линтерами
    - Время: 4-5 часов

---

## Общие рекомендации

### 1. Архитектура

- Внедрить dependency injection (например, `dependency-injector`)
- Разделить большие модули на подмодули
- Использовать Protocols для абстракций
- Документировать архитектурные решения (ADR)

### 2. Качество кода

- Установить и настроить:
  - `ruff` для linting (замена flake8 + isort + pyupgrade)
  - `black` для форматирования
  - `mypy` для type checking
- Pre-commit hooks для автопроверки
- Максимальная сложность функции: 10
- Максимальная длина функции: 50 строк
- Максимальный размер файла: 500 строк

### 3. Обработка ошибок

- Никогда не использовать bare `except:`
- Всегда логировать исключения с контекстом
- Использовать custom exceptions для domain errors
- Retry декораторы для network/IO операций
- Circuit breaker для внешних сервисов

### 4. Безопасность

- Немедленно переместить credentials в защищённое хранилище
- Использовать `keyring` library для паролей
- Регулярный security audit:
  ```bash
  pip install pip-audit bandit
  pip-audit
  bandit -r .
  ```
- Code signing для релизов
- HTTPS everywhere

### 5. Тестирование

- Минимум 40% покрытие для production кода
- Обязательные тесты:
  - Unit tests для сервисов
  - Integration tests для БД
  - E2E tests для критичных flows
- Моки для внешних зависимостей (Playwright, network)
- Property-based testing для парсеров

### 6. Документация

- Docstrings для всех public API
- README с quick start и troubleshooting
- CONTRIBUTING.md с guidelines
- CHANGELOG.md для отслеживания изменений
- Архитектурные диаграммы (C4 model)

### 7. DevOps

- CI/CD с автоматическим тестированием
- Dependabot для обновления зависимостей
- Semantic versioning (semver)
- Automated releases с changelog
- Docker образ для development

### 8. Мониторинг

- Structured logging (JSON logs)
- Метрики производительности (parsing speed, success rate)
- Error tracking (Sentry или self-hosted)
- Usage analytics (анонимные)

---

## Метрики кода

### Общие

- **Всего строк кода:** 32,852
- **Файлов Python:** 121
- **Средний размер файла:** 271 строк
- **Комментариев:** ~15-20% (оценка)
- **Docstrings:** ~30-40% функций

### Сложность

- **Средняя цикломатическая сложность:** ~5-8 (оценка)
- **Файлов >500 строк:** 10
- **Функций >100 строк:** ~15-20
- **Bare excepts:** 18+ файлов
- **TODO/FIXME:** 7 файлов

### Качество

- **Тестовое покрытие:** ~0-5%
- **Type hints:** ~60-70% (хорошо!)
- **Hardcoded values:** Множество
- **Дублирование кода:** Высокое (особенно автологин)

### Зависимости

- **Прямых зависимостей:** 9
- **Устаревших:** 0 критичных
- **С уязвимостями:** Требуется проверка через pip-audit

---

## Заключение

KeySet - функциональный проект с хорошей базовой архитектурой (разделение UI/domain/infra), но накопившим значительный технический долг.

**Критичные проблемы:**
1. Hardcoded пути делают приложение непереносимым
2. Утечки ресурсов Playwright приводят к зависаниям
3. Bare excepts скрывают баги и усложняют debug
4. Отсутствие тестов делает рефакторинг опасным
5. Credentials в plaintext - риск безопасности

**Сильные стороны:**
- Современный стек технологий (PySide6, Playwright, SQLAlchemy 2.x)
- Использование type hints
- Хорошая структура директорий
- Активная разработка (35+ документов)

**План действий:**
1. Неделя 1: Исправить критичные проблемы (пункты 1-6)
2. Неделя 2-3: Важные улучшения (пункты 7-14)
3. Месяц 2-3: Техдолг и улучшения (пункты 15-20)

**Оценка трудозатрат:** ~120-150 часов для исправления всех критичных и важных проблем.

При правильном подходе проект может стать maintainable, безопасным и готовым к production использованию.

---

**Дата создания отчёта:** 2024-01-15  
**Автор:** KeySet Codebase Audit  
**Версия:** 1.0
