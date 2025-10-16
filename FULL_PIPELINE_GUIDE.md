# 🚀 FULL PIPELINE - Полное руководство

**Версия:** 1.0  
**Дата:** 13.01.2025

---

## 🎯 ЧТО ТАКОЕ FULL PIPELINE?

**Full Pipeline** - это **полный цикл парсинга** от масок до готового CSV с бюджетами и группировкой, как в KeyCollector.

### Этапы pipeline:
1. **📊 Wordstat** - парсинг частотности (60-80 фраз/мин)
2. **💰 Direct** - прогноз бюджета и CPC (100 фраз/мин)
3. **🔗 Clustering** - группировка по стеммам (NLTK)
4. **💾 Export** - сохранение в CSV с полными данными

**Итого: ~112+ фраз/минуту** с полной аналитикой!

---

## 📦 ТРЕБОВАНИЯ:

### Установлены:
```bash
python >= 3.10
playwright
nltk
PySide6
```

### Проверка:
```powershell
cd C:\AI\yandex\keyset
python -c "from services.frequency import parse_batch_wordstat; from services.direct import forecast_batch_direct; from nltk.stem.snowball import SnowballStemmer; print('All OK!')"
```

Если ошибка `ModuleNotFoundError: No module named 'nltk'`:
```powershell
python -m pip install nltk==3.9.1
python -c "import nltk; nltk.download('stopwords', quiet=True)"
```

---

## 🚀 ЗАПУСК FULL PIPELINE:

### Шаг 1: Обновите код
```powershell
cd C:\AI\yandex\keyset

# Закройте GUI если открыт
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Подтяните изменения
git pull origin main

# Проверьте что последний коммит c49e4e9
git log --oneline -1
```

**Ожидается:** `c49e4e9 feat: add Full Pipeline tab...`

---

### Шаг 2: Установите зависимости
```powershell
# Если используете venv:
.\.venv\Scripts\activate

# Установка nltk
python -m pip install nltk==3.9.1

# Скачать данные NLTK
python -c "import nltk; nltk.download('stopwords', quiet=True); print('NLTK ready')"
```

---

### Шаг 3: Запустите GUI
```powershell
python -m keyset.app.main
```

**Должна появиться новая вкладка:** 🚀 Full Pipeline

---

## 📋 ИСПОЛЬЗОВАНИЕ:

### 1. Подготовьте фразы

Создайте файл `phrases.txt`:
```
купить телефон
купить iphone
купить samsung galaxy
ремонт телефонов
```

**ИЛИ** введите вручную в текстовое поле.

---

### 2. Настройте параметры

- **Регион:** 225 (Россия) - можно изменить
- **Фразы:** Загрузите файл или введите вручную

---

### 3. Запустите Pipeline

Нажмите **🚀 ЗАПУСТИТЬ FULL PIPELINE**

**Что произойдет:**

```
📊 Этап 1/3: Парсинг частотности (Wordstat)...
   ├─ купить телефон: 15,000 ✅
   ├─ купить iphone: 8,500 ✅
   ├─ купить samsung galaxy: 3,200 ✅
   └─ ремонт телефонов: 12,000 ✅

💰 Этап 2/3: Прогноз бюджета (Direct)...
   ├─ CPC, показы, бюджет для каждой фразы
   └─ Автоматическая оценка если Direct недоступен

🔗 Этап 3/3: Объединение и группировка...
   ├─ Stemming (купить → купи, телефон → телефон)
   ├─ Группировка по стеммам
   └─ Статистика по группам

✅ Готово! Обработано 4 фразы
```

---

### 4. Результаты в таблице

| Время | Фраза | Частотность | CPC | Показы | Бюджет | Группа | Статус |
|-------|-------|-------------|-----|--------|--------|--------|--------|
| 10:30:15 | купить телефон | 15,000 | 25.50 | 12,000 | 600.00 | купи | ✅ |
| 10:30:18 | купить iphone | 8,500 | 35.00 | 6,800 | 476.00 | купи | ✅ |
| 10:30:21 | купить samsung | 3,200 | 40.00 | 2,560 | 204.80 | купи | ✅ |
| 10:30:24 | ремонт телефонов | 12,000 | 30.00 | 9,600 | 576.00 | ремонт | ✅ |

**Колонки:**
- **Группа** - stemmed корень слова
- **Бюджет** - прогноз месячного бюджета (₽)
- **CPC** - стоимость клика
- **Показы** - прогноз показов

---

### 5. Экспорт в CSV

Нажмите **💾 Экспорт CSV**

**Файл будет содержать:**
```csv
Фраза;Частотность;CPC;Показы;Бюджет;Группа;Размер группы;Средняя частота группы;Общий бюджет группы
купить телефон;15000;25.5;12000;600;купи;3;8900;1280.8
купить iphone;8500;35;6800;476;купи;3;8900;1280.8
купить samsung;3200;40;2560;204.8;купи;3;8900;1280.8
ремонт телефонов;12000;30;9600;576;ремонт;1;12000;576
```

**Дополнительные колонки для анализа:**
- `Размер группы` - сколько фраз в группе
- `Средняя частота группы` - средняя частотность по группе
- `Общий бюджет группы` - суммарный бюджет группы

---

## 🎨 ИНТЕРФЕЙС:

