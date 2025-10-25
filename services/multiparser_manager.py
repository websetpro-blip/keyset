#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Менеджер многопоточного парсинга для KeySet
Управляет одновременным запуском нескольких парсеров с разными профилями
"""

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import threading
from queue import Queue

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('C:/AI/yandex/keyset/logs/multiparser.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('MultiParser')


@dataclass
class ParsingTask:
    """Задача парсинга для одного профиля"""
    task_id: str
    profile_email: str
    profile_path: Path
    proxy_uri: Optional[str]
    phrases: List[str]
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, running, completed, failed
    results: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    progress: int = 0
    
    def to_dict(self) -> dict:
        """Конвертация в словарь для сериализации"""
        return {
            'task_id': self.task_id,
            'profile_email': self.profile_email,
            'profile_path': str(self.profile_path),
            'proxy_uri': self.proxy_uri,
            'phrases_count': len(self.phrases),
            'status': self.status,
            'progress': self.progress,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'error_message': self.error_message,
            'results_count': len(self.results),
        }


class MultiParserManager:
    """Менеджер для управления множественными парсерами"""
    
    def __init__(self, max_workers: int = 5):
        """
        Args:
            max_workers: Максимальное количество одновременно работающих парсеров
        """
        self.max_workers = max_workers
        self.tasks: Dict[str, ParsingTask] = {}
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.results_queue = Queue()
        self.log_queue = Queue()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        
        # Директории для сохранения результатов
        self.results_dir = Path("C:/AI/yandex/keyset/results")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        self.logs_dir = Path("C:/AI/yandex/keyset/logs")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        
    def create_task(
        self, 
        profile_email: str,
        profile_path: str,
        proxy_uri: Optional[str],
        phrases: List[str]
    ) -> ParsingTask:
        """Создать новую задачу парсинга"""
        task_id = f"{profile_email}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        task = ParsingTask(
            task_id=task_id,
            profile_email=profile_email,
            profile_path=Path(profile_path),
            proxy_uri=proxy_uri,
            phrases=phrases
        )
        
        with self._lock:
            self.tasks[task_id] = task
            
        logger.info(f"Created task {task_id} for {profile_email} with {len(phrases)} phrases")
        return task
        
    def submit_tasks(self, profiles: List[Dict], phrases: List[str]) -> List[str]:
        """
        Отправить задачи на выполнение
        
        Args:
            profiles: Список профилей с данными
            phrases: Список фраз для парсинга
            
        Returns:
            Список task_id созданных задач
        """
        task_ids = []
        futures = {}
        
        for profile in profiles:
            # Создаем задачу
            task = self.create_task(
                profile_email=profile['email'],
                profile_path=profile['profile_path'],
                proxy_uri=profile.get('proxy'),
                phrases=phrases
            )
            task_ids.append(task.task_id)
            
            # Отправляем на выполнение
            future = self.executor.submit(self._run_parser_task, task)
            futures[future] = task.task_id
            
        # Запускаем обработку результатов в отдельном потоке
        threading.Thread(
            target=self._process_futures,
            args=(futures,),
            daemon=True
        ).start()
        
        return task_ids
        
    def _run_parser_task(self, task: ParsingTask) -> Dict[str, Any]:
        """Запустить парсер для одной задачи"""
        try:
            # Обновляем статус
            with self._lock:
                task.status = "running"
                task.started_at = datetime.now()
                
            self._log(f"Starting parser for {task.profile_email}", level="INFO", task_id=task.task_id)
            
            # Проверяем профиль
            if not task.profile_path.exists():
                raise FileNotFoundError(f"Profile not found: {task.profile_path}")
                
            # Создаем новый event loop для этого потока
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                # Импортируем парсер
                import sys
                turbo_path = Path("C:/AI/yandex")
                if str(turbo_path) not in sys.path:
                    sys.path.insert(0, str(turbo_path))
                    
                from turbo_parser_10tabs import turbo_parser_10tabs
                
                # Запускаем парсинг
                results = loop.run_until_complete(
                    turbo_parser_10tabs(
                        account_name=task.profile_email,
                        profile_path=task.profile_path,
                        phrases=task.phrases,
                        headless=False,
                        proxy_uri=task.proxy_uri,
                    )
                )
                
                # Обновляем результаты
                with self._lock:
                    task.results = results
                    task.status = "completed"
                    task.completed_at = datetime.now()
                    task.progress = 100
                    
                self._log(
                    f"Parser completed for {task.profile_email}: {len(results)} results",
                    level="SUCCESS",
                    task_id=task.task_id
                )
                
                # Сохраняем результаты
                self._save_results(task)
                
                return results
                
            finally:
                loop.close()
                
        except Exception as e:
            with self._lock:
                task.status = "failed"
                task.error_message = str(e)
                task.completed_at = datetime.now()
                
            self._log(
                f"Parser failed for {task.profile_email}: {str(e)}",
                level="ERROR",
                task_id=task.task_id
            )
            
            raise
            
    def _process_futures(self, futures: Dict):
        """Обработка завершенных задач"""
        for future in as_completed(futures):
            task_id = futures[future]
            task = self.tasks.get(task_id)
            
            try:
                result = future.result()
                self.results_queue.put({
                    'task_id': task_id,
                    'status': 'completed',
                    'results': result
                })
            except Exception as e:
                self.results_queue.put({
                    'task_id': task_id,
                    'status': 'failed',
                    'error': str(e)
                })
                
    def _save_results(self, task: ParsingTask):
        """Сохранить результаты задачи в файл"""
        try:
            # Создаем директорию для результатов профиля
            profile_dir = self.results_dir / task.profile_email.replace('@', '_at_')
            profile_dir.mkdir(parents=True, exist_ok=True)
            
            # Сохраняем результаты
            results_file = profile_dir / f"results_{task.task_id}.json"
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'task_info': task.to_dict(),
                    'results': task.results,
                    'phrases': task.phrases,
                }, f, ensure_ascii=False, indent=2)
                
            self._log(
                f"Results saved to {results_file}",
                level="INFO",
                task_id=task.task_id
            )
            
            # Также сохраняем в CSV для удобства
            csv_file = profile_dir / f"results_{task.task_id}.csv"
            self._save_as_csv(task, csv_file)
            
        except Exception as e:
            self._log(
                f"Failed to save results: {str(e)}",
                level="ERROR",
                task_id=task.task_id
            )
            
    def _save_as_csv(self, task: ParsingTask, csv_file: Path):
        """Сохранить результаты в CSV"""
        try:
            import csv
            
            with open(csv_file, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                writer.writerow(['Phrase', 'WS', 'QWS', 'BWS', 'Profile', 'Timestamp'])
                
                for phrase, freq_data in task.results.items():
                    if isinstance(freq_data, dict):
                        ws = freq_data.get('ws', 0)
                        qws = freq_data.get('qws', 0)
                        bws = freq_data.get('bws', 0)
                    else:
                        ws = freq_data
                        qws = 0
                        bws = 0
                        
                    writer.writerow([
                        phrase,
                        ws,
                        qws,
                        bws,
                        task.profile_email,
                        task.completed_at.isoformat() if task.completed_at else ''
                    ])
                    
            self._log(
                f"CSV saved to {csv_file}",
                level="INFO",
                task_id=task.task_id
            )
            
        except Exception as e:
            self._log(
                f"Failed to save CSV: {str(e)}",
                level="ERROR",
                task_id=task.task_id
            )
            
    def _log(self, message: str, level: str = "INFO", task_id: Optional[str] = None):
        """Логирование с поддержкой очереди"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'task_id': task_id
        }
        
        self.log_queue.put(log_entry)
        
        # Также логируем через logger
        if level == "ERROR":
            logger.error(message)
        elif level == "SUCCESS":
            logger.info(f"✅ {message}")
        else:
            logger.info(message)
            
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Получить статус задачи"""
        with self._lock:
            task = self.tasks.get(task_id)
            if task:
                return task.to_dict()
        return None
        
    def get_all_tasks_status(self) -> List[Dict]:
        """Получить статус всех задач"""
        with self._lock:
            return [task.to_dict() for task in self.tasks.values()]
            
    def get_logs(self, limit: int = 100) -> List[Dict]:
        """Получить последние логи"""
        logs = []
        while not self.log_queue.empty() and len(logs) < limit:
            try:
                logs.append(self.log_queue.get_nowait())
            except:
                break
        return logs
        
    def get_results(self, limit: int = 100) -> List[Dict]:
        """Получить последние результаты"""
        results = []
        while not self.results_queue.empty() and len(results) < limit:
            try:
                results.append(self.results_queue.get_nowait())
            except:
                break
        return results
        
    def stop(self):
        """Остановить менеджер"""
        self._stop_event.set()
        self.executor.shutdown(wait=False)
        logger.info("MultiParserManager stopped")
        
    def wait_for_completion(self, task_ids: List[str], timeout: Optional[int] = None) -> bool:
        """
        Ждать завершения задач
        
        Returns:
            True если все задачи завершены, False если истек таймаут
        """
        start_time = time.time()
        
        while True:
            with self._lock:
                all_completed = all(
                    self.tasks[task_id].status in ['completed', 'failed']
                    for task_id in task_ids
                    if task_id in self.tasks
                )
                
            if all_completed:
                return True
                
            if timeout and (time.time() - start_time) > timeout:
                return False
                
            time.sleep(1)
            
    def merge_results(self, task_ids: List[str]) -> Dict[str, Any]:
        """Объединить результаты нескольких задач"""
        merged = {}
        
        with self._lock:
            for task_id in task_ids:
                if task_id in self.tasks:
                    task = self.tasks[task_id]
                    if task.status == 'completed' and task.results:
                        # Объединяем результаты
                        for phrase, freq_data in task.results.items():
                            if phrase not in merged:
                                merged[phrase] = {
                                    'profiles': {},
                                    'total': {'ws': 0, 'qws': 0, 'bws': 0}
                                }
                                
                            # Сохраняем результат для профиля
                            merged[phrase]['profiles'][task.profile_email] = freq_data
                            
                            # Суммируем общие результаты (берем максимум)
                            if isinstance(freq_data, dict):
                                for key in ['ws', 'qws', 'bws']:
                                    val = freq_data.get(key, 0)
                                    if isinstance(val, (int, float)):
                                        merged[phrase]['total'][key] = max(
                                            merged[phrase]['total'][key],
                                            val
                                        )
                            else:
                                merged[phrase]['total']['ws'] = max(
                                    merged[phrase]['total']['ws'],
                                    int(freq_data) if freq_data else 0
                                )
                                
        return merged


# Пример использования
if __name__ == "__main__":
    # Тестовый запуск
    manager = MultiParserManager(max_workers=3)
    
    # Тестовые профили
    test_profiles = [
        {
            'email': 'test1@example.com',
            'profile_path': 'C:/AI/yandex/profiles/profile1',
            'proxy': 'http://user:pass@proxy1.com:8080'
        },
        {
            'email': 'test2@example.com',
            'profile_path': 'C:/AI/yandex/profiles/profile2',
            'proxy': 'http://user:pass@proxy2.com:8080'
        }
    ]
    
    # Тестовые фразы
    test_phrases = [
        'купить телефон',
        'ремонт квартиры',
        'доставка еды'
    ]
    
    # Запускаем парсинг
    task_ids = manager.submit_tasks(test_profiles, test_phrases)
    
    print(f"Submitted {len(task_ids)} tasks")
    
    # Ждем завершения
    if manager.wait_for_completion(task_ids, timeout=300):
        print("All tasks completed!")
        
        # Получаем объединенные результаты
        merged = manager.merge_results(task_ids)
        print(f"Merged results: {len(merged)} phrases")
        
        # Выводим статусы
        for status in manager.get_all_tasks_status():
            print(f"Task {status['task_id']}: {status['status']}")
    else:
        print("Timeout waiting for tasks")
        
    manager.stop()
