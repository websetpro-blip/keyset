from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import time

from sqlalchemy import select

try:
    # Относительные импорты для запуска как пакета
    from ..core.db import SessionLocal
    from ..core.models import Account
    from ..utils.proxy import proxy_to_playwright
    from ..utils.text_fix import fix_mojibake
    from .proxy_manager import ProxyManager
    from .chrome_launcher import ChromeLauncher
except ImportError:
    # Абсолютные импорты для запуска как скрипта
    from core.db import SessionLocal
    from core.models import Account
    from utils.proxy import proxy_to_playwright
    from utils.text_fix import fix_mojibake
    from .proxy_manager import ProxyManager
    from .chrome_launcher import ChromeLauncher

# Для проверки прокси и автологина
try:
    import aiohttp
    import asyncio
    from playwright.async_api import async_playwright
    ASYNC_AVAILABLE = True
except ImportError:
    ASYNC_AVAILABLE = False


def _auto_refresh(session):
    now = datetime.utcnow()
    stmt = select(Account).where(Account.status.in_(['cooldown', 'captcha']))
    for acc in session.execute(stmt).scalars():
        if acc.cooldown_until and acc.cooldown_until <= now:
            acc.status = 'ok'
            acc.cooldown_until = None
            acc.captcha_tries = 0
    session.commit()


def _sanitize_account(account: Account) -> Account:
    account.name = fix_mojibake(account.name)
    account.profile_path = fix_mojibake(account.profile_path)
    account.proxy = fix_mojibake(account.proxy)
    account.proxy_id = fix_mojibake(account.proxy_id)
    account.proxy_strategy = fix_mojibake(account.proxy_strategy) or "fixed"
    account.notes = fix_mojibake(account.notes)
    account.status = fix_mojibake(account.status)
    if account.proxy_id and not account.proxy:
        proxy = ProxyManager.instance().get(account.proxy_id)
        if proxy:
            account.proxy = proxy.uri()
    return account


def list_accounts() -> list[Account]:
    with SessionLocal() as session:
        _auto_refresh(session)
        result = session.execute(select(Account).order_by(Account.name))
        return [_sanitize_account(acc) for acc in result.scalars()]


def create_account(
    name: str,
    profile_path: str,
    proxy: str | None = None,
    notes: str | None = None,
    *,
    proxy_id: str | None = None,
    proxy_strategy: str = "fixed",
) -> Account:
    manager = ProxyManager.instance()
    proxy_value = proxy or None
    if proxy_id and not proxy_value:
        proxy_obj = manager.get(proxy_id)
        if proxy_obj:
            proxy_value = proxy_obj.uri()

    with SessionLocal() as session:
        account = Account(
            name=name,
            profile_path=profile_path,
            proxy=proxy_value,
            proxy_id=proxy_id,
            proxy_strategy=proxy_strategy or "fixed",
            notes=notes,
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return _sanitize_account(account)


def upsert_account(
    name: str,
    profile_path: str,
    proxy: str | None = None,
    notes: str | None = None,
    *,
    proxy_id: str | None = None,
    proxy_strategy: str = "fixed",
) -> Account:
    manager = ProxyManager.instance()
    proxy_value = proxy or None
    if proxy_id and not proxy_value:
        proxy_obj = manager.get(proxy_id)
        if proxy_obj:
            proxy_value = proxy_obj.uri()

    with SessionLocal() as session:
        stmt = select(Account).where(Account.name == name)
        existing = session.execute(stmt).scalar_one_or_none()
        if existing:
            existing.profile_path = profile_path
            existing.proxy = proxy_value
            existing.proxy_id = proxy_id
            existing.proxy_strategy = proxy_strategy or "fixed"
            existing.notes = notes
            session.commit()
            session.refresh(existing)
            return _sanitize_account(existing)
        account = Account(
            name=name,
            profile_path=profile_path,
            proxy=proxy_value,
            proxy_id=proxy_id,
            proxy_strategy=proxy_strategy or "fixed",
            notes=notes,
        )
        session.add(account)
        session.commit()
        session.refresh(account)
        return _sanitize_account(account)


def update_account(account_id: int, **fields) -> Account:
    with SessionLocal() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f'Account {account_id} not found')
        manager = ProxyManager.instance()
        for key, value in fields.items():
            if key == "proxy_id":
                account.proxy_id = value or None
                proxy_obj = manager.get(value) if value else None
                account.proxy = proxy_obj.uri() if proxy_obj else None
                continue
            if key == "proxy_strategy":
                account.proxy_strategy = value or "fixed"
                continue
            if key == "proxy":
                account.proxy = value or None
                continue
            if hasattr(account, key):
                setattr(account, key, value)
        session.commit()
        session.refresh(account)
        return _sanitize_account(account)


