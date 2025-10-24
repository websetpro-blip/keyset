# -*- coding: utf-8 -*-
"""
Обёртки над рабочими воркерами Wordstat.

Функции здесь вызываются из UI (через services.wordstat_bridge) и
подтягивают реальные частотности из TurboWordstatParser.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Iterable

try:
    from ..workers.turbo_parser_integration import TurboWordstatParser
    from . import accounts as account_service
except ImportError:
    from workers.turbo_parser_integration import TurboWordstatParser
    from . import accounts as account_service


@dataclass(slots=True)
class _Query:
    """Спецификация одного запроса к Wordstat."""

    phrase: str
    mode: str  # ws | qws | bws
    query: str


def _prepare_requests(phrases: Iterable[str], modes: dict[str, bool]) -> list[_Query]:
    """Сформировать список запросов для TurboWordstatParser."""
    requests: list[_Query] = []
    for phrase in phrases:
        cleaned = phrase.strip()
        if not cleaned:
            continue
        if modes.get("ws", False):
            requests.append(_Query(cleaned, "ws", cleaned))
        if modes.get("qws", False):
            requests.append(_Query(cleaned, "qws", f"\"{cleaned}\""))
        if modes.get("bws", False):
            exact = " ".join(f"!{part}" if not part.startswith("!") else part for part in cleaned.split())
            requests.append(_Query(cleaned, "bws", exact))
    return requests


def _resolve_account(name: str | None):
    """
    Найти аккаунт по имени.

    Возвращает SQLAlchemy-модель Account, которую понимает TurboWordstatParser.
    """
    accounts = account_service.list_accounts()
    if not accounts:
        raise RuntimeError("В базе нет аккаунтов — подключите хотя бы один перед парсингом.")
    if not name:
        return accounts[0]
    for account in accounts:
        if account.name == name:
            return account
    raise RuntimeError(f"Аккаунт «{name}» не найден в базе.")


async def _run_turbo(queries: list[str], account, region: int) -> list[dict]:
    """Асинхронный запуск TurboWordstatParser."""
    parser = TurboWordstatParser(account=account, headless=False)
    try:
        results = await parser.parse_batch(queries, region=region)
        if results:
            await parser.save_to_db(results)
        return results or []
    finally:
        await parser.close()


def collect_frequency(
    phrases: list[str],
    *,
    modes: dict[str, bool],
    regions: list[int],
    profile: str | None,
) -> list[dict]:
    """
    Вернуть реальные частотности (WS/"WS"/!WS) для списка фраз.

    Args:
        phrases: исходные ключевые фразы из UI.
        modes: какие режимы частотности нужны.
        regions: список регионов Яндекса (используем первый).
        profile: выбранный аккаунт (имя из базы).
    """
    requests = _prepare_requests(phrases, modes)
    if not requests:
        return []

    # TurboWordstatParser ожидает уникальные запросы — убираем дубли.
    seen: set[str] = set()
    unique_queries: list[str] = []
    for entry in requests:
        if entry.query not in seen:
            seen.add(entry.query)
            unique_queries.append(entry.query)

    account = _resolve_account(profile)
    region = regions[0] if regions else 225

    try:
        results = asyncio.run(_run_turbo(unique_queries, account, region))
    except RuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - реальный запуск вне тестов
        raise RuntimeError(f"TurboWordstatParser error: {exc}") from exc

    freq_by_query = {row.get("query"): int(row.get("frequency", 0) or 0) for row in results}

    rows: list[dict] = []
    for phrase in phrases:
        phrase = phrase.strip()
        if not phrase:
            continue
        row = {"phrase": phrase}
        missing_modes: list[str] = []

        def _set(column: str, query: str | None) -> None:
            if not modes.get(column, False) or not query:
                row[column] = ""
                return
            value = freq_by_query.get(query)
            if value is None:
                missing_modes.append(column)
                row[column] = 0
            else:
                row[column] = value

        _set("ws", phrase)
        _set("qws", f"\"{phrase}\"")
        exact_query = " ".join(f"!{part}" if not part.startswith("!") else part for part in phrase.split())
        _set("bws", exact_query)

        if missing_modes and any(modes.values()):
            row["status"] = f"Нет данных ({', '.join(missing_modes)})"
        else:
            row["status"] = "OK"
        rows.append(row)

    return rows


__all__ = ["collect_frequency"]

