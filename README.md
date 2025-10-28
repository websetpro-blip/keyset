# 🚀 KeySet - Full Pipeline Edition

**KeySet** — профессиональный инструмент для комплексного анализа ключевых слов с интеграцией Yandex Wordstat, Yandex Direct API и автоматической кластеризацией.

Дополнительно для вкладки «Маски»:
- xmindparser — парсинг .xmind
- pymorphy2 — морфология
- pyperclip — копирование в буфер обмена


---

## Comet GUI (новый интерфейс)
- Запуск десктопного UI: `python -m keyset.app.main` (из корня проекта) или `python run_keyset.pyw`.
- Tabs: Аккаунты, Парсинг, Маски. Masks can push phrases straight into the parsing tab.
- The top toolbar mirrors Key Collector actions (Частотка, Вглубь, Прогноз бюджета, Гео, Минусовка, Стоп-слова, Экспорт, Аналитика).
- История задач находится в нижнем доке; обновление списка аккаунтов обновляет и список профилей на панели.

## 📦 Основные возможности

### 🔥 Full Pipeline Mode
- **Wordstat парсинг** — автоматический сбор частотности по маскам
- **Direct API интеграция** — прогнозы бюджетов, кликов, показов, CPC
- **Автоматическая кластеризация** — NLTK-based группировка фраз
- **CSV/XLSX экспорт** — полная поддержка UTF-8, мультиформатный вывод

### ⚡ Турбо-парсер
- До **195 фраз/минуту** (с учетом лимитов Yandex)
- Умная обработка капчи и ротация аккаунтов
- CDP режим с поддержкой user_data_dir

### 🌍 Region & Proxy Management
- **Выбор региона** — любой регион РФ для таргетинга
- **Proxy поддержка** — HTTP/HTTPS/SOCKS5 прокси
- **IP rotation** — автоматическая ротация при блокировках

---

## 🚀 Быстрый старт

### 1️⃣ Установка

```bash
# Клонирование репозитория
git clone https://github.com/websetpro-blip/keyset.git
cd keyset

# Создание виртуального окружения
python -m venv venv
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# Установка зависимостей
pip install -r requirements.txt

# Установка Playwright браузеров
playwright install chromium
```

### 2️⃣ Настройка Yandex аккаунтов

**Способ 1: Автологин (рекомендуется)**
```bash
python login.py --email your@email.com --password yourpass
```

**Способ 2: Ручной вход**
```bash
python login.py --manual
```

### 3️⃣ Настройка конфигурации

**config.json:**
```json
{
  "region_id": 213,
  "proxy": {
    "enabled": true,
    "server": "http://proxy.example.com:8080",
    "username": "user",
    "password": "pass"
  },
  "direct_api": {
    "token": "YOUR_YANDEX_DIRECT_TOKEN",
    "client_login": "your-client-login"
  },
  "parsing": {
    "batch_size": 195,
    "delay_range": [2, 5]
  }
}
```

### 4️⃣ Запуск парсинга

```bash
# Full Pipeline (Wordstat + Direct + Clustering)
python main.py --mode full --input keywords.txt --output results/

# Только Wordstat
python main.py --mode wordstat --input keywords.txt

# Только Direct прогнозы
python main.py --mode direct --input keywords.txt
```

---

## 📖 Детальные гайды

- 📘 **[QUICK_START.md](QUICK_START.md)** — быстрый старт для новичков
- 📗 **[FULL_PIPELINE_GUIDE.md](FULL_PIPELINE_GUIDE.md)** — полное руководство по Full Pipeline
- 📙 **[UPDATE_INSTRUCTIONS.md](UPDATE_INSTRUCTIONS.md)** — инструкции по обновлению
- 📕 **[GITHUB_WORKFLOW.md](GITHUB_WORKFLOW.md)** — workflow для разработки

---

## 🌍 Настройка регионов и прокси

### Выбор региона Wordstat

```python
# В коде или через config.json
REGION_ID = 213  # Москва
REGION_ID = 2    # Санкт-Петербург
REGION_ID = 54   # Екатеринбург
REGION_ID = 11316 # Новосибирск
```

**Полный список регионов:** https://yandex.ru/dev/direct/doc/dg/objects/regions.html

### Настройка прокси

**HTTP/HTTPS Proxy:**
```json
{
  "proxy": {
    "server": "http://proxy.example.com:8080",
    "username": "user",
    "password": "pass"
  }
}
```

**SOCKS5 Proxy:**
```json
{
  "proxy": {
    "server": "socks5://proxy.example.com:1080",
    "username": "user",
    "password": "pass"
  }
}
```

**Без прокси:**
```json
{
  "proxy": {
    "enabled": false
  }
}
```

---

## 📊 Интеграция с Yandex Direct API

### Получение токена Direct API

1. Перейдите: https://oauth.yandex.ru/
2. Зарегистрируйте приложение
3. Получите **OAuth Token**
4. Добавьте в `config.json`:

