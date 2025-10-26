#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Менеджер многопоточного парсинга для KeySet
Управляет одновременным запуском нескольких парсеров с разными профилями
"""

import asyncio
import base64
import json
import logging
import shutil
import sqlite3
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import threading
from queue import Queue

from playwright.async_api import BrowserContext
from sqlalchemy import select
import win32crypt

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    AESGCM_AVAILABLE = True
except ImportError:  # pragma: no cover - safety fallback
    AESGCM_AVAILABLE = False

try:
    from ..core.db import SessionLocal
    from ..core.models import Account
except ImportError:  # pragma: no cover - fallback for scripts
    from core.db import SessionLocal  # type: ignore
    from core.models import Account  # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parents[2]
KEYSET_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = KEYSET_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR = KEYSET_ROOT / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_DIR / 'multiparser.log'), encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('MultiParser')

_MASTER_KEY_CACHE: Dict[Path, Optional[bytes]] = {}


def _get_chrome_master_key(profile_path: Path, logger_obj: logging.Logger) -> Optional[bytes]:
    """Извлечь мастер-ключ Chrome для расшифровки v10 cookie."""
    resolved_path = profile_path.resolve()
    if resolved_path in _MASTER_KEY_CACHE:
        return _MASTER_KEY_CACHE[resolved_path]

    local_state_path = resolved_path / "Local State"
    if not local_state_path.exists():
        logger_obj.debug(f"[{profile_path.name}] Local State не найден по пути {local_state_path}")
        _MASTER_KEY_CACHE[resolved_path] = None
        return None

    try:
        data = json.loads(local_state_path.read_text(encoding="utf-8"))
        encrypted_key_b64 = data.get("os_crypt", {}).get("encrypted_key")
        if not encrypted_key_b64:
            logger_obj.debug(f"[{profile_path.name}] В Local State отсутствует os_crypt.encrypted_key")
            _MASTER_KEY_CACHE[resolved_path] = None
            return None
        encrypted_key = base64.b64decode(encrypted_key_b64)
        if encrypted_key.startswith(b"DPAPI"):
            encrypted_key = encrypted_key[5:]
        master_key = win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
        _MASTER_KEY_CACHE[resolved_path] = master_key
        return master_key
    except Exception as exc:  # pragma: no cover - диагностический путь
        logger_obj.warning(f"[{profile_path.name}] Не удалось получить мастер-ключ Chrome: {exc}")
        _MASTER_KEY_CACHE[resolved_path] = None
        return None


def _decrypt_chrome_value(
    encrypted_value: bytes,
    profile_path: Path,
    logger_obj: logging.Logger,
    master_key: Optional[bytes],
) -> str:
    """Расшифровать значение cookie из Chrome (Windows DPAPI)."""
    if not encrypted_value:
        return ""
    try:
        if encrypted_value.startswith(b'v10') or encrypted_value.startswith(b'v11'):
            if not AESGCM_AVAILABLE:
                logger_obj.debug(f"[{profile_path.name}] AESGCM недоступен, не удалось расшифровать cookie v10")
                return ""
            if not master_key:
                master_key = _get_chrome_master_key(profile_path, logger_obj)
                if not master_key:
                    return ""
            nonce = encrypted_value[3:15]
            ciphertext = encrypted_value[15:-16]
            tag = encrypted_value[-16:]
            aesgcm = AESGCM(master_key)
            decrypted = aesgcm.decrypt(nonce, ciphertext + tag, None)
        else:
            decrypted = win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1]
        return decrypted.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _extract_profile_cookies(profile_path: Path, logger_obj: logging.Logger) -> List[Dict[str, Any]]:
    """Вытащить куки из Chrome-профиля на диске и привести в формат Playwright."""
    candidates = [
        profile_path / "Default" / "Network" / "Cookies",
        profile_path / "Default" / "Cookies",
        profile_path / "Cookies",
        profile_path / "Network" / "Cookies",
    ]
    source_path: Optional[Path] = None
    for candidate in candidates:
        if candidate.exists():
            source_path = candidate
            break

    if not source_path:
        # fallback: ищем любой файл Cookies в структуре профиля
        try:
            for candidate in profile_path.rglob("Cookies"):
                if candidate.is_file():
                    source_path = candidate
                    break
        except Exception as exc:  # pragma: no cover - защитный путь
            logger_obj.debug(f"[{profile_path.name}] Ошибка при поиске Cookies: {exc}")

    if not source_path:
        logger_obj.info(f"[{profile_path.name}] Файл Cookies не найден в профиле")
        return []

    tmp_dir = Path(tempfile.gettempdir())
    tmp_copy = tmp_dir / f"cookies_{profile_path.name}_{int(time.time())}.db"
    try:
        shutil.copy2(source_path, tmp_copy)
    except Exception as exc:
        logger_obj.error(f"[{profile_path.name}] Не удалось скопировать Cookies: {exc}")
        return []

    cookies: List[Dict[str, Any]] = []
    try:
        conn = sqlite3.connect(tmp_copy)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT host_key, name, value, encrypted_value, path, expires_utc,
                   is_secure, is_httponly, samesite
            FROM cookies
            """
        )
        rows = cursor.fetchall()
        conn.close()
    except Exception as exc:
        logger_obj.error(f"[{profile_path.name}] Ошибка чтения Cookies: {exc}")
        tmp_copy.unlink(missing_ok=True)
        return []

    master_key = _get_chrome_master_key(profile_path, logger_obj)

    for host_key, name, value, encrypted_value, path_value, expires_utc, is_secure, is_httponly, same_site in rows:
        if not name:
            continue
        if not value and encrypted_value:
            if master_key is None and (encrypted_value.startswith(b'v10') or encrypted_value.startswith(b'v11')):
                master_key = _get_chrome_master_key(profile_path, logger_obj)
            value = _decrypt_chrome_value(encrypted_value, profile_path, logger_obj, master_key)
        if not value:
            continue
        host = host_key or ""
        if "yandex" not in host and ".ya" not in host:
            continue

        cookie_entry: Dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": host_key if host_key.startswith(".") else f".{host_key}",
            "path": path_value or "/",
            "secure": bool(is_secure),
            "httpOnly": bool(is_httponly),
        }
        if expires_utc and expires_utc != 0:
            # Преобразуем Windows epoch (микросекунды с 1601 г.)
            expires = int(expires_utc / 1_000_000 - 11644473600)
            if expires > 0:
                cookie_entry["expires"] = expires
        same_site_map = {0: "None", 1: "Lax", 2: "Strict"}
        if same_site in same_site_map:
            cookie_entry["sameSite"] = same_site_map[same_site]
        cookies.append(cookie_entry)

    tmp_copy.unlink(missing_ok=True)
    return cookies

