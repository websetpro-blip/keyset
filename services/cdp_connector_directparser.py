"""CDP connector utilities mirroring DirectParser behaviour."""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, Optional

from playwright.async_api import async_playwright, Browser

LOGGER = logging.getLogger(__name__)


class CDPConnectorDirectParser:
    """Lightweight helper for interacting with the running Chrome via CDP."""

    @staticmethod
    async def connect(cdp_port: int) -> Optional[Browser]:
        try:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            # Attach playwright instance to browser for later clean-up
            browser._directparser_playwright = playwright  # type: ignore[attr-defined]
            LOGGER.info("[CDP] Connected to port %s", cdp_port)
            return browser
        except Exception as exc:
            LOGGER.error("[CDP] Connection error on port %s: %s", cdp_port, exc)
            return None

    @staticmethod
    async def _disconnect(browser: Browser) -> None:
        playwright = getattr(browser, "_directparser_playwright", None)
        try:
            await browser.close()
        except Exception:  # pragma: no cover
            LOGGER.debug("[CDP] Browser close raised", exc_info=True)
        if playwright:
            try:
                await playwright.stop()
            except Exception:  # pragma: no cover
                LOGGER.debug("[CDP] Playwright stop raised", exc_info=True)

    @staticmethod
    async def extract_cookies(cdp_port: int) -> Dict[str, str]:
        browser = await CDPConnectorDirectParser.connect(cdp_port)
        if not browser:
            return {}
        try:
            contexts = browser.contexts
            if not contexts:
                LOGGER.warning("[CDP] No contexts available")
                return {}
            context = contexts[0]
            cookies = await context.cookies()
            payload = {cookie["name"]: cookie["value"] for cookie in cookies}
            LOGGER.info("[CDP] Extracted %s cookies", len(payload))
            return payload
        except Exception as exc:
            LOGGER.error("[CDP] Failed to extract cookies: %s", exc)
            return {}
        finally:
            await CDPConnectorDirectParser._disconnect(browser)

    @staticmethod
    async def extract_cookies_for_account(account_name: str, cdp_port: int) -> Dict[str, str]:
        cookies = await CDPConnectorDirectParser.extract_cookies(cdp_port)
        LOGGER.debug("[%s] cookies: %s", account_name, list(cookies.keys()))
        return cookies

    @staticmethod
    async def check_ip(cdp_port: int) -> Optional[str]:
        browser = await CDPConnectorDirectParser.connect(cdp_port)
        if not browser:
            return None
        try:
            contexts = browser.contexts
            if not contexts:
                return None
            context = contexts[0]
            page = await context.new_page()
            try:
                await page.goto("https://yandex.ru/internet", timeout=15000)
                await page.wait_for_load_state("networkidle")
                content = await page.content()
            finally:
                await page.close()
            import re

            match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", content)
            if match:
                ip = match.group(1)
                LOGGER.info("[CDP] Detected IP %s", ip)
                return ip
            return None
        except Exception as exc:
            LOGGER.error("[CDP] IP check error: %s", exc)
            return None
        finally:
            await CDPConnectorDirectParser._disconnect(browser)

    @staticmethod
    async def check_login(account_name: str, cdp_port: int) -> bool:
        cookies = await CDPConnectorDirectParser.extract_cookies(cdp_port)
        markers = ["Session_id", "sessionid", "yandexuid", "yp", "ys"]
        found = [marker for marker in markers if any(marker in key for key in cookies.keys())]
        if found:
            LOGGER.info("[%s] Authorization markers found: %s", account_name, found)
            return True
        LOGGER.warning("[%s] Authorization markers missing", account_name)
        return False


__all__ = ["CDPConnectorDirectParser"]
