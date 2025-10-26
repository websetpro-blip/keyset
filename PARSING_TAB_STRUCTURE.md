# СТРУКТУРА ВКЛАДКИ ПАРСИНГА (parsing_tab.py)

**Файл:** `c:\AI\yandex\keyset\app\tabs\parsing_tab.py`
**Всего строк:** ~1060
**Классов:** 3
**Методов:** 35+
**Стилей:** 3

---

## 📦 КЛАССЫ

### 1. SingleParsingTask
**Строки:** [102-164](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L102-L164)
**Назначение:** Задача парсинга для одного профиля

**Методы:**
- [`__init__(profile_email, profile_path, proxy, phrases, session_id, cookie_count)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L105-L123) - Инициализация задачи
- [`log(message, level)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L125-L135) - Логирование с префиксом профиля
- [`run()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L137-L164) - Асинхронный запуск парсинга (вызывает turbo_parser_10tabs)

**Атрибуты:**
- `profile_email` - email профиля
- `profile_path` - путь к профилю Chrome
- `proxy` - прокси для профиля
- `phrases` - список фраз для парсинга
- `session_id` - ID сессии
- `cookie_count` - количество кук
- `results` - результаты парсинга (dict)

---

### 2. MultiParsingWorker (QThread)
**Строки:** [167-318](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L167-L318)
**Назначение:** Многопоточный воркер для запуска парсинга на всех профилях одновременно

**Сигналы (Qt Signals):**
- `log_signal(str)` - Общий лог
- `profile_log_signal(str, str)` - Лог конкретного профиля (email, message)
- `progress_signal(dict)` - Прогресс всех профилей
- `task_completed(str, dict)` - Профиль завершил работу (email, results)
- `all_finished(list)` - Все задачи завершены

**Методы:**
- [`__init__(phrases, modes, geo_ids, selected_profiles, parent)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L177-L223) - Инициализация воркера, создание задач для каждого профиля
- [`stop()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L225-L226) - Остановка парсинга
- [`_write_log(message)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L228-L237) - Запись в лог файл и отправка в GUI
- [`run()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L239-L276) - Основной метод запуска всех парсеров
- [`_run_all_parsers()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L278-L295) - Асинхронный запуск всех парсеров
- [`_run_single_parser(task)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L297-L318) - Запуск одного парсера с обработкой событий

**Атрибуты:**
- `phrases` - список фраз
- `modes` - режимы парсинга (ws, qws, bws)
- `geo_ids` - регионы
- `selected_profiles` - выбранные профили
- `tasks` - список задач SingleParsingTask
- `session_id` - ID сессии
- `log_file` - путь к лог файлу

**Важно:** В `__init__` (строки 192-218) происходит **распределение фраз между профилями**:
```python
# Распределяем фразы поровну между профилями
num_profiles = len(selected_profiles)
phrases_per_profile = len(phrases) // num_profiles
remainder = len(phrases) % num_profiles

batches = []
start_idx = 0

for i in range(num_profiles):
    end_idx = start_idx + phrases_per_profile + (1 if i >= num_profiles - remainder else 0)
    batch = phrases[start_idx:end_idx]
    batches.append(batch)
    start_idx = end_idx
```

---

### 3. ParsingTab (QWidget) - ГЛАВНЫЙ КЛАСС
**Строки:** [321-1060](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L321-L1060)
**Назначение:** Главная вкладка парсинга с UI и логикой

#### 🎨 UI МЕТОДЫ

##### Инициализация
- [`__init__(parent, keys_panel)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L324-L331) - Конструктор вкладки

