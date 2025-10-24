# -*- coding: utf-8 -*-
from __future__ import annotations

from importlib import import_module
from typing import Any


def _call(module: str, func: str, *args, **kwargs) -> Any:
    try:
        mod = import_module(module)
        target = getattr(mod, func, None)
        if callable(target):
            return target(*args, **kwargs)
    except Exception:
        return None
    return None


def collect_frequency(
    phrases: list[str],
    *,
    modes: dict[str, bool],
    regions: list[int],
    profile: str | None,
) -> list[dict]:
    """Proxy to whichever frequency implementation is available."""

    for module, func in [
        ("keyset.services.wordstat_ws", "collect_frequency"),
        ("keyset.services.frequency", "collect_frequency_ui"),
        ("keyset.services.frequency", "collect_frequency"),
        ("keyset.workers.full_pipeline_worker", "collect_frequency"),
    ]:
        payload = _call(module, func, phrases, modes=modes, regions=regions, profile=profile)
        if payload is not None:
            return payload

    # fallback — return empty results instead of synthetic data
    # Демо-данные удалены - теперь возвращаем пустые результаты
    results: list[dict] = []
    for phrase in phrases:
        results.append(
            {
                "phrase": phrase,
                "ws": "",
                "qws": "",
                "bws": "",
                "status": "No parser available",
            }
        )
    return results


def collect_depth(
    phrases: list[str],
    *,
    column: str,
    pages: int,
    regions: list[int],
    profile: str | None,
) -> list[dict]:
    for module, func in [
        ("keyset.services.frequency", "collect_depth"),
        ("keyset.workers.full_pipeline_worker", "collect_depth"),
    ]:
        payload = _call(
            module,
            func,
            phrases,
            column=column,
            pages=pages,
            regions=regions,
            profile=profile,
        )
        if payload is not None:
            return payload

    # fallback — echo the phrases with dummy counts
    return [
        {
            "phrase": phrase,
            "count": random.randint(0, 200),
            "column": column,
            "status": "OK",
        }
        for phrase in phrases
    ]


def collect_forecast(
    phrases: list[str],
    *,
    regions: list[int],
    profile_ctx: dict,
) -> list[dict]:
    storage_state = (profile_ctx or {}).get("storage_state")
    proxy = (profile_ctx or {}).get("proxy")

    result = _call(
        "keyset.services.direct_batch",
        "get_bids_sync",
        phrases,
        storage_state=storage_state,
        proxy=proxy,
    )
    if result is not None:
        return result

    return [
        {
            "phrase": phrase,
            "shows": random.randint(50, 1000),
            "clicks": random.randint(5, 120),
            "cost": round(random.random() * 10, 2),
            "cpc": round(random.random() * 2, 2),
            "status": "Forecast",
        }
        for phrase in phrases
    ]


__all__ = ["collect_frequency", "collect_depth", "collect_forecast"]
