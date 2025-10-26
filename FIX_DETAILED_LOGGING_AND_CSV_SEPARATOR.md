# ДОБАВЛЕНО: ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ И TAB РАЗДЕЛИТЕЛЬ В CSV

**Дата:** 26.10.2025
**Статус:** ✅ ВЫПОЛНЕНО

---

## 🎯 ЗАДАЧИ

### Проблема 1: Некоторые фразы показывают частотность 0

**Причина:** Недостаточно логирования для выявления на каком этапе теряются данные

**Решение:** Добавлено детальное JSONL логирование на каждом этапе парсинга

### Проблема 2: CSV экспорт с запятой может ломаться

**Причина:** Запятые в фразах могут нарушать структуру CSV

**Решение:** Использован TAB (`\t`) в качестве разделителя

---

## ✅ ЗАДАЧА 1: ДЕТАЛЬНОЕ ЛОГИРОВАНИЕ ПАРСИНГА

### Файл: `turbo_parser_improved.py`

#### 1. Добавлена функция `log_parsing_debug()` (строки 76-97)

**Файл:** [turbo_parser_improved.py:76-97](c:\AI\yandex\keyset\turbo_parser_improved.py#L76-L97)

```python
def log_parsing_debug(entry: Dict[str, Any]) -> None:
    """
    Сохраняет детальные логи парсинга в JSONL файл для отладки.

    Каждая запись содержит:
      - timestamp: ISO формат времени
      - account: имя аккаунта
      - tab: номер вкладки
      - phrase: фраза
      - status: статус этапа
      - message: описание
      - ws: частотность (если получена)
      - elapsed: время выполнения этапа в секундах
      - error: текст ошибки (если есть)
    """
    debug_log_file = LOG_DIR / 'parsing_debug.jsonl'

    try:
        with open(debug_log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as e:
        logging.error(f"Ошибка записи debug лога: {e}")
```

**Результат:** Все события сохраняются в `keyset/logs/parsing_debug.jsonl`

#### 2. Интегрировано логирование в функцию `parse_tab()` (строки 547-749)

**Этапы логирования:**

1. **started** - начало парсинга фразы
2. **input_found** - поле ввода найдено (с указанием селектора и времени)
3. **phrase_typed** - фраза введена в поле
4. **enter_pressed** - Enter нажат, запрос отправлен
5. **api_waiting** - ожидание API ответа (с таймаутом)
6. **success** - частотность получена ✅
7. **api_timeout** - таймаут API (не получен ответ) ⚠️
8. **error_no_input** - поле ввода не найдено ❌
9. **critical_error** - критическая ошибка при парсинге ❌

**Ключевые изменения:**

```python
# ЛОГ: Начало парсинга
log_entry = {
    'timestamp': datetime.now().isoformat(),
    'account': self.account_name,
    'tab': tab_index + 1,
    'phrase': phrase,
    'status': 'started',
    'message': f'[TAB {tab_index + 1}] Начало парсинга: "{phrase}"'
}
log_parsing_debug(log_entry)

# ... поиск поля ввода ...

# ЛОГ: Поле найдено
log_entry.update({
    'timestamp': datetime.now().isoformat(),
    'status': 'input_found',
    'message': f'Поле ввода найдено: {selector}',
    'selector': selector,
    'elapsed': round(elapsed_input, 3)
})
log_parsing_debug(log_entry)

# ... ввод фразы и нажатие Enter ...

# ЛОГ: Ожидание API
t_api_start = time.time()
log_entry.update({
    'timestamp': datetime.now().isoformat(),
    'status': 'api_waiting',
    'message': f'Ожидание API ответа (timeout={timeout:.1f}s)'
})
log_parsing_debug(log_entry)

# ... ожидание ответа ...

if response_received:
    # ЛОГ: Успех
    log_entry.update({
        'timestamp': datetime.now().isoformat(),
        'status': 'success',
        'message': f'Частотность получена: {value}',
        'ws': value,
        'elapsed': round(elapsed_api, 3),
        'api_received': True
    })
    log_parsing_debug(log_entry)
else:
    # ЛОГ: Таймаут
    log_entry.update({
        'timestamp': datetime.now().isoformat(),
        'status': 'api_timeout',
        'message': f'API таймаут после {elapsed_api:.2f}s ожидания',
        'ws': 0,
        'elapsed': round(elapsed_api, 3),
        'api_received': False
    })
    log_parsing_debug(log_entry)
```

#### 3. Добавлено логирование в `handle_response()` (строки 523-535)

**Файл:** [turbo_parser_improved.py:523-535](c:\AI\yandex\keyset\turbo_parser_improved.py#L523-L535)

Теперь каждый API ответ логируется отдельной записью:

```python
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
```

### Пример лога (parsing_debug.jsonl):

```json
{"timestamp": "2025-10-26T03:15:22.123456", "account": "dsmismirnov", "tab": 1, "phrase": "ремонт квартиры", "status": "started", "message": "[TAB 1] Начало парсинга: \"ремонт квартиры\""}
{"timestamp": "2025-10-26T03:15:22.234567", "account": "dsmismirnov", "tab": 1, "phrase": "ремонт квартиры", "status": "input_found", "message": "Поле ввода найдено: input[name='text']", "selector": "input[name='text']", "elapsed": 0.111}
{"timestamp": "2025-10-26T03:15:22.456789", "account": "dsmismirnov", "tab": 1, "phrase": "ремонт квартиры", "status": "phrase_typed", "message": "Фраза введена в поле", "elapsed": 0.222}
{"timestamp": "2025-10-26T03:15:22.567890", "account": "dsmismirnov", "tab": 1, "phrase": "ремонт квартиры", "status": "enter_pressed", "message": "Enter нажат, запрос отправлен", "elapsed": 0.111}
{"timestamp": "2025-10-26T03:15:22.789012", "account": "dsmismirnov", "tab": 1, "phrase": "ремонт квартиры", "status": "api_waiting", "message": "Ожидание API ответа (timeout=10.0s)"}
{"timestamp": "2025-10-26T03:15:23.012345", "account": "dsmismirnov", "tab": "API", "phrase": "ремонт квартиры", "status": "api_response_received", "message": "API ответ получен: 27892800", "ws": 27892800, "api_url": "https://wordstat.yandex.ru/api/v2/search", "api_status": 200}
{"timestamp": "2025-10-26T03:15:23.234567", "account": "dsmismirnov", "tab": 1, "phrase": "ремонт квартиры", "status": "success", "message": "Частотность получена: 27892800", "ws": 27892800, "elapsed": 0.445, "api_received": true}
```

### Как анализировать логи:

**1. Найти фразы с ws=0:**
```bash
grep '"ws": 0' keyset/logs/parsing_debug.jsonl
```

**2. Найти фразы с таймаутом API:**
```bash
grep '"api_timeout"' keyset/logs/parsing_debug.jsonl
```

**3. Найти критические ошибки:**
```bash
grep '"critical_error"' keyset/logs/parsing_debug.jsonl
```

**4. Проверить получены ли API ответы:**
```bash
grep '"api_received": false' keyset/logs/parsing_debug.jsonl
```

---

## ✅ ЗАДАЧА 2: TAB РАЗДЕЛИТЕЛЬ В CSV

### Файл: `parsing_tab.py`

**Было:** `csv.writer(f, quoting=csv.QUOTE_MINIMAL)`
**Стало:** `csv.writer(f, delimiter='\t', quoting=csv.QUOTE_MINIMAL)`

**Файл:** [parsing_tab.py:848-851](c:\AI\yandex\keyset\app\tabs\parsing_tab.py#L848-L851)

```python
# Записываем в CSV с TAB разделителем для надёжности
# TAB предпочтительнее запятой, т.к. в фразах могут быть запятые
with open(file_path, 'w', newline='', encoding='utf-8-sig') as f:
    writer = csv.writer(f, delimiter='\t', quoting=csv.QUOTE_MINIMAL)
```

### Преимущества TAB разделителя:

✅ **Надёжность:** В фразах редко встречаются табы
✅ **Excel:** Правильно распознаёт колонки
✅ **Совместимость:** Работает в Google Sheets, LibreOffice
✅ **Читаемость:** Чётко разделяет данные

### Пример CSV с TAB:

```
Фраза	Частотность
ремонт квартир под ключ	56262
купить квартиру москва	615470
доставка еды на дом	55432
```

(Между колонками TAB символ, не пробел)

---

## 🧪 КАК ТЕСТИРОВАТЬ

### Тест 1: Проверка логирования

1. Запустить парсинг 10-20 фраз
2. Открыть `keyset/logs/parsing_debug.jsonl`
3. **Проверить:**
   - Есть ли запись `started` для каждой фразы
   - Есть ли запись `api_response_received` от API
   - Есть ли запись `success` или `api_timeout` для каждой фразы
   - Поле `elapsed` показывает время выполнения

### Тест 2: Анализ фраз с ws=0

1. После парсинга найти фразы с 0 частотностью
2. Искать в `parsing_debug.jsonl` по фразе
3. **Анализировать последовательность:**
   - Если `api_timeout` → увеличить RESPONSE_WAIT_TIMEOUT
   - Если `error_no_input` → проблема с селектором поля ввода
   - Если `api_response_received` есть, но `success` нет → race condition

### Тест 3: Экспорт CSV с TAB

1. После парсинга нажать "Экспорт"
2. Открыть CSV в Excel/Google Sheets
3. **Проверить:**
   - Фраза в колонке A
   - Частотность в колонке B
   - Нет объединённых ячеек
   - Запятые в фразах не ломают структуру

---

## 📊 ДИАГНОСТИКА ПРОБЛЕМ

### Если фраза показывает 0:

1. **Найти в логах:**
```bash
grep "фраза текст" keyset/logs/parsing_debug.jsonl
```

2. **Проверить статусы:**
   - `api_timeout` → Wordstat не отвечает (плохой прокси? капча?)
   - `error_no_input` → Селектор поля не работает
   - `critical_error` → Ошибка в коде

3. **Проверить api_received:**
   - `true` → API ответил, но результат 0 (это реальная частотность!)
   - `false` → API не ответил за таймаут

### Если все фразы показывают 0:

1. Проверить авторизацию аккаунта
2. Проверить прокси (если используется)
3. Проверить капчу в браузере
4. Увеличить RESPONSE_WAIT_TIMEOUT до 15-20 секунд

---

## ✅ ЧЕК-ЛИСТ

### Логирование:
- [x] Функция `log_parsing_debug()` добавлена
- [x] Логирование этапа `started`
- [x] Логирование этапа `input_found`
- [x] Логирование этапа `phrase_typed`
- [x] Логирование этапа `enter_pressed`
- [x] Логирование этапа `api_waiting`
- [x] Логирование этапа `success` / `api_timeout`
- [x] Логирование `api_response_received` в handle_response
- [x] Логирование критических ошибок
- [x] Сохранение в JSONL формате
- [x] UTF-8 кодировка
- [x] Временные метки (elapsed)

### CSV экспорт:
- [x] TAB разделитель (`delimiter='\t'`)
- [x] 2 колонки (Фраза, Частотность)
- [x] UTF-8-sig кодировка
- [x] Сортировка по убыванию
- [x] QUOTE_MINIMAL

---

## 📝 ФАЙЛЫ ИЗМЕНЕНЫ

1. **`c:\AI\yandex\keyset\turbo_parser_improved.py`**
   - Строки 76-97: функция `log_parsing_debug()`
   - Строки 523-535: логирование в `handle_response()`
   - Строки 556-749: детальное логирование в `parse_tab()`

2. **`c:\AI\yandex\keyset\app\tabs\parsing_tab.py`**
   - Строки 848-851: TAB разделитель в CSV экспорте

---

## 🎯 РЕЗУЛЬТАТ

### До:
- ❌ Нет детальных логов → невозможно понять почему ws=0
- ❌ CSV с запятой → фразы с запятыми ломают структуру

### После:
- ✅ Детальные JSONL логи на каждом этапе → видно где теряются данные
- ✅ CSV с TAB разделителем → надёжная структура, правильно открывается в Excel

---

**Автор:** Claude (AI Assistant)
**Encoding:** UTF-8
**Проверено:** Синтаксис валиден, импорты корректны
**Логи:** `keyset/logs/parsing_debug.jsonl`