def set_account_proxy(account_id: int, proxy_id: str | None, strategy: str = "fixed") -> Account:
    manager = ProxyManager.instance()
    with SessionLocal() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f'Account {account_id} not found')
        proxy_obj = manager.get(proxy_id) if proxy_id else None
        account.proxy_id = proxy_id or None
        account.proxy_strategy = strategy or "fixed"
        account.proxy = proxy_obj.uri() if proxy_obj else None
        session.commit()
        session.refresh(account)
        return _sanitize_account(account)


def delete_account(account_id: int) -> None:
    with SessionLocal() as session:
        account = session.get(Account, account_id)
        if account:
            session.delete(account)
            session.commit()


def set_status(account_id: int, status: str, *, cooldown_minutes: int | None = None, captcha_increment: bool = False) -> Account:
    with SessionLocal() as session:
        account = session.get(Account, account_id)
        if account is None:
            raise ValueError(f'Account {account_id} not found')
        account.status = status
        if cooldown_minutes is not None:
            account.cooldown_until = datetime.utcnow() + timedelta(minutes=cooldown_minutes)
        elif status == 'ok':
            account.cooldown_until = None
        if captcha_increment:
            account.captcha_tries = (account.captcha_tries or 0) + 1
        session.commit()
        session.refresh(account)
        return _sanitize_account(account)


def mark_captcha(account_id: int, minutes: int = 30) -> Account:
    return set_status(account_id, 'captcha', cooldown_minutes=minutes, captcha_increment=True)


def mark_cooldown(account_id: int, minutes: int = 10) -> Account:
    return set_status(account_id, 'cooldown', cooldown_minutes=minutes)


def mark_error(account_id: int) -> Account:
    return set_status(account_id, 'error')


def mark_ok(account_id: int) -> Account:
    return set_status(account_id, 'ok')


def update_account_proxy(account_name: str, proxy: str | None) -> Account:
    """Обновить прокси у аккаунта по имени"""
    with SessionLocal() as session:
        stmt = select(Account).where(Account.name == account_name)
        account = session.execute(stmt).scalar_one_or_none()
        if account is None:
            raise ValueError(f'Account {account_name} not found')
        account.proxy = proxy
        session.commit()
        session.refresh(account)
        return _sanitize_account(account)


# ========== НОВЫЕ ФУНКЦИИ ИЗ ФАЙЛА 42 ==========

async def test_proxy(proxy: Optional[str], timeout: int = 10) -> Dict[str, Any]:
    """
    Проверка прокси
    
    Returns:
        {"ok": True/False, "ip": "1.2.3.4" или "error": "описание ошибки"}
    """
    if not ASYNC_AVAILABLE:
        return {"ok": False, "error": "aiohttp не установлен"}
    
    if not proxy:
        return {"ok": True, "ip": None, "message": "Без прокси"}
    
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:
            async with session.get(
                "https://yandex.ru/internet",
                proxy=proxy,
                headers={"User-Agent": "Mozilla/5.0"}
            ) as resp:
                resp.raise_for_status()
                ip = resp.headers.get("x-client-ip") or "ok"
                return {"ok": True, "ip": ip}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_cookies_status(account: Account) -> str:
    """
    Статус куки аккаунта
    
    Returns:
        "None" | "Fresh" | "Expired"
    """
    raw_path = account.profile_path or ""
    if not raw_path:
        return "Нет профиля"

    profile_path = ChromeLauncher._normalise_profile_path(raw_path, account.name)

    candidates = [
        ("Chrome", profile_path / "Default" / "Network" / "Cookies"),
        ("Chrome", profile_path / "Default" / "Cookies"),
        ("state", profile_path / "storage_state.json"),
        ("state", profile_path / "state.json"),
        ("state", profile_path / "cookies.json"),
    ]

    for source, cookie_path in candidates:
        if cookie_path.exists():
            stat = cookie_path.stat()
            size_kb = stat.st_size / 1024
            age_days = max(0.0, (time.time() - stat.st_mtime) / 86400)

            if age_days < 3:
                freshness = "Fresh"
            elif age_days < 14:
                freshness = "Stale"
            else:
                freshness = "Expired"

            label = f"{size_kb:.1f}KB {source} ({freshness})"
            return label

    return "Нет куков"


