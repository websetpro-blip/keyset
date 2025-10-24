# -*- coding: utf-8 -*-
"""
Yandex.Direct forecast service - budget prediction for phrases.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

try:
    from ..core.db import get_db_connection
except ImportError:
    from core.db import get_db_connection


async def forecast_batch_direct(
    phrases: list[str],
    session_page=None,
    chunk_size: int = 100,
    region: int = 225
) -> list[dict]:
    """
    Get budget forecast from Yandex.Direct for batch of phrases.
    
    Args:
        phrases: List of phrases to forecast
        session_page: Playwright page with active Yandex session (from autologin)
        chunk_size: Number of phrases per batch (Direct limit: ~100/min)
        region: Yandex region ID
    
    Returns:
        List of dicts: [{'phrase': str, 'cpc': float, 'impressions': int, 'budget': float}, ...]
    """
    results = []
    
    # Import only when needed
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
        await session_page.goto("https://direct.yandex.ru/")
    
    try:
        for i in range(0, len(phrases), chunk_size):
            batch = phrases[i:i + chunk_size]
            
            for phrase in batch:
                try:
                    # Navigate to Direct forecast tool
                    url = f"https://direct.yandex.ru/registered/main.pl?cmd=forecastByWords&words={phrase}"
                    await session_page.goto(url, timeout=20000)
                    
                    # Wait for forecast results to load
                    await session_page.wait_for_selector(
                        ".forecast-table, [data-bem*='forecast']",
                        timeout=15000
                    )
                    
                    # Extract CPC (cost per click)
                    try:
                        cpc_element = session_page.locator(
                            ".forecast-table__cpc, [data-test-id='cpc']"
                        )
                        cpc_text = await cpc_element.first.inner_text(timeout=5000)
                        cpc = float(''.join(filter(lambda x: x.isdigit() or x == '.', cpc_text)))
                    except:
                        cpc = 0.0
                    
                    # Extract impressions (показы)
                    try:
                        impr_element = session_page.locator(
                            ".forecast-table__impressions, [data-test-id='impressions']"
                        )
                        impr_text = await impr_element.first.inner_text(timeout=5000)
                        impressions = int(''.join(filter(str.isdigit, impr_text)))
                    except:
                        impressions = 0
                    
                    # Calculate monthly budget (CPC * impressions * 30 days)
                    budget = round(cpc * impressions * 30, 2)
                    
                    result = {
                        'phrase': phrase,
                        'cpc': cpc,
                        'impressions': impressions,
                        'budget': budget
                    }
                    results.append(result)
                    
                    # Save to database immediately
                    with get_db_connection() as conn:
                        conn.execute(
                            """INSERT OR REPLACE INTO forecasts 
                            (phrase, cpc, impressions, budget, region, processed) 
                            VALUES (?, ?, ?, ?, ?, 0)""",
                            (phrase, cpc, impressions, budget, region)
                        )
                    
                    # Rate limiting: ~1 req/sec = 60/min
                    await asyncio.sleep(1.0)
                    
                    print(f"[Direct] {phrase}: CPC={cpc:.2f} ₽, Shows={impressions:,}, Budget={budget:,.0f} ₽")
                    
                except Exception as e:
                    print(f"[Direct ERROR] {phrase}: {e}")
                    results.append({
                        'phrase': phrase,
                        'cpc': 0.0,
                        'impressions': 0,
                        'budget': 0.0
                    })
            
            # Longer pause between batches
            if i + chunk_size < len(phrases):
                await asyncio.sleep(5)
    
    finally:
        if own_browser:
            await context.close()
            await browser.close()
            await playwright.stop()
    
    return results


async def get_saved_forecasts(region: int = 225) -> list[dict]:
    """Get all saved forecast results from database."""
    with get_db_connection() as conn:
        cursor = conn.execute(
            """SELECT phrase, cpc, impressions, budget 
            FROM forecasts 
            WHERE region = ? 
            ORDER BY budget DESC""",
            (region,)
        )
        return [
            {
                'phrase': row[0],
                'cpc': row[1],
                'impressions': row[2],
                'budget': row[3]
            }
            for row in cursor.fetchall()
        ]


def merge_freq_and_forecast(region: int = 225) -> list[dict]:
    """
    Merge frequency and forecast data for export.
    
    Returns:
        List of dicts with: phrase, freq, cpc, impressions, budget
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            SELECT 
                f.phrase,
                f.freq,
                fc.cpc,
                fc.impressions,
                fc.budget
            FROM frequencies f
            LEFT JOIN forecasts fc ON f.phrase = fc.phrase AND f.region = fc.region
            WHERE f.region = ?
            ORDER BY f.freq DESC
            """,
            (region,)
        )
        
        return [
            {
                'phrase': row[0],
                'freq': row[1],
                'cpc': row[2] or 0.0,
                'impressions': row[3] or 0,
                'budget': row[4] or 0.0
            }
            for row in cursor.fetchall()
        ]