##### Построение UI (Key Collector Style)
- [`_init_ui()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L333-L533) - **ГЛАВНЫЙ МЕТОД UI** - строит всю структуру интерфейса

**Структура _init_ui():**

1. **TOP PANEL** (строки 337-368) - Кнопки функций вверху
   - ➕ Добавить
   - ❌ Удалить
   - 📊 Частотка
   - 📦 Пакет
   - 💰 Прогноз
   - 🗑️ Очистить
   - 💾 Экспорт
   - 🟢 Статус

2. **ЛЕВАЯ КОЛОНКА** (строки 375-422) - Управление выбором + Настройки (5-10%)
   - Кнопки управления выбором (строки 382-390)
   - Настройки парсинга (строки 392-420):
     - Профили (QListWidget, 100px)
     - Режимы (WS, "WS", !WS)
     - Регионы (GeoTree, 80px)

3. **ЦЕНТРАЛЬНАЯ КОЛОНКА** (строки 424-476) - Основная таблица (80%)
   - Кнопки парсинга (строки 431-446):
     - 🚀 Запустить
     - ⏹ Стоп
     - Прогресс-бар
   - Главная таблица (строки 449-467):
     - 4 колонки: № (40px) | **Фраза (500px)** | Частотность (120px) | Статус (80px)
     - MultiSelection режим
     - SelectRows поведение
   - Поле ввода фраз (строки 469-476):
     - 80px высота
     - Placeholder

4. **ПРАВАЯ КОЛОНКА** (строки 478-497) - Группы фраз (10%)
   - Список групп
   - Кнопка "➕ Новая"

5. **SPLITTER** (строки 499-507) - Объединение 3 колонок
   - Пропорции: [100, 800, 120]

6. **BOTTOM JOURNAL** (строки 509-533) - Журнал логов
   - Терминальный стиль (черный фон, зеленый текст)
   - 150px высота
   - Кнопка "Очистить журнал"

##### Подключение сигналов
- [`_wire_signals()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L535-L562) - Подключение всех обработчиков событий

---

#### 🔧 ФУНКЦИИ УПРАВЛЕНИЯ ПРОФИЛЯМИ

- [`_refresh_profiles()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L564-L593) - Обновить список профилей из БД
- [`_select_all_profiles()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L595-L598) - Выбрать все профили
- [`_deselect_all_profiles()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L600-L603) - Снять выбор со всех профилей
- [`_get_selected_profiles()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L605-L612) - Получить список выбранных профилей

---

#### 💾 ФУНКЦИИ СОХРАНЕНИЯ/ЗАГРУЗКИ СОСТОЯНИЯ

- [`save_session_state(partial_results)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L614-L641) - Сохранить состояние сессии в JSON
- [`load_session_state()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L643-L652) - Загрузить состояние сессии из JSON
- [`_restore_session_state()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L654-L680) - Восстановить UI из сохраненного состояния

---

#### 📊 ФУНКЦИИ ОБРАБОТКИ ДАННЫХ

- [`_coerce_freq(value)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L682-L697) - Статический метод преобразования частотности в int
- [`_aggregate_by_phrase(rows)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L699-L709) - Агрегация результатов по фразам (суммирование ws, qws, bws)
- [`_populate_results(rows)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L711-L767) - **ОБНОВЛЕНИЕ ТАБЛИЦЫ** - заполнение результатов парсинга

**Логика _populate_results():**
1. Создает словарь результатов по фразам
2. Проходит по существующим строкам таблицы
3. Обновляет колонки "Частотность" и "Статус"
4. Возвращает нормализованные строки

---

#### 🎛️ ФУНКЦИИ УПРАВЛЕНИЯ СТРОКАМИ (Левая панель)

**Раздел:** [Строки 769-791](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L769-L791)

- [`_select_all_rows()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L773-L776) - Выбрать все строки таблицы (`selectAll()`)
- [`_deselect_all_rows()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L778-L781) - Снять выбор (`clearSelection()`)
- [`_invert_selection()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L783-L791) - Инвертировать выбор строк

---

#### 🔨 ФУНКЦИИ TOP PANEL (Основные действия)

**Раздел:** [Строки 793-860](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L793-L860)

- [`_on_add_phrases()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L797-L824) - **➕ Добавить фразы** из поля ввода в таблицу
  - Читает текст из `phrases_edit`
  - Добавляет строки в таблицу с номерами
  - Очищает поле ввода

- [`_on_delete_phrases()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L826-L842) - **❌ Удалить** выбранные фразы
  - Получает выбранные строки
  - Удаляет в обратном порядке
  - Перенумеровывает оставшиеся

- [`_on_clear_results()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L844-L847) - **🗑️ Очистить** всю таблицу

- [`_on_batch_parsing()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L849-L851) - **📦 Пакетный парсинг** (заглушка)

- [`_on_forecast()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L853-L855) - **💰 Прогноз бюджета** (заглушка)