```json
{
  "direct_api": {
    "token": "YOUR_OAUTH_TOKEN",
    "client_login": "your-login"
  }
}
```

### Доступные метрики Direct

- **Impressions** — прогноз показов
- **Clicks** — прогноз кликов
- **CTR** — средний CTR
- **CPC** — средняя цена клика
- **Budget** — необходимый бюджет

---

## 🧩 Кластеризация ключевых слов

### NLTK Stemming

```python
from nltk.stem.snowball import RussianStemmer

stemmer = RussianStemmer()
keywords = ["купить телефон", "телефоны купить", "купить смартфон"]

# Автоматическая группировка по стеммингу
clusters = auto_cluster(keywords, method="stem")
```

### Методы кластеризации

1. **Stemming** — морфологическая группировка
2. **N-gram** — группировка по общим словам
3. **Semantic** — семантическая близость (word2vec)

---

## 💾 Экспорт данных

### CSV Export (UTF-8)

```python
import pandas as pd

df = pd.DataFrame(results)
df.to_csv('output.csv', encoding='utf-8-sig', index=False)
```

### XLSX Export

```python
from openpyxl import Workbook

wb = Workbook()
ws = wb.active
ws.append(["Keyword", "Frequency", "CPC", "Cluster"])

for row in results:
    ws.append([row['keyword'], row['freq'], row['cpc'], row['cluster']])

wb.save('output.xlsx')
```

### Форматы экспорта

- **CSV** — универсальный формат (UTF-8 BOM для Excel)
- **XLSX** — Excel с форматированием
- **JSON** — для API интеграций
- **KeyCollector** — прямой импорт в KC

---

## 🎓 Примеры использования

### Пример 1: Анализ конкурентов

```bash
# Создайте файл competitors.txt
бренд1
бренд2
бренд3

# Запустите Full Pipeline
python main.py --mode full --input competitors.txt --region 213

# Результат: CSV с частотами, CPC, кластерами
```

### Пример 2: Семантическое ядро

```bash
# Создайте файл seeds.txt
купить [товар]
заказать [товар]
цена [товар]

# Расширение через Wordstat
python main.py --mode wordstat --expand --input seeds.txt

# Результат: расширенное ядро с частотами
```

### Пример 3: Бюджетирование кампании

```bash
# Все фразы кампании
python main.py --mode direct --input campaign_keywords.txt

# Результат: прогноз бюджета, кликов, показов
```

---

## 🔧 Продвинутая конфигурация

### Настройка парсинга

```json
{
  "parsing": {
    "batch_size": 195,
    "delay_range": [2, 5],
    "max_retries": 3,
    "timeout": 30,
    "user_agent": "custom-ua"
  }
}
```

### Настройка кластеризации

```json
{
  "clustering": {
    "method": "stem",
    "threshold": 0.7,
    "min_cluster_size": 3
  }
}
```

### Настройка экспорта

```json
{
  "export": {
    "formats": ["csv", "xlsx", "json"],
    "encoding": "utf-8-sig",
    "delimiter": ","
  }
}
```

---

## 📈 История версий

### v2.0 (13.01.2025) - Full Pipeline 🚀
- ✅ Full Pipeline: Wordstat → Direct → Clustering
- ✅ NLTK интеграция (Russian stemming)
- ✅ WAL режим базы данных
- ✅ Расширенный CSV export (UTF-8 BOM)
- ✅ Region & Proxy management

### v1.0 (12.10.2025) - Турбо парсер
- ✅ Турбо-парсер (до 195 фраз/мин)
- ✅ Управление аккаунтами
- ✅ Автологин с CDP

---

## ⚠️ Важные замечания

### Лимиты Yandex
- **Wordstat:** ~200 запросов/минуту
- **Direct API:** 10,000 запросов/день
- **Captcha:** обрабатывается автоматически

### Требования
- **Python:** 3.8+
- **RAM:** минимум 2GB
- **Disk:** 500MB для базы данных

---

## 🔗 Полезные ссылки

- **Репозиторий:** https://github.com/websetpro-blip/keyset
- **Issues:** https://github.com/websetpro-blip/keyset/issues
- **Discussions:** https://github.com/websetpro-blip/keyset/discussions
- **Yandex Direct API:** https://yandex.ru/dev/direct/
- **Yandex Wordstat:** https://wordstat.yandex.ru/

---

## ⚠️ ДЛЯ AI АГЕНТОВ

**ОБЯЗАТЕЛЬНО:** После каждой правки → commit + push в GitHub!

📄 **Инструкция:** [GITHUB_WORKFLOW.md](GITHUB_WORKFLOW.md)

---

## 🙏 Благодарности

- Yandex Wordstat & Direct API
- Playwright team
- NLTK contributors
- Qt/PySide6 developers

---

**Made with ❤️ for SEO specialists**

**Удачного парсинга!** 🚀