async def load_cookies_from_db_to_context(
    context: BrowserContext,
    account_name: str,
    logger_obj: Optional[logging.Logger] = None,
) -> bool:
    """Загрузить куки из БД и добавить их в контекст браузера."""
    log = logger_obj or logger
    try:
        with SessionLocal() as session:
            stmt = select(Account).where(Account.name == account_name)
            account = session.execute(stmt).scalar_one_or_none()
            if not account or not getattr(account, "cookies", None):
                log.info(f"[{account_name}] Куки в БД не найдены")
                return False

            raw_cookies = account.cookies
            cookies_payload: Any
            try:
                cookies_payload = json.loads(raw_cookies) if isinstance(raw_cookies, str) else raw_cookies
            except json.JSONDecodeError:
                log.error(f"[{account_name}] Некорректный формат куки в БД")
                return False

            if not isinstance(cookies_payload, list):
                log.error(f"[{account_name}] Ожидался список куки, получено {type(cookies_payload)}")
                return False

            if not cookies_payload:
                log.info(f"[{account_name}] Список куки пуст")
                return False

            await context.add_cookies(cookies_payload)
            log.info(f"[{account_name}] ✓ Загружено {len(cookies_payload)} куки из БД")
            return True
    except Exception as exc:
        log.error(f"[{account_name}] Ошибка загрузки куки из БД: {exc}")
        return False


async def save_cookies_to_db(
    account_name: str,
    context: BrowserContext,
    logger_obj: Optional[logging.Logger] = None,
) -> None:
    """Сохранить текущие куки из контекста браузера в базу данных."""
    log = logger_obj or logger
    try:
        cookies = await context.cookies()
        with SessionLocal() as session:
            stmt = select(Account).where(Account.name == account_name)
            account = session.execute(stmt).scalar_one_or_none()
            if not account:
                log.warning(f"[{account_name}] Не удалось найти аккаунт для сохранения куки")
                return
            account.cookies = json.dumps(cookies, ensure_ascii=False)
            session.commit()
            log.info(f"[{account_name}] ✓ Куки сохранены в БД ({len(cookies)} шт)")
    except Exception as exc:
        log.error(f"[{account_name}] Ошибка сохранения куки в БД: {exc}")


async def load_cookies_from_profile_to_context(
    context: BrowserContext,
    account_name: str,
    profile_path: Path,
    logger_obj: Optional[logging.Logger] = None,
    persist: bool = True,
) -> bool:
    """
    Загрузить куки из локального Chrome-профиля и добавить их в контекст браузера.

    Args:
        context: активный контекст Playwright
        account_name: имя аккаунта в KeySet
        profile_path: путь к профилю Chrome на диске
        logger_obj: кастомный логгер (опционально)
        persist: дополнительно сохранить загруженные куки в БД

    Returns:
        True если куки успешно добавлены, иначе False
    """
    log = logger_obj or logger
    path_obj = Path(profile_path)

    cookies = _extract_profile_cookies(path_obj, log)
    if not cookies:
        log.info(f"[{account_name}] Куки в профиле {path_obj} не найдены")
        return False

    try:
        await context.add_cookies(cookies)
        log.info(f"[{account_name}] ✓ Загружено {len(cookies)} куки из профиля {path_obj.name}")
    except Exception as exc:
        log.error(f"[{account_name}] Ошибка добавления куки из профиля: {exc}")
        return False

    if persist:
        try:
            await save_cookies_to_db(account_name, context, log)
        except Exception as exc:
            log.warning(f"[{account_name}] Не удалось сохранить куки из профиля в БД: {exc}")

    return True

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
        self.results_dir = RESULTS_DIR
        self.results_dir.mkdir(parents=True, exist_ok=True)
        
        self.logs_dir = LOG_DIR
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
                turbo_path = PROJECT_ROOT
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
            'profile_path': str(PROJECT_ROOT / 'profiles/profile1'),
            'proxy': 'http://user:pass@proxy1.com:8080'
        },
        {
            'email': 'test2@example.com',
            'profile_path': str(PROJECT_ROOT / 'profiles/profile2'),
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


__all__ = [
    "MultiParserManager",
    "load_cookies_from_db_to_context",
    "save_cookies_to_db",
    "load_cookies_from_profile_to_context",
]
