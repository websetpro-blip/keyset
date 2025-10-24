from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Iterable

from sqlalchemy import select, func

try:
    from ..core.db import SessionLocal, get_db_connection
    from ..core.models import FrequencyResult
except ImportError:
    from core.db import SessionLocal, get_db_connection
    from core.models import FrequencyResult

QUEUE_STATUSES = ("queued", "running", "ok", "error")


def enqueue_masks(masks: Iterable[str], region: int) -> int:
    """Add masks into freq_results, resetting non-ok rows to queued."""
    inserted = 0
    normalized = []
    for raw in masks:
        mask = (raw or "").strip()
        if mask:
            normalized.append(mask)
    if not normalized:
        return 0
    with SessionLocal() as session:
        for mask in normalized:
            stmt = select(FrequencyResult).where(
                FrequencyResult.mask == mask,
                FrequencyResult.region == region,
            )
            existing = session.scalars(stmt).first()
            if existing:
                if existing.status != 'ok':
                    existing.status = 'queued'
                    existing.freq_total = 0
                    existing.freq_quotes = 0
                    existing.freq_exact = 0
                    existing.error = None
                    existing.attempts = 0
                    existing.updated_at = datetime.utcnow()
            else:
                session.add(FrequencyResult(mask=mask, region=region))
                inserted += 1
        session.commit()
    return inserted


def list_results(status: str | None = None, limit: int = 500) -> list[dict]:
    with SessionLocal() as session:
        stmt = select(FrequencyResult).order_by(FrequencyResult.updated_at.desc())
        if status and status != 'all':
            stmt = stmt.where(FrequencyResult.status == status)
        if limit:
            stmt = stmt.limit(limit)
        rows = session.scalars(stmt).all()
        return [
            {
                'mask': row.mask,
                'region': row.region,
                'status': row.status,
                'freq_total': row.freq_total,
                'freq_quotes': getattr(row, 'freq_quotes', 0),  # С поддержкой старых БД
                'freq_exact': row.freq_exact,
                'group': getattr(row, 'group', ''),  # Группа для организации
                'attempts': row.attempts,
                'error': row.error or '',
                'updated_at': row.updated_at,
            }
            for row in rows
        ]


def counts_by_status() -> dict[str, int]:
    with SessionLocal() as session:
        stmt = select(FrequencyResult.status, func.count(FrequencyResult.id)).group_by(FrequencyResult.status)
        rows = session.execute(stmt).all()
        counts: dict[str, int] = {status: 0 for status in QUEUE_STATUSES}
        for status, value in rows:
            counts[status] = value
        return counts


def update_group(phrase_ids: list[int], group_name: str) -> int:
    """Обновить группу для выбранных фраз"""
    with SessionLocal() as session:
        stmt = select(FrequencyResult).where(FrequencyResult.id.in_(phrase_ids))
        results = session.scalars(stmt).all()
        
        for result in results:
            result.group = group_name
            result.updated_at = datetime.utcnow()
        
        session.commit()
        return len(results)


def get_all_groups() -> list[str]:
    """Получить список всех уникальных групп"""
    with SessionLocal() as session:
        stmt = select(FrequencyResult.group).distinct().where(FrequencyResult.group.isnot(None))
        groups = session.scalars(stmt).all()
        return [g for g in groups if g]


def clear_results() -> None:
    with SessionLocal() as session:
        session.query(FrequencyResult).delete()
        session.commit()


# ============================================================================
# TURBO PARSER: Batch Wordstat parsing for pipeline
# ============================================================================

