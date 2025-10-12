# 🚀 БЫСТРЫЙ СТАРТ - SemTool Full Pipeline

**За 5 минут до первого запуска!**

---

## ⚡ ШАГ 1: Обновите код (30 сек)

```powershell
cd C:\AI\yandex\semtool

# Закройте GUI если открыт
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Подтяните изменения
git pull origin main
```

**Ожидается:** `Already up to date` или список обновлений

---

## ⚡ ШАГ 2: Установите nltk (1 мин)

```powershell
# Установка
python -m pip install nltk==3.9.1

# Скачать данные
python -c "import nltk; nltk.download('stopwords', quiet=True); print('✓ NLTK готов')"
```

**Ожидается:** `✓ NLTK готов`

---

## ⚡ ШАГ 3: Запустите GUI (5 сек)

```powershell
python -m semtool.app.main
```

**Должна появиться вкладка:** 🚀 Full Pipeline

---

## ⚡ ШАГ 4: Тестовый запуск (2 мин)

### В GUI:

1. **Откройте вкладку:** 🚀 Full Pipeline

2. **Загрузите тестовый файл:**
   - Нажмите: **📁 Загрузить из файла**
   - Выберите: `data/example_phrases.txt` (10 фраз)

3. **Запустите:**
   - Нажмите: **🚀 ЗАПУСТИТЬ FULL PIPELINE**
   - Ждите ~30 секунд

4. **Результат:**
   - Таблица заполнится 10 строками
   - Колонки: Фраза, Частотность, CPC, Показы, Бюджет, Группа
   - Статистика: ~20 фраз/мин

5. **Экспорт:**
   - Нажмите: **💾 Экспорт CSV**
   - Сохраните результаты

---

## ✅ ГОТОВО!

**Теперь Full Pipeline работает!**

### Что дальше?

- **Свои фразы:** Загрузите свой .txt файл (одна фраза на строку)
- **Большие объёмы:** Протестируйте на 50-100 фразах
- **Анализ:** Откройте CSV в Excel, анализируйте по группам

### Полная документация:

- 📘 **FULL_PIPELINE_GUIDE.md** - подробное руководство
- 📙 **UPDATE_INSTRUCTIONS.md** - обновление и troubleshooting

---

## 🆘 Проблемы?

### "No module named 'nltk'"
```powershell
python -m pip install nltk==3.9.1
```

### "Вкладка Full Pipeline не появилась"
```powershell
# Перезапустите GUI
Get-Process python | Stop-Process -Force
python -m semtool.app.main
```

### "Парсинг не запускается"
- Проверьте интернет
- Попробуйте меньше фраз (3-5)
- Смотрите логи в GUI

---

## 📊 Что получаете:

✅ Частотность из Wordstat (60-80 фраз/мин)  
✅ Прогноз бюджета из Direct (100 фраз/мин)  
✅ Группировка по семантике (NLTK)  
✅ Export в CSV с полными данными  

**Итого: ~112 фраз/мин с полной аналитикой!**

---

🎉 **Приятного парсинга!**
