# 📊 АНАЛИЗ SEMTOOL - ЧТО РАБОТАЕТ И ЧТО ДОРАБОТАТЬ

**Дата:** 12.01.2025 22:05  
**Источник:** yandex\новое\СЕМТОЛ\40 + GitHub репозиторий

---

## ✅ ЧТО УЖЕ РАБОТАЕТ (НЕ ТРОГАТЬ!)

### 1. **Рабочий турбо-парсер (526.3 фраз/мин)**
- **Файл:** `workers/turbo_parser_working.py`
- **Интеграция:** `app/turbo_tab_qt.py`
- **Статус:** ✅ РАБОТАЕТ! Только что протестирован
- **Что делает:** 10 параллельных вкладок, XHR перехват, автоматическое распределение
- **НЕ ТРОГАТЬ:** Этот код рабочий и проверенный

### 2. **База данных SQLite с WAL**
- **Файл:** `core/db.py`
- **Модели:** `core/models.py`
- **Таблицы:**
  - `accounts` - аккаунты Яндекс
  - `tasks` - очередь задач
  - `freq_results` - результаты частотности
- **Статус:** ✅ РАБОТАЕТ
- **НЕ ТРОГАТЬ:** Структура БД правильная

### 3. **GUI на PySide6**
- **Файл:** `app/main.py`
- **Вкладки:**
  - Full Pipeline
  - Турбо Парсер (✅ рабочий!)
  - Аккаунты
  - Задачи
- **Статус:** ✅ РАБОТАЕТ
- **НЕ ТРОГАТЬ:** Основная структура окна

### 4. **Управление аккаунтами**
- **Файл:** `services/accounts.py`
- **Функции:** CRUD, статусы (ok/cooldown/captcha/banned)
- **Статус:** ✅ РАБОТАЕТ
- **Что есть:**
  - Добавление/удаление/редактирование
  - Статусы и cooldown
  - Привязка к задачам
- **НЕ ТРОГАТЬ:** Логика работает

### 5. **Автологин**
- **Файл:** `workers/yandex_smart_login.py`
- **Интеграция:** `app/accounts_tab_extended.py`
- **Статус:** ✅ РАБОТАЕТ
- **Что делает:** CDP автологин с сохранением storage_state
- **НЕ ТРОГАТЬ:** Логин работает

### 6. **Full Pipeline**
- **Файл:** `app/full_pipeline_tab.py`
- **Этапы:** Wordstat → Direct → Clustering → Export
- **Статус:** ✅ РАБОТАЕТ
- **НЕ ТРОГАТЬ:** Пайплайн работает

---

## ❌ ЧТО НУЖНО ДОРАБОТАТЬ (БЕЗ СЛОМА СУЩЕСТВУЮЩЕГО)

### 1. ❌ Проверка прокси
**Что нужно:**
- Сервис `services/proxy_check.py`
- Кнопка "Тест прокси" в вкладке Аккаунты
- Показ IP и статуса (OK/FAIL)

**Как добавить:**
```python
# services/proxy_check.py (НОВЫЙ ФАЙЛ)
import httpx
import asyncio

async def test_proxy(proxy_url: str, timeout=10):
    """Проверка прокси через https://yandex.ru/internet"""
    try:
        async with httpx.AsyncClient(proxies=proxy_url, timeout=timeout) as client:
            r = await client.get("https://yandex.ru/internet")
            r.raise_for_status()
            ip = r.headers.get("x-client-ip", "unknown")
            return {"ok": True, "ip": ip, "latency_ms": int(r.elapsed.total_seconds() * 1000)}
    except Exception as e:
        return {"ok": False, "error": str(e)}
```

**Изменения в GUI:**
- В `app/accounts_tab_extended.py` добавить кнопку "Тест прокси"
- Вызывать `test_proxy(account.proxy)`
- Показывать результат в диалоге

### 2. ❌ Интеграция капчи (RuCaptcha/CapMonster)
**Что нужно:**
- Поле `captcha_key` в модели Account
- Сервис `services/captcha.py`
- Кнопка "Проверить баланс капчи"

**Добавить в models.py:**
```python
class Account(Base):
    # ... существующие поля
    captcha_key: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    captcha_balance: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
```

