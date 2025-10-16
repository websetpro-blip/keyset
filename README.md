# 🚀 KeySet - Full Pipeline Edition

**Массовый парсинг Wordstat + Direct + Кластеризация**

[![Version](https://img.shields.io/badge/version-2.0-blue.svg)](https://github.com/websetpro-blip/keyset)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org)
[![License](https://img.shields.io/badge/license-Open%20Source-brightgreen.svg)](LICENSE)

---

## 🎯 Что это?

**KeySet** - это полный цикл анализа семантики для SEO:

```
Маски → Wordstat → Direct → Clustering → CSV
```

**Как KeyCollector, но бесплатно и с автоматизацией!**

### ⚡ Возможности:
- 📊 **Wordstat парсинг** (60-80 фраз/мин)
- 💰 **Direct прогноз** (CPC + бюджеты)
- 🔗 **Кластеризация** (NLTK Russian)
- ⚡ **Турбо-режим** (до 195 фраз/мин)
- 🤖 **Автологин** (5 аккаунтов Яндекс)
- 💾 **Export CSV** с полными данными

---

## 🚀 Быстрый старт

### 1. Клонируй и установи:
```powershell
git clone https://github.com/websetpro-blip/keyset.git
cd keyset
pip install -r requirements.txt
python -c "import nltk; nltk.download('stopwords')"
```

### 2. Запусти GUI:
```powershell
python -m keyset.app.main
```

### 3. Используй Full Pipeline:
- Открой вкладку **🚀 Full Pipeline**
- Загрузи фразы из `data/example_phrases.txt`
- Нажми **ЗАПУСТИТЬ**
- Получи результаты с частотностью, CPC, бюджетами и группировкой!

**Детали:** [QUICK_START.md](QUICK_START.md)

---

## 📊 Full Pipeline (НОВОЕ!)

### Полный цикл за один клик:

```
Этап 1: 📊 Wordstat   → Парсинг частотности
Этап 2: 💰 Direct     → Прогноз бюджета + CPC
Этап 3: 🔗 Clustering → Группировка по стеммам
Этап 4: 💾 Export     → CSV с полными данными
```

**Результат:** Таблица с 8 колонками:
- Фраза | Частотность | CPC | Показы | Бюджет | Группа | Статус

**Скорость:** ~112 фраз/мин (комбо Wordstat+Direct)

**Подробнее:** [FULL_PIPELINE_GUIDE.md](FULL_PIPELINE_GUIDE.md)

---

## 📁 Структура проекта

```
keyset/
├── app/                    # Qt GUI интерфейс
│   ├── main.py            # Главное окно
│   ├── full_pipeline_tab.py  # Full Pipeline (НОВОЕ!)
│   └── turbo_tab_qt.py    # Турбо парсер
├── services/              # Бизнес-логика
│   ├── frequency.py       # Wordstat парсинг
│   ├── direct.py          # Direct прогноз (НОВОЕ!)
│   └── accounts.py        # Управление аккаунтами
├── workers/               # Async воркеры
│   ├── full_pipeline_worker.py  # Pipeline worker (НОВОЕ!)
│   └── turbo_parser_integration.py
├── core/                  # База данных
│   ├── db.py              # SQLite WAL (НОВОЕ!)
│   └── models.py          # SQLAlchemy модели
└── data/                  # Данные
    ├── keyset.db         # База WAL режим
    └── example_phrases.txt # Тестовые фразы
```

---

## 💻 Требования

- **Python:** 3.10+
- **OS:** Windows 10+ (Linux/Mac с адаптацией)
- **RAM:** 4GB+
- **Интернет:** Для Wordstat/Direct API

### Зависимости:
```
PySide6==6.8.0.2
playwright==1.48.0
nltk==3.9.1
sqlalchemy==2.0.36
```

---

## 📚 Документация

- 🚀 [QUICK_START.md](QUICK_START.md) - Быстрый старт (5 минут)
- 📘 [FULL_PIPELINE_GUIDE.md](FULL_PIPELINE_GUIDE.md) - Полное руководство
- 📙 [UPDATE_INSTRUCTIONS.md](UPDATE_INSTRUCTIONS.md) - Обновление после git pull
- 🔧 [GITHUB_WORKFLOW.md](GITHUB_WORKFLOW.md) - Git workflow для AI

---

## 🎓 Примеры использования

### Пример 1: Анализ конкурентов
```
1. Загрузи список брендов
2. Full Pipeline → частотность + бюджеты
3. Анализируй в Excel (группировка, сортировка)
```

### Пример 2: Семантическое ядро
```
1. Базовые маски (купить, заказать, цена)
2. Full Pipeline → оценки по всем
3. Фильтр низкочастотных
4. Export в KeyCollector
```

### Пример 3: Бюджетирование
```
1. Все планируемые фразы
2. Full Pipeline → прогнозы
3. Суммируй по группам
4. Планируй бюджет кампании
```

---

## 📈 История версий

### v2.0 (13.01.2025) - Full Pipeline 🚀
- ✅ Full Pipeline: Wordstat → Direct → Clustering
- ✅ NLTK интеграция (Russian stemming)
- ✅ WAL режим базы данных
- ✅ Расширенный CSV export

### v1.0 (12.10.2025) - Турбо парсер
- ✅ Турбо-парсер (до 195 фраз/мин)
- ✅ Управление аккаунтами
- ✅ Автологин с CDP

---

## ⚠️ ДЛЯ AI АГЕНТОВ

**ОБЯЗАТЕЛЬНО:** После каждой правки → commit + push в GitHub!

📄 **Инструкция:** [GITHUB_WORKFLOW.md](GITHUB_WORKFLOW.md)

---

## 🔗 Ссылки

- **Репозиторий:** https://github.com/websetpro-blip/keyset
- **Issues:** https://github.com/websetpro-blip/keyset/issues
- **Discussions:** https://github.com/websetpro-blip/keyset/discussions

---

## 🙏 Благодарности

- Yandex Wordstat & Direct API
- Playwright team
- NLTK contributors
- Qt/PySide6 developers

---

**Made with ❤️ for SEO specialists**

**Удачного парсинга!** 🚀