- [`_on_new_group()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L857-L859) - **➕ Создать группу** (заглушка)

---

#### 🚀 ФУНКЦИИ ПАРСИНГА

**Раздел:** [Строки 861-996](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L861-L996)

- [`_on_run_clicked()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L865-L946) - **ГЛАВНАЯ ФУНКЦИЯ ПАРСИНГА** 📊🚀

  **Алгоритм:**
  1. Получает фразы из таблицы (колонка 1)
  2. Получает выбранные профили
  3. Проверяет количество кук в профилях
  4. Создает `MultiParsingWorker`
  5. Подключает сигналы
  6. Запускает воркер

  **Важно:** Фразы берутся из **таблицы**, а не из текстового поля!

- [`_on_stop_clicked()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L948-L956) - ⏹ Остановка парсинга

---

#### 📝 ФУНКЦИИ ЛОГИРОВАНИЯ И ОБРАТНОЙ СВЯЗИ

- [`_append_log(message)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L958-L963) - Добавить сообщение в журнал с автопрокруткой

- [`_on_profile_log(profile_email, message)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L965-L968) - Обработка лога от конкретного профиля

- [`_on_progress_update(progress_data)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L970-L975) - Обновление прогресс-бара

- [`_on_task_completed(profile_email, results)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L977-L979) - Профиль завершил работу

- [`_on_all_finished(all_results)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L981-L995) - **Все задачи завершены**
  - Останавливает воркер
  - Обновляет UI
  - Заполняет таблицу результатами
  - Сохраняет состояние

---

#### 💾 ФУНКЦИЯ ЭКСПОРТА

- [`_on_export_clicked()`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L997-L1060) - **💾 Экспорт в CSV**

  **Формат CSV:**
  - 2 колонки: Фраза | Частотность
  - TAB разделитель (`delimiter='\t'`)
  - UTF-8-sig кодировка
  - Сортировка по убыванию частотности
  - QUOTE_MINIMAL

---

## 🎨 СТИЛИ (StyleSheets)

### 1. Статус Label
**Строка:** [365](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L365)
```python
self.status_label.setStyleSheet("QLabel { font-weight: bold; padding: 5px; }")
```

### 2. Кнопка "Запустить парсинг"
**Строка:** [434](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L434)
```python
self.btn_run.setStyleSheet("QPushButton { font-weight: bold; padding: 8px; }")
```

### 3. Журнал логов (Терминальный стиль)
**Строки:** [518-525](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L518-L525)
```python
self.log_text.setStyleSheet("""
    QTextEdit {
        background-color: #1e1e1e;
        color: #00ff00;
        font-family: 'Consolas', 'Monaco', monospace;
        font-size: 9pt;
    }
""")
```

---

## 🔗 ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ

### Вне классов:

- [`_probe_profile_cookies(profile_info)`](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L45-L100) - Проверка количества кук в профиле
  - Читает cookies из SQLite базы Chrome
  - Расшифровывает DPAPI encrypted cookies
  - Возвращает количество кук или ошибку

---

## 📋 КОНСТАНТЫ И ИМПОРТЫ

**Строки:** [1-43](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L1-L43)

### Импорты:
- PySide6 (Qt)
- asyncio
- pathlib
- json
- csv
- datetime
- sqlite3
- base64

### Важные импорты:
- `GeoTree` - виджет выбора регионов
- `KeysPanel` - панель ключевых слов
- `list_accounts` - получение списка аккаунтов из БД
- `turbo_parser_10tabs` - функция парсинга

### Константы:
- `BASE_DIR` - базовая директория проекта
- `STATE_FILE` - путь к файлу состояния сессии

---

## 🗂️ СТРУКТУРА UI КОМПОНЕНТОВ

### TOP PANEL (Кнопки):
- `self.btn_add` - ➕ Добавить
- `self.btn_delete` - ❌ Удалить
- `self.btn_ws` - 📊 Частотка
- `self.btn_batch` - 📦 Пакет
- `self.btn_forecast` - 💰 Прогноз
- `self.btn_clear` - 🗑️ Очистить
- `self.btn_export` - 💾 Экспорт
- `self.status_label` - Статус

### ЛЕВАЯ КОЛОНКА:
- `self.btn_select_all_rows` - ✓ Выбрать все
- `self.btn_deselect_all_rows` - ✗ Снять выбор
- `self.btn_invert_selection` - 🔄 Инвертировать
- `self.profiles_list` - Список профилей (QListWidget)
- `self.btn_refresh_profiles` - Обновить
- `self.chk_ws` - Чекбокс WS
- `self.chk_qws` - Чекбокс "WS"
- `self.chk_bws` - Чекбокс !WS
- `self.geo_tree` - Дерево регионов (GeoTree)