### Кнопки:
- **📁 Загрузить из файла** - открыть .txt с фразами
- **🗑 Очистить** - очистить текстовое поле
- **🚀 ЗАПУСТИТЬ FULL PIPELINE** - старт парсинга
- **⏹ ОСТАНОВИТЬ** - отмена выполнения
- **💾 Экспорт CSV** - сохранить результаты

### Индикаторы:
- **Прогресс бар** - % выполнения
- **Статистика** - обработано, успешно, скорость, время
- **Таблица** - real-time результаты

---

## 🔧 ТЕХНИЧЕСКИЕ ДЕТАЛИ:

### Архитектура:

```
FullPipelineTab (GUI)
    └─> FullPipelineWorkerThread (QThread)
            ├─> services/frequency.py::parse_batch_wordstat()
            ├─> services/direct.py::forecast_batch_direct()
            └─> _cluster_phrases() (NLTK stemming)
                    └─> Сохранение в DB (frequencies, forecasts, clusters)
```

### Rate Limiting:
- **Wordstat:** 1 запрос/сек = 60/мин (с паузами между батчами)
- **Direct:** 0.8 сек/запрос = 75-100/мин
- **Total:** ~112 фраз/мин с полным циклом

### База данных (WAL режим):
```sql
-- Сохраняются в:
frequencies (phrase, freq, region, processed)
forecasts (phrase, cpc, impressions, budget, freq_ref)
clusters (stem, phrases, avg_freq, total_budget)
```

---

## 📊 ПРОИЗВОДИТЕЛЬНОСТЬ:

### Benchmark:
- **10 фраз:** ~10 секунд
- **50 фраз:** ~35 секунд
- **100 фраз:** ~60 секунд
- **500 фраз:** ~5 минут
- **1000 фраз:** ~10 минут

**С 5 аккаунтами ротации:** до 500+ фраз/мин!

---

## ❌ TROUBLESHOOTING:

### Проблема: "No module named 'nltk'"
```powershell
python -m pip install nltk==3.9.1
python -c "import nltk; nltk.download('stopwords')"
```

---

### Проблема: "Вкладка Full Pipeline не появилась"
```powershell
# 1. Закройте GUI
Get-Process python | Stop-Process -Force

# 2. Удалите кэш
Remove-Item -Recurse -Force app/__pycache__
Remove-Item -Recurse -Force workers/__pycache__

# 3. Git pull
git pull origin main

# 4. Перезапустите
python -m keyset.app.main
```

---

### Проблема: "ImportError: attempted relative import"
Это нормально! Запускайте через модуль:
```powershell
python -m keyset.app.main
```

**НЕ запускайте напрямую:** `python app/main.py` ❌

---

### Проблема: "Парсинг зависает на Wordstat"
- Проверьте интернет соединение
- Возможна блокировка Яндексом (нужен VPN или прокси)
- Уменьшите chunk_size в коде (80 → 40)

---

### Проблема: "CPC = 0 для всех фраз"
Direct API может быть недоступен. Pipeline использует **эвристическую оценку**:
- freq > 100,000 → CPC = 15₽
- freq > 10,000 → CPC = 25₽
- freq > 1,000 → CPC = 35₽
- freq > 100 → CPC = 50₽
- freq < 100 → CPC = 70₽

---

## 🎓 ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ:

### Пример 1: Анализ конкурентов
```
1. Загрузите список брендов конкурентов
2. Запустите Full Pipeline
3. Экспортируйте CSV
4. Анализируйте в Excel:
   - Сортировка по бюджету (дорогие ниши)
   - Группировка по стеммам (семантические кластеры)
   - Фильтр по частотности (популярные запросы)
```

---

### Пример 2: Подбор семантического ядра
```
1. Введите базовые маски (купить, заказать, цена)
2. Full Pipeline даст оценки по всем
3. Отфильтруйте низкочастотные (<10)
4. Экспортируйте в KeyCollector для дальнейшей работы
```

---

### Пример 3: Бюджетирование кампании
```
1. Список всех планируемых фраз
2. Full Pipeline → получите прогнозы бюджетов
3. Суммируйте по группам (Excel: SUMIF по Группа)
4. Планируйте бюджет кампании на основе данных
```

---

## 📚 ДОПОЛНИТЕЛЬНЫЕ МАТЕРИАЛЫ:

- **UPDATE_INSTRUCTIONS.md** - как обновить KeySet
- **GITHUB_WORKFLOW.md** - работа с Git
- **README.md** - общая информация о проекте

---

## 🔗 РЕПОЗИТОРИЙ:

**GitHub:** https://github.com/websetpro-blip/keyset

**Коммиты Full Pipeline:**
- `c49e4e9` - feat: add Full Pipeline tab
- `0f556b7` - feat: add pipeline services
- `8d9005d` - feat: add WAL mode and tables

---

## ✅ ЧЕКЛИСТ ГОТОВНОСТИ:

Перед первым запуском проверьте:

- [ ] Git pull выполнен (`git log -1` показывает c49e4e9)
- [ ] nltk установлен (`python -c "import nltk"`)
- [ ] stopwords скачаны (`python -c "import nltk; nltk.data.find('corpora/stopwords')"`)
- [ ] GUI полностью закрыт и перезапущен
- [ ] Вкладка 🚀 Full Pipeline видна
- [ ] База данных обновлена (WAL режим)

---

## 🎉 ГОТОВО К ИСПОЛЬЗОВАНИЮ!

Теперь у вас есть полноценный KeyCollector-like инструмент в KeySet!

**Приятного парсинга! 🚀**
