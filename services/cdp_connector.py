'''Small helpers for interacting with Chrome DevTools for diagnostics.'''
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

LOGGER = logging.getLogger(__name__)


class CDPConnector:
    """Minimal async utilities to check Chrome remote debugging endpoints."""

    @staticmethod
    async def fetch_version(port: int, timeout: float = 5.0) -> Optional[dict]:
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=timeout) as resp:
                    if resp.status != 200:
                        LOGGER.debug("CDP version check failed (%s): %s", url, resp.status)
                        return None
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            LOGGER.debug("CDP version request error: %s", exc)
            return None

    @staticmethod
    async def check_port(port: int, timeout: float = 5.0) -> Optional[str]:
        """Return a human readable status if the CDP port responds."""
        metadata = await CDPConnector.fetch_version(port, timeout=timeout)
        if not metadata:
            return None
        browser = metadata.get("Browser") or metadata.get("User-Agent") or "unknown"
        return f"CDP ready ({browser})"


async def check_port(port: int, timeout: float = 5.0) -> Optional[str]:
    """Convenience functional wrapper."""
    return await CDPConnector.check_port(port, timeout=timeout)