### ЦЕНТРАЛЬНАЯ КОЛОНКА:
- `self.btn_run` - 🚀 Запустить парсинг
- `self.btn_stop` - ⏹ Стоп
- `self.progress` - Прогресс-бар (QProgressBar)
- `self.table` - Главная таблица (QTableWidget, 4 колонки)
- `self.phrases_edit` - Поле ввода фраз (QTextEdit)

### ПРАВАЯ КОЛОНКА:
- `self.groups_list` - Список групп (QListWidget)
- `self.btn_new_group` - ➕ Новая группа

### BOTTOM:
- `self.log_text` - Журнал логов (QTextEdit)
- `self.btn_clear_log` - Очистить журнал

---

## 🔄 ПОТОК ДАННЫХ (Data Flow)

### 1. Добавление фраз:
```
Пользователь вводит текст в phrases_edit
    ↓
Нажимает "➕ Добавить" (_on_add_phrases)
    ↓
Фразы добавляются в таблицу (table) построчно
```

### 2. Запуск парсинга:
```
Пользователь нажимает "📊 Частотка" или "🚀 Запустить"
    ↓
_on_run_clicked() получает фразы из таблицы
    ↓
Создается MultiParsingWorker с выбранными профилями
    ↓
Фразы распределяются между профилями (__init__ MultiParsingWorker)
    ↓
Каждый профиль получает SingleParsingTask со своим батчем фраз
    ↓
Запускается run() → _run_all_parsers() → asyncio.gather всех задач
    ↓
Каждая задача вызывает turbo_parser_10tabs()
    ↓
Результаты возвращаются через сигналы:
    - task_completed (каждый профиль)
    - all_finished (все профили)
    ↓
_on_all_finished() → _populate_results() → обновление таблицы
```

### 3. Экспорт:
```
Пользователь нажимает "💾 Экспорт"
    ↓
_on_export_clicked() читает таблицу
    ↓
Создает список {phrase, frequency}
    ↓
Сортирует по убыванию
    ↓
Сохраняет в CSV (TAB разделитель, UTF-8-sig)
```

---

## 📊 ТАБЛИЦА РЕЗУЛЬТАТОВ (self.table)

### Колонки:
| Индекс | Название | Ширина | Описание |
|--------|----------|--------|----------|
| 0 | № | 40px | Номер строки (автонумерация) |
| 1 | **Фраза** | **500px** | **ОСНОВНАЯ колонка** - ключевая фраза |
| 2 | Частотность | 120px | WS значение (заполняется при парсинге) |
| 3 | Статус | 80px | ✓ (успех) или ⏱ (таймаут) |

### Настройки:
- `SelectionBehavior`: `SelectRows` - выбор целой строки
- `SelectionMode`: `MultiSelection` - множественный выбор
- `MinimumHeight`: 400px

---

## 🎯 КЛЮЧЕВЫЕ МОМЕНТЫ

### ⚠️ Важные изменения от старой версии:

1. **Фразы из таблицы, а не из текстового поля:**
   ```python
   # _on_run_clicked() строка 867-873
   for row in range(self.table.rowCount()):
       phrase_item = self.table.item(row, 1)
       if phrase_item:
           phrases.append(phrase_item.text().strip())
   ```

2. **Распределение фраз между профилями:**
   ```python
   # MultiParsingWorker.__init__() строки 192-205
   # Каждый профиль получает СВОЙ батч фраз
   ```

3. **Результаты обновляют существующие строки:**
   ```python
   # _populate_results() строки 726-747
   # НЕ создает новые строки, а обновляет колонки 2 и 3
   ```

4. **CSV с TAB разделителем:**
   ```python
   # _on_export_clicked() строка 1034
   writer = csv.writer(f, delimiter='\t', quoting=csv.QUOTE_MINIMAL)
   ```

---

## 📁 СВЯЗАННЫЕ ФАЙЛЫ

- `turbo_parser_improved.py` - парсер с 10 вкладками
- `services/multiparser_manager.py` - менеджер множественного парсинга
- `widgets/geo_tree.py` - виджет выбора регионов
- `keys_panel.py` - панель группировки ключевых слов
- `services/accounts.py` - работа с аккаунтами

---

**Создано:** 26.10.2025
**Версия UI:** Key Collector style
**Всего функций:** 35+
**Кодировка:** UTF-8