async def autologin_account(account: Account) -> Dict[str, Any]:
    """
    Автологин аккаунта через Playwright
    Открывает Wordstat, проверяет авторизацию, сохраняет storage_state
    
    Returns:
        {"ok": True/False, "message": "...", "storage_path": "..."}
    """
    if not ASYNC_AVAILABLE:
        return {"ok": False, "message": "Playwright не установлен"}
    
    profile_path = ChromeLauncher._normalise_profile_path(account.profile_path, account.name)
    profile_path.mkdir(parents=True, exist_ok=True)
    storage_file = profile_path / "storage_state.json"
    
    try:
        proxy_config = proxy_to_playwright(account.proxy)
        
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            
            context = await browser.new_context(
                proxy=proxy_config,
                viewport={"width": 1280, "height": 900}
            )
            
            page = await context.new_page()
            
            # Открываем Wordstat
            await page.goto("https://wordstat.yandex.ru/", timeout=60000)
            
            # Ждем загрузки
            await page.wait_for_load_state("domcontentloaded")
            
            # Проверяем авторизован ли
            current_url = page.url
            
            if "passport.yandex" in current_url or "passport.ya.ru" in current_url:
                await browser.close()
                return {
                    "ok": False,
                    "message": "Требуется ручной вход (открыта страница паспорта)"
                }
            
            # Сохраняем storage_state
            await context.storage_state(path=str(storage_file))
            await browser.close()
            
            # Обновляем last_used_at
            with SessionLocal() as session:
                stmt = select(Account).where(Account.id == account.id)
                acc = session.execute(stmt).scalar_one_or_none()
                if acc:
                    acc.last_used_at = datetime.utcnow()
                    session.commit()
            
            return {
                "ok": True,
                "message": "Авторизация успешна",
                "storage_path": str(storage_file)
            }
            
    except Exception as e:
        return {"ok": False, "message": f"Ошибка: {e}"}


# ---------------------------------------------------------------------------
# Lightweight helpers for the new parsing UI
# ---------------------------------------------------------------------------


def list_profiles() -> list[str]:
    """Return account names ordered alphabetically for the toolbar drop-down."""
    accounts = list_accounts()
    return [account.name for account in accounts] or ["Текущий"]


def get_profile_ctx(name: str | None) -> dict[str, str | None]:
    """Return storage state / proxy information for a given account name."""
    if not name:
        return {"storage_state": None, "proxy": None}

    with SessionLocal() as session:
        stmt = select(Account).where(Account.name == name)
        account = session.execute(stmt).scalar_one_or_none()
        if not account:
            return {"storage_state": None, "proxy": None}
        profile_path = ChromeLauncher._normalise_profile_path(account.profile_path, account.name)
        storage_file = None
        for candidate in [
            profile_path / "storage_state.json",
            profile_path / "state.json",
            profile_path / "Default" / "storage_state.json",
        ]:
            if candidate.exists():
                storage_file = str(candidate)
                break
        return {
            "storage_state": storage_file,
            "proxy": account.proxy,
        }


def get_account_by_email(email: str) -> dict | None:
    """
    Получить аккаунт из БД по email.

    Args:
        email: Email аккаунта
    
    Returns:
        dict: {'email': str, 'proxy': str, 'profile_path': str, 'status': str}
        None: Если аккаунт не найден
    """
    try:
        with SessionLocal() as session:
            stmt = select(Account).where(Account.name == email)
            acc = session.execute(stmt).scalar_one_or_none()

            if not acc:
                return None

            return {
                "email": acc.name,
                "proxy": acc.proxy,
                "profile_path": acc.profile_path,
                "status": acc.status,
            }
    except Exception as e:
        print(f"Ошибка получения аккаунта: {e}")
        return None
