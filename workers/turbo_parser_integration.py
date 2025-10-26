# -*- coding: utf-8 -*-
"""ТУРБО ПАРСЕР ИНТЕГРАЦИЯ ДЛЯ SEMTOOL
Интегрирует наш парсер 195.9 фраз/мин в KeySet
Основан на parser_final_130plus.py + рекомендации GPT
"""

import asyncio
import time
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from urllib.parse import quote

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

try:
    from ..utils.proxy import proxy_to_playwright
    from ..utils.text_fix import WORDSTAT_FETCH_NORMALIZER_SCRIPT, fix_mojibake
    from ..core.db import SessionLocal
    from ..core.models import Account
    from ..services.proxy_manager import ProxyManager, proxy_preflight, Proxy
    from .visual_browser_manager import VisualBrowserManager, BrowserStatus
    from .auto_auth_handler import AutoAuthHandler
except ImportError:
    from utils.proxy import proxy_to_playwright
    from utils.text_fix import WORDSTAT_FETCH_NORMALIZER_SCRIPT, fix_mojibake
    from core.db import SessionLocal
    from core.models import Account
    from services.proxy_manager import ProxyManager, proxy_preflight, Proxy
    from .visual_browser_manager import VisualBrowserManager, BrowserStatus
    from .auto_auth_handler import AutoAuthHandler


def _wire_logging(page: Page) -> None:
    page.on("requestfailed", lambda r: print(f"[TURBO][NET] FAIL {r.url} {r.failure}"))
    page.on("console", lambda m: print(f"[TURBO][CONSOLE] {m.type}: {m.text}"))


def _ensure_wired(page: Page) -> None:
    if getattr(page, "_turbo_ws_wired", False):
        return
    _wire_logging(page)
    setattr(page, "_turbo_ws_wired", True)


_WORDSTAT_ENCODINGS: tuple[str, ...] = ("utf-8", "windows-1251", "cp1251", "latin-1")


async def _parse_wordstat_json(response) -> Optional[dict]:
    """Считывает тело ответа Wordstat с учётом charset."""
    try:
        raw = await response.body()
    except Exception:
        raw = b""

    content_type = ""
    try:
        content_type = response.headers.get("content-type", "")
    except Exception:
        content_type = ""

    encodings: list[str] = []
    match = re.search(r"charset=([^;]+)", content_type or "", flags=re.IGNORECASE)
    if match:
        enc = match.group(1).strip().lower()
        if enc:
            encodings.append(enc)
    for enc in _WORDSTAT_ENCODINGS:
        if enc not in encodings:
            encodings.append(enc)

    last_exc: Optional[Exception] = None
    for encoding in encodings:
        try:
            text = raw.decode(encoding, errors="strict")
            return json.loads(text)
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc:
        print(f"[TURBO] Не удалось декодировать ответ Wordstat: {last_exc}")
    return None


