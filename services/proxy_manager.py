from __future__ import annotations

import base64
import json
import threading
import time
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

try:
    from ..utils.proxy import proxy_to_playwright
except ImportError:
    from utils.proxy import proxy_to_playwright


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "proxies.json"


def _normalize_server(proxy_type: str, server: str) -> str:
    value = server.strip()
    if not value:
        return value
    if "://" in value:
        return value
    return f"{proxy_type}://{value}"


@dataclass
class Proxy:
    id: str
    label: str
    type: str
    server: str
    username: Optional[str] = None
    password: Optional[str] = None
    geo: Optional[str] = None
    sticky: bool = True
    max_concurrent: int = 10
    enabled: bool = True
    notes: str = ""
    last_check: Optional[float] = None
    last_ip: Optional[str] = None
    _in_use: int = field(default=0, repr=False)

    @property
    def has_auth(self) -> bool:
        return bool(self.username and self.password)

    def __post_init__(self) -> None:
        self.type = (self.type or "http").lower()
        if self.type not in {"http", "https", "socks5"}:
            self.type = "http"
        self.server = _normalize_server(self.type, self.server)
        if not self.label:
            self.label = self.id

    def playwright_config(self) -> Dict[str, str]:
        payload: Dict[str, str] = {"server": self.server}
        if self.username:
            payload["username"] = self.username
        if self.password:
            payload["password"] = self.password
        return payload

    def chrome_flag(self) -> str:
        scheme, _, host_port = self.server.partition("://")
        return f'--proxy-server="{scheme}://{host_port}"'

    def uri(self, include_credentials: bool = True) -> str:
        scheme, _, host_port = self.server.partition("://")
        if include_credentials and self.username:
            password = self.password or ""
            return f"{scheme}://{self.username}:{password}@{host_port}"
        return f"{scheme}://{host_port}"

    def display_label(self) -> str:
        parts = [self.label or self.id]
        extras: List[str] = []
        if self.geo:
            extras.append(self.geo)
        extras.append(self.type.upper())
        if extras:
            parts.append(f"({' / '.join(extras)})")
        if not self.enabled:
            parts.append("[OFF]")
        return " ".join(parts)


