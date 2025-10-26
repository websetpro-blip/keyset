#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Тест диалога пакетного сбора фраз"""

import sys
from pathlib import Path

# Добавляем корень проекта в sys.path
project_root = Path(__file__).resolve().parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from PySide6.QtWidgets import QApplication
from app.dialogs.batch_collect_dialog import BatchCollectDialog


def on_collect_requested(phrases, settings):
    """Обработчик запроса сбора"""
    print("=" * 70)
    print("ЗАПРОС ПАКЕТНОГО СБОРА ФРАЗ")
    print("=" * 70)
    print(f"\n📝 Фразы ({len(phrases)}):")
    for i, phrase in enumerate(phrases[:10], 1):
        print(f"  {i}. {phrase}")
    if len(phrases) > 10:
        print(f"  ... и ещё {len(phrases) - 10} фраз")

    print(f"\n🌍 Регионы: {settings.get('geo_ids', [])}")
    print(f"📊 Порог показов: {settings.get('threshold', 0)}")

    mode = settings.get('mode', {})
    print(f"📋 Режим: {'в активную группу' if mode.get('to_active_group') else 'распределить по группам'}")

    options = settings.get('options', {})
    print(f"⚙️ Опции:")
    if options.get('skip_existing'):
        print("  - Пропускать существующие фразы")
    if options.get('integrate_minus'):
        print("  - Интегрировать минус-слова")
    if options.get('add_plus'):
        print("  - Добавлять '+' оператор")

    print("\n✅ Настройки получены успешно!")
    print("=" * 70)


def main():
    app = QApplication(sys.argv)

    dialog = BatchCollectDialog()
    dialog.collect_requested.connect(on_collect_requested)

    # Предзаполняем тестовыми фразами
    test_phrases = """купить телефон
ремонт квартиры
заказать пиццу
доставка цветов
онлайн курсы программирования"""

    dialog.phrases_edit.setPlainText(test_phrases)

    result = dialog.exec()

    if result:
        print("\n✅ Диалог закрыт с подтверждением")
    else:
        print("\n❌ Диалог отменён")

    sys.exit(0)


if __name__ == "__main__":
    main()