**Новый файл:**
```python
# services/captcha.py (НОВЫЙ ФАЙЛ)
import httpx
import asyncio

class RuCaptchaClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://rucaptcha.com"
    
    async def get_balance(self):
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.base_url}/res.php", params={
                "key": self.api_key,
                "action": "getbalance"
            })
            return float(r.text)
    
    async def solve_image(self, image_base64: str):
        # Реализация решения капчи
        pass
```

### 3. ❌ Правая панель с ключами (как в Key Collector)
**Что нужно:**
- Новый файл `app/keys_panel.py`
- Интеграция через QSplitter в main.py
- Колонки: Фраза | WS | "WS" | !WS | Статус | Группа

**Новый файл:**
```python
# app/keys_panel.py (НОВЫЙ ФАЙЛ)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, 
    QTableWidgetItem, QLineEdit, QLabel, QHeaderView
)

class KeysPanel(QWidget):
    """Правая панель с ключами во всю высоту"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(400)
        
        layout = QVBoxLayout(self)
        
        # Заголовок
        layout.addWidget(QLabel("Ключевые фразы"))
        
        # Поиск/фильтр
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по фразам...")
        layout.addWidget(self.search)
        
        # Таблица
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Фраза", "WS", '"WS"', "!WS", "Статус", "Группа"
        ])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table, 1)
        
        # Подключение фильтра
        self.search.textChanged.connect(self._filter_rows)
    
    def load_data(self, results: list[dict]):
        """Загрузка данных из БД"""
        self.table.setRowCount(len(results))
        for i, row in enumerate(results):
            self.table.setItem(i, 0, QTableWidgetItem(row["phrase"]))
            self.table.setItem(i, 1, QTableWidgetItem(str(row.get("ws", 0))))
            self.table.setItem(i, 2, QTableWidgetItem(str(row.get("qws", 0))))
            self.table.setItem(i, 3, QTableWidgetItem(str(row.get("bws", 0))))
            self.table.setItem(i, 4, QTableWidgetItem(row.get("status", "")))
            self.table.setItem(i, 5, QTableWidgetItem(row.get("group", "")))
    
    def _filter_rows(self, text):
        """Фильтрация строк по тексту"""
        for i in range(self.table.rowCount()):
            phrase = self.table.item(i, 0).text().lower()
            self.table.setRowHidden(i, text.lower() not in phrase)
```

**Интеграция в main.py:**
```python
# В app/main.py добавить:
from .keys_panel import KeysPanel

class MainWindow(QMainWindow):
    def __init__(self):
        # ... существующий код
        
        # Создать QSplitter вместо центрального виджета
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.tabs)  # Левая часть - вкладки
        
        # Правая панель с ключами
        self.keys_panel = KeysPanel()
        splitter.addWidget(self.keys_panel)
        
        # Пропорции: 70% слева, 30% справа
        splitter.setSizes([700, 300])
        
        self.setCentralWidget(splitter)
```

### 4. ❌ Колонки WS / "WS" / !WS (три типа частотности)
**Что нужно:**
- Добавить поле `freq_quotes` в FrequencyResult
- Обновить парсер для получения всех 3 типов
- Показывать в правой панели

**Изменения в models.py:**
```python
class FrequencyResult(Base):
    # ... существующие поля
    freq_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)      # WS
    freq_quotes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)     # "WS"
    freq_exact: Mapped[int] = mapped_column(Integer, nullable=False, default=0)      # !WS
```

**Миграция БД:**
```python
# Добавить ALTER TABLE в core/db.py при инициализации
with engine.connect() as conn:
    try:
        conn.execute(text("ALTER TABLE freq_results ADD COLUMN freq_quotes INTEGER DEFAULT 0"))
        conn.commit()
    except:
        pass  # Колонка уже существует
```

### 5. ❌ Удобные кнопки в вкладке Аккаунты
**Что добавить:**
- ✅ "Добавить" (уже есть)
- ✅ "Изменить" (уже есть)
- ✅ "Удалить" (уже есть)
- ❌ "Тест прокси" (ДОБАВИТЬ)
- ✅ "Войти" (уже есть)
- ✅ "Войти во все" (уже есть)
- ❌ "Проверить баланс капчи" (ДОБАВИТЬ)

### 6. ❌ Группировка (улучшить отображение)
**Что есть:**
- Кластеризация работает (NLTK)
- Результаты сохраняются

**Что добавить:**
- Колонка "Группа" в правой панели
- Фильтр по группам
- Выделение цветом по группам
- Кнопка "Объединить группы"
- Кнопка "Разбить группу"