class ProxyManager:
    _instance: Optional["ProxyManager"] = None
    _singleton_lock = threading.Lock()

    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self._items: Dict[str, Proxy] = {}
        self._lock = threading.RLock()
        self._load()

    @classmethod
    def instance(cls) -> "ProxyManager":
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        with self._lock:
            self._items.clear()
            if not self.path.exists():
                self._save_unlocked()
                return
            raw = self.path.read_text(encoding="utf-8").strip()
            if not raw:
                self._save_unlocked()
                return
            data = json.loads(raw)
            for entry in data.get("proxies", []):
                try:
                    proxy = Proxy(**entry)
                except TypeError:
                    continue
                self._items[proxy.id] = proxy
            if not self._items:
                self._bootstrap_from_accounts()


    def _bootstrap_from_accounts(self) -> None:
        try:
            from . import accounts as account_service
            from ..core.db import SessionLocal
            from ..core.models import Account
        except Exception:
            return
        try:
            accounts = account_service.list_accounts()
        except Exception:
            return
        if not accounts:
            return

        created = False
        mapping = {}
        for proxy in self._items.values():
            key = (proxy.server, proxy.username, proxy.password)
            mapping[key] = proxy

        for account in accounts:
            raw = (account.proxy or '').strip()
            if not raw:
                continue
            parsed = proxy_to_playwright(raw)
            if not parsed or not parsed.get('server'):
                continue
            key = (parsed['server'], parsed.get('username'), parsed.get('password'))
            proxy = mapping.get(key)
            if proxy is None:
                proxy = Proxy(
                    id=uuid.uuid4().hex,
                    label=parsed['server'].split('://', 1)[-1],
                    type=parsed['server'].split('://', 1)[0],
                    server=parsed['server'],
                    username=parsed.get('username'),
                    password=parsed.get('password'),
                    geo=None,
                    sticky=True,
                    max_concurrent=10,
                    enabled=True,
                )
                self._items[proxy.id] = proxy
                mapping[key] = proxy
                created = True

        if not mapping:
            if created:
                self._save_unlocked()
            return

        with SessionLocal() as session:
            for account in accounts:
                raw = (account.proxy or '').strip()
                if not raw:
                    continue
                parsed = proxy_to_playwright(raw)
                if not parsed or not parsed.get('server'):
                    continue
                key = (parsed['server'], parsed.get('username'), parsed.get('password'))
                proxy = mapping.get(key)
                if proxy is None:
                    continue
                db_account = session.get(Account, account.id)
                if not db_account:
                    continue
                db_account.proxy_id = proxy.id
                db_account.proxy = proxy.uri()
                db_account.proxy_strategy = 'fixed'
            session.commit()

        if created:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        payload = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "proxies": [],
        }
        for proxy in self._items.values():
            record = asdict(proxy).copy()
            record.pop("_in_use", None)
            payload["proxies"].append(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save(self) -> None:
        with self._lock:
            self._save_unlocked()

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def list(self, include_disabled: bool = False) -> List[Proxy]:
        with self._lock:
            proxies = list(self._items.values())
        if include_disabled:
            return [Proxy(**{**asdict(p), "_in_use": p._in_use}) for p in proxies]
        return [
            Proxy(**{**asdict(p), "_in_use": p._in_use})
            for p in proxies
            if p.enabled
        ]

    def get(self, proxy_id: Optional[str]) -> Optional[Proxy]:
        if not proxy_id:
            return None
        with self._lock:
            proxy = self._items.get(proxy_id)
            if proxy is None:
                return None
            return Proxy(**{**asdict(proxy), "_in_use": proxy._in_use})

    def upsert(self, proxy: Proxy) -> Proxy:
        with self._lock:
            existing = self._items.get(proxy.id)
            if existing:
                proxy._in_use = existing._in_use
            self._items[proxy.id] = proxy
            self._save_unlocked()
        return proxy

    def delete(self, proxy_id: str) -> None:
        with self._lock:
            self._items.pop(proxy_id, None)
            self._save_unlocked()

    def save_many(self, proxies: Iterable[Proxy]) -> None:
        for proxy in proxies:
            self.upsert(proxy)

    # ------------------------------------------------------------------ #
    # Allocation helpers
    # ------------------------------------------------------------------ #
    def acquire(self, proxy_id: Optional[str] = None, *, geo: Optional[str] = None) -> Optional[Proxy]:
        with self._lock:
            candidates: List[Proxy] = []
            if proxy_id and proxy_id in self._items:
                proxy = self._items[proxy_id]
                if proxy.enabled:
                    candidates = [proxy]
            else:
                candidates = [p for p in self._items.values() if p.enabled]
                if geo:
                    geo_lower = geo.lower()
                    geo_filtered = [p for p in candidates if (p.geo or "").lower() == geo_lower]
                    if geo_filtered:
                        candidates = geo_filtered
            candidates.sort(key=lambda item: item._in_use)

            for proxy in candidates:
                limit = proxy.max_concurrent or 0
                if limit and proxy._in_use >= limit:
                    continue
                proxy._in_use += 1
                return Proxy(**{**asdict(proxy), "_in_use": proxy._in_use})
        return None

    def release(self, proxy: Optional[Proxy]) -> None:
        if proxy is None:
            return
        with self._lock:
            stored = self._items.get(proxy.id)
            if stored:
                stored._in_use = max(0, stored._in_use - 1)

    # ------------------------------------------------------------------ #
    # Utilities
    # ------------------------------------------------------------------ #
    def to_options(self) -> List[dict]:
        options = []
        for proxy in self.list(include_disabled=True):
            options.append(
                {
                    "value": proxy.id,
                    "label": proxy.display_label(),
                    "enabled": proxy.enabled,
                    "geo": proxy.geo,
                }
            )
        return options

def test_proxy(self, proxy: Proxy, timeout: float = 10.0) -> Dict[str, object]:
        handler = urllib.request.ProxyHandler(
            {
                "http": proxy.uri(include_credentials=True),
                "https": proxy.uri(include_credentials=True),
            }
        )
        opener = urllib.request.build_opener(handler)
        if proxy.username:
            credentials = f"{proxy.username}:{proxy.password or ''}".encode("utf-8")
            opener.addheaders = [("Proxy-Authorization", f"Basic {base64.b64encode(credentials).decode('ascii')}")]

        start = time.perf_counter()
        try:
            with opener.open("https://api.ipify.org", timeout=timeout) as response:
                ip = response.read().decode("utf-8").strip()
        except Exception as exc:
            elapsed = int((time.perf_counter() - start) * 1000)
            return {"ok": False, "error": str(exc), "latency_ms": elapsed}
        else:
            elapsed = int((time.perf_counter() - start) * 1000)
            proxy.last_ip = ip
            proxy.last_check = time.time()
            self.upsert(proxy)
            return {"ok": True, "ip": ip, "latency_ms": elapsed}


def proxy_preflight(proxy: Optional[Proxy], *, timeout: float = 10.0) -> Dict[str, Optional[str]]:
    """Лёгкая проверка доступности прокси (без запуска браузера)."""
    if proxy is None:
        return {"ok": True, "ip": None, "error": None}

    server = proxy.server
    scheme = proxy.type or "http"
    if not server:
        return {"ok": False, "ip": None, "error": "empty proxy server"}

    if "://" not in server:
        server = f"{scheme}://{server}"

    if scheme.lower().startswith("socks"):
        # urllib не умеет SOCKS, отдадим проверку браузеру
        return {"ok": True, "ip": None, "error": None}

    handler = urllib.request.ProxyHandler({"http": server, "https": server})
    opener = urllib.request.build_opener(handler)
    if proxy.username:
        creds = f"{proxy.username}:{proxy.password or ''}".encode("utf-8")
        opener.addheaders = [("Proxy-Authorization", f"Basic {base64.b64encode(creds).decode('ascii')}")]

    try:
        with opener.open("https://api.ipify.org", timeout=timeout) as response:
            ip = response.read().decode("utf-8").strip()
            return {"ok": True, "ip": ip, "error": None}
    except Exception as exc:
        return {"ok": False, "ip": None, "error": str(exc)}


__all__ = ["Proxy", "ProxyManager", "proxy_preflight"]




