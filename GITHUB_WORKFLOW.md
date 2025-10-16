# 🔄 ОБЯЗАТЕЛЬНЫЙ GITHUB WORKFLOW ДЛЯ AI АГЕНТОВ

**⚠️ КРИТИЧЕСКИ ВАЖНО: ПОСЛЕ КАЖДОЙ ПРАВКИ → COMMIT + PUSH В GITHUB!**

---

## 📋 АВТОМАТИЧЕСКАЯ ПОСЛЕДОВАТЕЛЬНОСТЬ

### После ЛЮБОЙ правки файлов:

1. **Проверь статус:**
```bash
cd C:\AI\yandex\keyset
git status
```

2. **Добавь файлы:**
```bash
git add .
```

3. **Проверь что будет закоммичено:**
```bash
git diff --cached
```

4. **Создай коммит:**
```bash
git commit -m "fix: краткое описание

- Детали изменений
- Какие файлы правил

Co-authored-by: factory-droid[bot] <138933559+factory-droid[bot]@users.noreply.github.com>"
```

5. **Отправь в GitHub:**
```bash
git push origin main
```

6. **Подтверди пользователю:**
```
✅ Изменения отправлены в GitHub
```

---

## 📝 ФОРМАТ COMMIT MESSAGE

```
тип: краткое описание (до 50 символов)

Детальное описание:
- Что изменено
- Зачем изменено

Co-authored-by: factory-droid[bot] <138933559+factory-droid[bot]@users.noreply.github.com>
```

**Типы коммитов:**
- `fix:` - исправление бага
- `feat:` - новая функция
- `refactor:` - рефакторинг
- `docs:` - документация
- `chore:` - рутинные задачи
- `test:` - тесты

---

## ❌ НЕ КОММИТИТЬ (уже в .gitignore):

```
__pycache__/
*.pyc
.venv/
results/
*.db
.profiles/
configs/accounts.json
secrets/
```

---

## 🚀 БЫСТРАЯ КОМАНДА

```bash
cd C:\AI\yandex\keyset; git add .; git commit -m "тип: описание

Co-authored-by: factory-droid[bot] <138933559+factory-droid[bot]@users.noreply.github.com>"; git push origin main
```

---

## 📊 РЕПОЗИТОРИЙ

**GitHub:** https://github.com/websetpro-blip/keyset

**Помни:** Код без коммита = потерянная работа!