### 7. ❌ Минусовка (кросс-минусовка)
**Что нужно:**
- Новый файл `solvers/minus_words.py`
- Кнопка "Кросс-минусовка" в Full Pipeline
- Экспорт минус-слов в отдельный файл

**Новый файл:**
```python
# solvers/minus_words.py (НОВЫЙ ФАЙЛ)
from collections import Counter

def extract_minus_words(groups: dict[int, list[str]], threshold=0.5):
    """
    Кросс-минусовка между группами
    Находит слова которые встречаются в одной группе но не в других
    """
    minus_words = {}
    
    for group_id, phrases in groups.items():
        # Все слова в группе
        words = []
        for phrase in phrases:
            words.extend(phrase.lower().split())
        
        # Подсчёт частоты слов
        word_freq = Counter(words)
        
        # Слова из других групп
        other_words = set()
        for other_id, other_phrases in groups.items():
            if other_id != group_id:
                for phrase in other_phrases:
                    other_words.update(phrase.lower().split())
        
        # Минус-слова: встречаются в других группах но не в этой
        minus = [word for word in other_words if word not in word_freq]
        minus_words[group_id] = minus
    
    return minus_words
```

---

## 🎯 ПЛАН ДЕЙСТВИЙ (ПОЭТАПНО)

### Этап 1: Проверка прокси (1 час)
1. Создать `services/proxy_check.py`
2. Добавить кнопку в `app/accounts_tab_extended.py`
3. Протестировать на реальных прокси

### Этап 2: Капча (2 часа)
1. Добавить поля в `core/models.py`
2. Создать миграцию
3. Создать `services/captcha.py`
4. Добавить кнопки в GUI
5. Протестировать баланс

### Этап 3: Правая панель с ключами (3 часа)
1. Создать `app/keys_panel.py`
2. Интегрировать в `app/main.py` через QSplitter
3. Подключить загрузку данных из БД
4. Добавить фильтры и поиск
5. Протестировать на реальных данных

### Этап 4: Три типа частотности (2 часа)
1. Добавить `freq_quotes` в модель
2. Создать миграцию
3. Обновить парсер для получения всех 3 типов
4. Обновить правую панель для отображения
5. Протестировать

### Этап 5: Группировка и минусовка (4 часа)
1. Создать `solvers/minus_words.py`
2. Добавить колонку "Группа" в правую панель
3. Добавить цветовое выделение групп
4. Кнопка "Кросс-минусовка"
5. Экспорт минус-слов
6. Протестировать на реальных группах

**ИТОГО:** ~12 часов работы

---

## ⚠️ КРИТИЧЕСКИ ВАЖНО

### НЕ ТРОГАТЬ (работает!)
- ✅ `workers/turbo_parser_working.py` - рабочий парсер
- ✅ `app/turbo_tab_qt.py` - интеграция парсера
- ✅ `core/db.py` - база данных
- ✅ `core/models.py` - модели (только добавлять поля!)
- ✅ `services/accounts.py` - управление аккаунтами
- ✅ `workers/yandex_smart_login.py` - автологин
- ✅ `app/full_pipeline_tab.py` - Full Pipeline

### ТОЛЬКО ДОБАВЛЯТЬ (не ломать!)
- ➕ Новые файлы в `services/`
- ➕ Новые файлы в `solvers/`
- ➕ Новые файлы в `app/`
- ➕ Новые поля в модели Account
- ➕ Новые кнопки в GUI
- ➕ Новые колонки в таблицы

### ТЕСТИРОВАТЬ ПОСЛЕ КАЖДОГО ЭТАПА
1. Запустить KeySet
2. Проверить что все вкладки работают
3. Проверить что турбо-парсер работает
4. Проверить что новый функционал работает
5. Закоммитить и запушить в GitHub

---

## 📋 ЧЕК-ЛИСТ ДЛЯ КАЖДОГО ЭТАПА

Перед коммитом проверь:
- [ ] KeySet запускается без ошибок
- [ ] Все существующие вкладки работают
- [ ] Турбо-парсер работает (526.3 фраз/мин)
- [ ] Новый функционал работает
- [ ] Нет ошибок в логах
- [ ] БД не сломана
- [ ] Можно добавить/удалить аккаунт
- [ ] Автологин работает
- [ ] Full Pipeline работает

---

**Следующий шаг:** Начать с Этапа 1 (Проверка прокси)
