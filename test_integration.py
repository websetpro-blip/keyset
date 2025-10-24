#!/usr/bin/env python3
"""
Тест интеграции TurboParserGUI с IntegrationService и GUI
"""

import sys
import asyncio
from pathlib import Path

# Добавляем путь к keyset в sys.path
keyset_path = Path(__file__).parent
if str(keyset_path) not in sys.path:
    sys.path.insert(0, str(keyset_path))

from services.integration_service import IntegrationService
from workers.turbo_parser_gui_wrapper import TurboParserGUI


class TestIntegration:
    """Тестовый класс для проверки интеграции"""
    
    def __init__(self):
        self.results_received = []
        self.progress_updates = []
        self.log_messages = []
    
    def on_result(self, phrase: str, result: dict):
        """Callback для получения результатов"""
        self.results_received.append((phrase, result))
        print(f"[RESULT] {phrase}: {result}")
    
    def on_progress(self, current: int, total: int):
        """Callback для прогресса"""
        self.progress_updates.append((current, total))
        percent = int((current / total) * 100) if total > 0 else 0
        print(f"[PROGRESS] {current}/{total} ({percent}%)")
    
    def on_log(self, message: str):
        """Callback для логов"""
        self.log_messages.append(message)
        print(f"[LOG] {message}")
    
    def on_finished(self, results: list):
        """Callback завершения"""
        print(f"[FINISHED] Получено {len(results)} результатов")
        print(f"[FINISHED] Всего логов: {len(self.log_messages)}")
        print(f"[FINISHED] Всего обновлений прогресса: {len(self.progress_updates)}")
    
    def on_error(self, error: str):
        """Callback ошибки"""
        print(f"[ERROR] {error}")
    
    async def test_integration_service(self):
        """Тест IntegrationService"""
        print("=" * 60)
        print("ТЕСТ 1: IntegrationService")
        print("=" * 60)
        
        # Создаем IntegrationService
        integration = IntegrationService()
        
        # Подключаем callbacks
        integration.onResult.connect(self.on_result)
        integration.onProgress.connect(self.on_progress)
        integration.onLog.connect(self.on_log)
        integration.onFinished.connect(self.on_finished)
        integration.onError.connect(self.on_error)
        
        # Тестовые фразы
        test_phrases = [
            "ремонт квартир",
            "отделка стен",
            "покраска потолков"
        ]
        
        try:
            # Запускаем парсинг
            integration.start_parsing(
                phrases=test_phrases,
                account_name="wordstat_main",
                region=225,
                modes={"ws": True, "qws": False, "bws": False},
                headless=True  # Без браузера для теста
            )
            
            # Ждём немного для обработки
            await asyncio.sleep(2)
            
            # Останавливаем
            integration.stop_parsing()
            
            # Проверяем результаты
            print(f"\nРезультаты теста:")
            print(f"- Получено результатов: {len(self.results_received)}")
            print(f"- Обновлений прогресса: {len(self.progress_updates)}")
            print(f"- Логов: {len(self.log_messages)}")
            
            return True
            
        except Exception as e:
            print(f"Ошибка теста IntegrationService: {e}")
            return False
    
    async def test_parser_gui_wrapper(self):
        """Тест TurboParserGUI напрямую"""
        print("\n" + "=" * 60)
        print("ТЕСТ 2: TurboParserGUI напрямую")
        print("=" * 60)
        
        # Создаем парсер
        parser = TurboParserGUI(
            on_result=self.on_result,
            on_progress=self.on_progress,
            on_log=self.on_log
        )
        
        # Тестовые фразы
        test_phrases = [
            "ремонт квартир",
            "отделка стен"
        ]
        
        try:
            # Запускаем парсинг
            results = await parser.parse_phrases(
                account="wordstat_main",
                profile_path="C:/AI/yandex/.profiles/wordstat_main",
                phrases=test_phrases,
                modes={"ws": True, "qws": False, "bws": False},
                region=225,
                proxy_uri=None
            )
            
            # Останавливаем
            await parser.stop()
            
            # Проверяем результаты
            print(f"\nРезультаты теста:")
            print(f"- Получено результатов: {len(self.results_received)}")
            print(f"- Обновлений прогресса: {len(self.progress_updates)}")
            print(f"- Логов: {len(self.log_messages)}")
            
            return True
            
        except Exception as e:
            print(f"Ошибка теста TurboParserGUI: {e}")
            return False
    
    async def run_tests(self):
        """Запуск всех тестов"""
        print("НАЧАЛО ТЕСТОВ ИНТЕГРАЦИИ")
        print("=" * 60)
        
        # Тест 1: IntegrationService
        test1_result = await self.test_integration_service()
        
        # Очищаем результаты между тестами
        self.results_received.clear()
        self.progress_updates.clear()
        self.log_messages.clear()
        
        # Тест 2: TurboParserGUI напрямую
        test2_result = await self.test_parser_gui_wrapper()
        
        # Итоги
        print("\n" + "=" * 60)
        print("ИТОГИ ТЕСТОВ")
        print("=" * 60)
        print(f"IntegrationService: {'✅ УСПЕХ' if test1_result else '❌ ОШИБКА'}")
        print(f"TurboParserGUI: {'✅ УСПЕХ' if test2_result else '❌ ОШИБКА'}")
        
        if test1_result and test2_result:
            print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
            print("Интеграция готова к использованию в GUI")
        else:
            print("\n❌ ЧАСТЬ ТЕСТОВ НЕ ПРОЙДЕНА")
            print("Нужно исправить ошибки перед использованием")
        
        return test1_result and test2_result


async def main():
    """Главная функция теста"""
    tester = TestIntegration()
    success = await tester.run_tests()
    
    if success:
        print("\n🎉 Интеграция готова к использованию!")
        print("Теперь можно запускать GUI и тестировать полный цикл")
    else:
        print("\n⚠️  Интеграция требует доработки")
        print("Проверьте ошибки и исправьте их")
    
    return success


if __name__ == "__main__":
    # Запуск тестов
    result = asyncio.run(main())
    sys.exit(0 if result else 1)