def _normalize_wordstat_payload(data: Dict[str, Any]) -> None:
    """Преобразует tableData → items/related, чтобы код дальше не ломался."""
    if not isinstance(data, dict):
        return
    table = data.get("table")
    if not isinstance(table, dict):
        return
    table_data = table.get("tableData")
    if not isinstance(table_data, dict):
        return

    def _norm(entries: Optional[List[Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in entries or []:
            phrase: str = ""
            count: Any = 0
            if isinstance(item, dict):
                phrase = (
                    item.get("text")
                    or item.get("phrase")
                    or item.get("key")
                    or item.get("title")
                    or ""
                )
                count = item.get("value", item.get("count", item.get("freq", 0)))
            elif isinstance(item, (list, tuple)) and item:
                phrase = str(item[0] or "")
                count = item[1] if len(item) > 1 else 0
            elif isinstance(item, str):
                phrase = item
                count = 0
            try:
                value = int(str(count).replace(" ", ""))
            except Exception:
                value = 0
            phrase = phrase.strip()
            if phrase:
                normalized.append({"phrase": phrase, "count": value})
        return normalized

    if not table.get("items"):
        table["items"] = _norm(table_data.get("popular"))
    if not table.get("related"):
        table["related"] = _norm(table_data.get("associations") or table_data.get("similar"))


def _extract_phrase_from_request(response) -> Optional[str]:
    """Достаёт исходный searchValue из тела POST."""
    try:
        payload = response.request.post_data
    except Exception:
        payload = None
    if not payload:
        return None
    try:
        blob = json.loads(payload)
        phrase = blob.get("searchValue") or blob.get("query") or ""
        if isinstance(phrase, str):
            phrase = fix_mojibake(phrase).strip()
        else:
            phrase = ""
        return phrase or None
    except Exception:
        return None


class AIMDController:
    """AIMD регулятор скорости для избежания банов"""

    def __init__(self):
        self.delay_ms = 50
        self.min_delay = 30
        self.max_delay = 300
        self.success_count = 0
        self.error_count = 0

    def on_success(self) -> None:
        """При успехе уменьшаем задержку"""
        self.success_count += 1
        if self.success_count >= 10:
            self.delay_ms = max(self.min_delay, self.delay_ms - 10)
            self.success_count = 0

    def on_error(self) -> None:
        """При ошибке увеличиваем задержку"""
        self.error_count += 1
        self.delay_ms = min(self.max_delay, self.delay_ms * 1.5)

    def get_delay(self) -> float:
        """Текущая задержка в секундах"""
        return self.delay_ms / 1000.0


class TurboWordstatParser:
    """Турбо парсер Wordstat для KeySet"""

    def __init__(self, account: Optional[Account] = None, headless: bool = False, visual_mode: bool = True):
        self.account = account
        self.headless = headless
        self.visual_mode = visual_mode
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.pages: List[Page] = []
        self.results: Dict[str, Any] = {}
        self.aimd = AIMDController()
        self.num_tabs = 10
        self.num_browsers = 1
        self.visual_manager = None
        self.db_path = Path("C:/AI/yandex/keyset/data/keyset.db")
        self.auth_handler = AutoAuthHandler()
        self.proxy_manager = ProxyManager.instance()
        self._proxy_item: Optional[Proxy] = None
        self._preflight_info: Optional[dict] = None

        if self.account:
            self._load_auth_data()

        self.total_processed = 0
        self.total_errors = 0
        self.start_time: Optional[float] = None

    def _load_auth_data(self) -> None:
        """Загружаем данные авторизации из accounts.json"""
        try:
            accounts_json_path = Path("C:/AI/yandex/keyset/configs/accounts.json")
            if not accounts_json_path.exists():
                accounts_json_path = Path("C:/AI/yandex/configs/accounts.json")
            if not accounts_json_path.exists():
                accounts_json_path = Path("C:/AI/accounts.json")
            if accounts_json_path.exists():
                with accounts_json_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                for acc_data in data:
                    if acc_data.get("login") == getattr(self.account, "name", None):
                        self.account.password = acc_data.get("password", getattr(self.account, "password", ""))
                        self.account.secret_answer = acc_data.get("secret_answer", getattr(self.account, "secret_answer", ""))
                        break
        except Exception as exc:
            print(f"[AUTH] Ошибка чтения accounts.json: {exc}")

    async def init_browser(self) -> None:
        """Запуск persistent контекста Chrome с привязанным прокси"""
        from ..services.proxy_manager import proxy_preflight

        print("[TURBO] Запуск браузера через persistent Playwright...")
        self.playwright = await async_playwright().start()

        base_profile = Path("C:/AI/yandex")
        profile_path = Path(self.account.profile_path or f".profiles/{self.account.name}") if self.account else Path(".profiles/default")
        if not profile_path.is_absolute():
            profile_path = base_profile / profile_path
        profile_path = profile_path.resolve()
        profile_path.parent.mkdir(parents=True, exist_ok=True)

        proxy_obj: Optional[Proxy] = None
        if self.account and getattr(self.account, "proxy_id", None):
            proxy_obj = self.proxy_manager.acquire(self.account.proxy_id)
            self._proxy_item = proxy_obj
        elif self.account and getattr(self.account, "proxy", None):
            parsed = proxy_to_playwright(self.account.proxy)
            if parsed and parsed.get("server"):
                server_value = parsed["server"]
                scheme = server_value.split("://", 1)[0] if "://" in server_value else "http"
                proxy_obj = Proxy(
                    id="legacy",
                    label="legacy",
                    type=scheme,
                    server=server_value,
                    username=parsed.get("username"),
                    password=parsed.get("password"),
                )

        preflight = proxy_preflight(proxy_obj) if proxy_obj else {"ok": True, "ip": None, "error": None}
        if not preflight.get("ok", False):
            raise RuntimeError(f"Proxy preflight failed: {preflight.get('error')}")
        self._preflight_info = preflight
        if preflight.get("ip"):
            print(f"[TURBO] Proxy preflight ip={preflight['ip']}")

        proxy_payload = proxy_obj.playwright_config() if proxy_obj else None
        chrome_exe = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        launch_kwargs: Dict[str, Any] = {
            "user_data_dir": str(profile_path),
            "headless": self.headless,
            "proxy": proxy_payload,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        }
        if not chrome_exe.exists():
            launch_kwargs["channel"] = "chrome"
        else:
            launch_kwargs["executable_path"] = str(chrome_exe)

        if proxy_obj and proxy_obj.type.lower().startswith("socks"):
            host = proxy_obj.server.split("://")[-1].split(":")[0]
            launch_kwargs["args"].append(f"--host-resolver-rules=MAP * ~NOTFOUND , EXCLUDE {host}")

        context = await self.playwright.chromium.launch_persistent_context(**launch_kwargs)
        await context.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
        for existing_page in context.pages:
            await existing_page.add_init_script(script=WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            try:
                await existing_page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            except Exception:
                pass
        self.context = context
        self.browser = context.browser

        if not context.pages:
            page = await context.new_page()
        else:
            page = context.pages[0]
        _ensure_wired(page)
        try:
            await page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
        except Exception:
            pass
        await page.goto(
            "https://wordstat.yandex.ru/#!/?region=225",
            wait_until="domcontentloaded",
            timeout=30000,
        )
        self.pages = [page]

    async def setup_tabs(self) -> None:
        print(f"[TURBO] Подготовка {self.num_tabs} вкладок...")
        existing_pages = self.context.pages
        for i in range(len(existing_pages), self.num_tabs):
            print(f"[TURBO] Создаю вкладку {i + 1}...")
            page = await self.context.new_page()
            _ensure_wired(page)
            try:
                await page.evaluate(WORDSTAT_FETCH_NORMALIZER_SCRIPT)
            except Exception:
                pass
            existing_pages.append(page)
        self.pages = existing_pages[:self.num_tabs]
        self.page_mapping: Dict[int, Page] = {}
        print(f"[TURBO] Загружаем Wordstat на {len(self.pages)} вкладках...")
        for i, page in enumerate(self.pages):
            _ensure_wired(page)
            self.page_mapping[i] = page
            if "wordstat.yandex.ru" not in page.url:
                try:
                    await page.goto(
                        "https://wordstat.yandex.ru/#!/?region=225",
                        wait_until="domcontentloaded",
                        timeout=30000,
                    )
                    await asyncio.sleep(2)
                except Exception as exc:
                    print(f"[TURBO] Tab {i}: ошибка загрузки Wordstat: {exc}")
        print(f"[TURBO] Все {len(self.pages)} вкладок готовы")

    async def wait_wordstat_ready(self, page: Page) -> None:
        await page.wait_for_selector("input.textinput__control", timeout=15000)

    async def handle_response(self, response, tab_id: int) -> None:
        if "wordstat/api" not in response.url:
            return

        data = await _parse_wordstat_json(response)
        if not data:
            return

        _normalize_wordstat_payload(data)

        phrase = _extract_phrase_from_request(response)
        if not phrase:
            items = (data.get("table") or {}).get("items") or []
            if items:
                phrase = fix_mojibake(items[0].get("phrase", "")).strip()
        if not phrase:
            return

        freq: Optional[Any] = data.get("totalValue")
        if freq is None:
            items = (data.get("table") or {}).get("items") or []
            if items:
                freq = items[0].get("count") or items[0].get("value")

        try:
            frequency = int(str(freq).replace(" ", "")) if freq is not None else None
        except Exception:
            frequency = None

        if frequency is None:
            return

        self.results[phrase] = {
            "query": phrase,
            "frequency": frequency,
            "timestamp": datetime.utcnow().isoformat(),
            "tab": tab_id,
        }

    async def process_tab_worker(self, page: Page, phrases: List[str], tab_id: int) -> List[Dict[str, Any]]:
        _ensure_wired(page)
        results = []
        page.on("response", lambda response: asyncio.create_task(self.handle_response(response, tab_id)))
        for phrase in phrases:
            try:
                await page.fill("input.textinput__control", phrase)
                await page.keyboard.press("Enter")
                await self.wait_wordstat_ready(page)
                captured = False
                wait_delay = max(self.aimd.get_delay(), 0.05)
                for _ in range(30):
                    if phrase in self.results:
                        results.append(self.results[phrase])
                        captured = True
                        break
                    await asyncio.sleep(wait_delay)
                if captured:
                    self.aimd.on_success()
                else:
                    print(f"[TURBO] Tab {tab_id}: не получили ответ для «{phrase}»")
                    self.aimd.on_error()
            except Exception as exc:
                print(f"[TURBO] Tab {tab_id}: ошибка {exc}")
                self.aimd.on_error()
        return results

    async def parse_batch(self, queries: List[str], region: int = 225) -> List[Dict[str, Any]]:
        if not queries:
            return []
        self.total_processed = 0
        self.total_errors = 0
        self.start_time = time.time()
        await self.init_browser()
        await self.setup_tabs()
        buckets = [queries[i::len(self.pages)] for i in range(len(self.pages))]
        tasks = []
        for idx, page in enumerate(self.pages):
            tasks.append(self.process_tab_worker(page, buckets[idx], idx))
        results_nested = await asyncio.gather(*tasks)
        flat_results = [item for bucket in results_nested for item in bucket]
        return flat_results

    async def save_to_db(self, results: List[Dict[str, Any]]) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for row in results:
            cursor.execute(
                """
                INSERT OR REPLACE INTO freq_results
                (mask, region, freq_total, freq_exact, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    row["query"],
                    row.get("region", 225),
                    row["frequency"],
                    row["frequency"],
                    "ok",
                    row["timestamp"],
                ),
            )
        conn.commit()
        conn.close()

    async def close(self) -> None:
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if getattr(self, "playwright", None):
                await self.playwright.stop()
        finally:
            if self._proxy_item:
                try:
                    self.proxy_manager.release(self._proxy_item)
                except Exception:
                    pass
                self._proxy_item = None
            self.context = None
            self.browser = None
            self.playwright = None
            self.pages = []
            print("[TURBO] Persistent сессия закрыта")


async def run_turbo_parser(queries: List[str], account: Optional[Account] = None, headless: bool = False) -> List[Dict[str, Any]]:
    parser = TurboWordstatParser(account=account, headless=headless)
    try:
        results = await parser.parse_batch(queries)
        await parser.save_to_db(results)
        return results
    finally:
        await parser.close()


if __name__ == "__main__":
    asyncio.run(run_turbo_parser([
        "купить квартиру",
        "ремонт квартир",
    ], headless=False))