async def parse_batch_wordstat(
    masks: list[str], 
    session_page=None, 
    chunk_size: int = 80, 
    region: int = 225
) -> list[dict]:
    """
    Parse frequency from Wordstat using Playwright in batch mode.
    
    Args:
        masks: List of search phrases to parse
        session_page: Playwright page with active session (from autologin)
        chunk_size: Number of masks per batch (Yandex limit: ~80/min)
        region: Yandex region ID (default 225 = Russia)
    
    Returns:
        List of dicts: [{'phrase': str, 'freq': int, 'region': int}, ...]
    """
    results = []
    
    # Import playwright only when needed
    from playwright.async_api import async_playwright
    
    # If no session provided, create temporary browser
    own_browser = session_page is None
    if own_browser:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        session_page = await context.new_page()
        await session_page.goto("https://wordstat.yandex.ru/")
    
    try:
        for i in range(0, len(masks), chunk_size):
            batch = masks[i:i + chunk_size]
            
            for mask in batch:
                try:
                    # Navigate to Wordstat with phrase
                    url = f"https://wordstat.yandex.ru/#!/?words={mask}&regions={region}"
                    await session_page.goto(url, timeout=15000)
                    
                    # КРИТИЧНО: Ждем загрузку URL и ответ от сервера
                    await session_page.wait_for_url("**/wordstat.yandex.ru/**", timeout=10000)
                    
                    # Ждем ответ с данными (ВАЖНО для SPA)
                    try:
                        await session_page.wait_for_response(
                            lambda r: "wordstat.yandex.ru" in r.url and r.ok,
                            timeout=10000
                        )
                    except:
                        pass  # Может не быть XHR на первой загрузке
                    
                    # Проверяем не открылось ли в iframe (challenge)
                    iframe_selectors = [
                        'iframe[src*="challenge"]',
                        'iframe[name*="passp:challenge"]',
                        'iframe[src*="passport"]'
                    ]
                    
                    for iframe_sel in iframe_selectors:
                        if await session_page.locator(iframe_sel).count() > 0:
                            print(f"[Wordstat] Обнаружен challenge в iframe для {mask}")
                            # Используем frame_locator для работы с iframe
                            frame = session_page.frame_locator(iframe_sel)
                            answer_field = frame.locator('input[name="answer"], input[type="text"]')
                            
                            # Если есть поле ответа - нужно его заполнить
                            if await answer_field.count() > 0:
                                # Здесь должен быть ответ на секретный вопрос из аккаунта
                                print(f"[Wordstat] ВНИМАНИЕ: Требуется ответ на секретный вопрос!")
                                # Пропускаем эту фразу
                                results.append({'phrase': mask, 'freq': 0, 'region': region})
                                continue
                    
                    # Wait for results to load
                    await session_page.wait_for_selector(
                        "[data-auto='phrase-count-total'], .b-phrase-count",
                        timeout=10000
                    )
                    
                    # Try to click "Show statistics" if exists
                    try:
                        show_btn = session_page.locator("text=Показать статистику")
                        if await show_btn.count() > 0:
                            await show_btn.first.click(timeout=3000)
                            await asyncio.sleep(1)
                    except:
                        pass  # Button might not exist
                    
                    # Extract frequency number
                    freq_element = session_page.locator(
                        "[data-auto='phrase-count-total'], .b-phrase-count__total"
                    )
                    freq_text = await freq_element.first.inner_text(timeout=5000)
                    
                    # Parse number from text (remove spaces, commas)
                    freq = int(''.join(filter(str.isdigit, freq_text)))
                    
                    result = {'phrase': mask, 'freq': freq, 'region': region}
                    results.append(result)
                    
                    # Save to DB immediately (for progress tracking)
                    with get_db_connection() as conn:
                        conn.execute(
                            "INSERT OR REPLACE INTO frequencies (phrase, freq, region, processed) VALUES (?, ?, ?, 0)",
                            (mask, freq, region)
                        )
                    
                    # Rate limiting: ~1 req/sec = 60/min
                    await asyncio.sleep(1.0)
                    
                    print(f"[Wordstat] {mask}: {freq:,}")
                    
                except Exception as e:
                    print(f"[Wordstat ERROR] {mask}: {e}")
                    results.append({'phrase': mask, 'freq': 0, 'region': region})
            
            # Longer pause between batches
            if i + chunk_size < len(masks):
                await asyncio.sleep(3)
    
    finally:
        if own_browser:
            await context.close()
            await browser.close()
            await playwright.stop()
    
    return results


async def get_saved_frequencies(region: int = 225) -> list[dict]:
    """Get all saved frequency results from database."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            "SELECT phrase, freq, region FROM frequencies WHERE region = ? ORDER BY freq DESC",
            (region,)
        )
        return [
            {'phrase': row[0], 'freq': row[1], 'region': row[2]}
            for row in cursor.fetchall()
        ]
