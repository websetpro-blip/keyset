# Changelog: Умный генератор масок XMind

## Версия 5.0 - Smart XMind Generator

### Новые возможности

#### 1. XMind Parser с типизацией
- **Файл**: `core/xmind_parser.py`
- Добавлен dataclass `MindNode` для структурированного хранения данных
- Поддержка типизации узлов по меткам (CORE, COMMERCIAL, INFO, ATTR, EXCLUDE)
- Чтение иерархии через ключ `topics` (совместимость с xmindparser)
- Поддержка XMind 8 и XMind 2020/Zen
- Метод `load()` возвращает `MindNode` с полной иерархией
- Метод `parse()` для обратной совместимости

#### 2. Морфологическая фильтрация
- **Файл**: `services/morphology_filter.py`
- Нормализация токенов с pymorphy2 (с fallback для Python 3.12+)
- Функция `normalize_phrase()` - упорядочивание слов
- Функция `is_good_phrase()` - валидация по лимитам Яндекс.Директа
- Фильтрация стоп-слов
- Проверка повторов
- Класс `MorphologyFilter` для объектного API

#### 3. Классификация намерений
- **Файл**: `services/intent_classifier.py`
- Rule-based классификатор
- Типы: TRANSACTIONAL, INFORMATIONAL, COMMERCIAL, GENERAL
- Функция `classify_intent()` для быстрой классификации
- Класс `IntentClassifier` с методом `classify()` (возвращает намерение + уверенность)

#### 4. Умное перемножение масок
- **Файл**: `services/keyword_multiplier.py`
- Функция `multiply()` для перемножения групп слов
- Использует `itertools.product` для комбинаций
- Интеграция с морфологией и классификацией
- Поддержка групп: core, products, mods, attrs, geo, brands
- Скоринг на основе намерения (TRANSACTIONAL = 1.0, INFORMATIONAL = 0.6, GENERAL = 0.4)
- Дедупликация и сортировка
- Метод `_extract_groups_from_tree()` - автоматическое извлечение групп из XMind

#### 5. Обновленный UI в MasksTab
- **Файл**: `app/tabs/maskstab.py`
- 3 подвкладки: "Обычный ввод", "Карта (XMind)", "Генератор"
- Добавлена визуализация майнд-карты (QGraphicsView + QGraphicsScene)
- Режим "центр и лучи" с цветовой кодировкой типов узлов
- Splitter для одновременного просмотра дерева и визуализации
- Метод `_render_mindmap()` для отрисовки майнд-карты
- Экспорт в CSV с разделителем `;`
- Кнопка "Передать в Парсинг"
- Обновленные названия вкладок (без эмодзи в начале)

### Улучшения

#### MasksTab
- Добавлен импорт необходимых компонентов Qt (QSplitter, QGraphicsView, QGraphicsScene)
- Добавлен импорт модулей csv и math
- Метод `on_load_xmind()` теперь вызывает `_render_mindmap()`
- Метод `_display_xmind_tree()` показывает метки в третьей колонке
- Метод `on_multiplier_export_csv()` для экспорта в CSV
- Метод `on_multiplier_to_parsing()` для передачи в Парсинг
- Улучшенная обработка ошибок

#### XMind Parser
- Поддержка notes из XMind файлов
- Улучшенная обработка пустых узлов
- Конвертация в legacy формат для совместимости

#### Morphology Filter
- Graceful fallback при недоступности pymorphy2
- Warning вместо exception при ошибках импорта
- Поддержка коммерческих глаголов
- Умное упорядочивание слов

#### Keyword Multiplier
- Fallback на absolute imports при relative import errors
- Более точный скоринг с учетом длины фразы
- Маппинг типов XMind узлов на группы

### Технические детали

#### Зависимости
- xmindparser >= 1.0.8 (уже в requirements.txt)
- pymorphy2 >= 0.9.1 (уже в requirements.txt, опционально)
- pyperclip >= 1.8.2 (уже в requirements.txt)

#### Совместимость
- Python 3.8+ (с fallback для pymorphy2 на 3.12+)
- PySide6 >= 6.8.0.2
- XMind 8 и XMind 2020/Zen

#### Лимиты Яндекс.Директа
- ✅ Максимум 7 слов в маске
- ✅ Фильтрация повторов
- ✅ Дедупликация
- ✅ Приоритет коммерческих запросов

### Файлы изменены
```
modified:   app/tabs/maskstab.py
modified:   core/xmind_parser.py
modified:   services/intent_classifier.py
modified:   services/keyword_multiplier.py
modified:   services/morphology_filter.py
```

### Новые файлы
```
MASKS_SMART_GENERATOR_IMPLEMENTATION.md - подробная документация
CHANGELOG_SMART_GENERATOR.md - этот файл
```

### Тестирование
Все компоненты протестированы и работают корректно:
- ✅ XMind Parser загружает и парсит файлы
- ✅ Morphology Filter нормализует фразы
- ✅ Intent Classifier определяет намерения
- ✅ Keyword Multiplier генерирует маски
- ✅ MasksTab UI компилируется без ошибок

### Migration Notes
Нет breaking changes. Все изменения обратно совместимы:
- Старый API XMindParser (`parse()`) продолжает работать
- Новый API доступен через `load()` → `MindNode`
- Fallback на упрощенную морфологию при отсутствии pymorphy2
- Fallback на absolute imports в keyword_multiplier

### Что дальше?
Возможные улучшения в следующих версиях:
1. Интеграция с Wordstat API для проверки частот
2. ML-модель для классификации намерений
3. Автоматическая группировка похожих масок
4. Поддержка операторов Директа (!, +, "")
5. Preset'ы для разных ниш

## Commit Message
```
feat(masks): add smart XMind generator with morphology and intent classification

- Add MindNode dataclass with label-based type detection
- Implement morphology filter with pymorphy2 (with fallback)
- Add rule-based intent classifier (TRANSACTIONAL/INFORMATIONAL/GENERAL)
- Implement smart keyword multiplier with scoring
- Add mind-map visualization (center + rays) with color coding
- Add CSV export and "Send to Parsing" functionality
- Update MasksTab with 3 sub-tabs
- Support XMind 8 and XMind 2020/Zen formats
- Handle Yandex.Direct limits (max 7 words)
```
