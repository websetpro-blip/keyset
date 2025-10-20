# -*- coding: utf-8 -*-
"""
Helpers for fixing mojibake strings that were double-encoded.

Example of corruption this handles:
    "РќРµ РїРѕРЅСЏС‚РЅРѕ"  ->  "Не понятно"
"""

from __future__ import annotations

from typing import Optional


def fix_mojibake(value: Optional[str]) -> Optional[str]:
    """Attempt to recover typical cp1251/latin1 mojibake artifacts.

    The conversion is best-effort: if decoding fails we return the original
    string untouched to avoid swallowing information.
    """
    if value is None or not isinstance(value, str):
        return value

    # Heuristic: only attempt recovery if mojibake markers present
    suspicious = any(ch in value for ch in ("Ð", "Ñ", "Ò", "Ó", "Р", "Ѓ", "�"))
    if not suspicious:
        return value

    # Try latin1 -> utf-8 (common when UTF-8 bytes were read as latin1)
    try:
        return value.encode("latin1").decode("utf-8")
    except UnicodeError:
        pass

    # Try cp1251 -> utf-8 (second common variant)
    try:
        return value.encode("cp1251", errors="ignore").decode("utf-8", errors="ignore")
    except UnicodeError:
        return value

    return value


def fix_dict_strings(data: dict) -> dict:
    """Recursively fix all string values inside a dict."""
    from collections.abc import Mapping, MutableMapping

    if isinstance(data, MutableMapping):
        for key, val in list(data.items()):
            if isinstance(val, str):
                data[key] = fix_mojibake(val)
            elif isinstance(val, Mapping):
                data[key] = fix_dict_strings(dict(val))
            elif isinstance(val, list):
                data[key] = [fix_mojibake(item) if isinstance(item, str) else item for item in val]
    return data


# JavaScript shim that normalizes Wordstat fetch responses back to the legacy schema.
WORDSTAT_FETCH_NORMALIZER_SCRIPT = r"""
(() => {
  const TARGET = /\/wordstat\/api\/search/;

  const normalizeEntries = (items = []) =>
    items
      .map((item) => {
        if (typeof item === 'string') {
          return { phrase: item, count: 0 };
        }
        if (Array.isArray(item)) {
          return { phrase: String(item[0] ?? ''), count: Number(item[1] ?? 0) };
        }
        if (item && typeof item === 'object') {
          const phrase = item.text ?? item.phrase ?? item.key ?? item.title ?? '';
          const value = item.value ?? item.count ?? item.freq ?? 0;
          return { phrase, count: Number(value) };
        }
        return null;
      })
      .filter((entry) => entry && entry.phrase);

  const wrapFetch = (origFetch) => async (input, init) => {
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    const response = await origFetch(input, init);
    if (!TARGET.test(url)) {
      return response;
    }

    try {
      const ct = response.headers?.get?.('content-type') ?? '';
      if (!ct.includes('application/json')) {
        return response;
      }

      const clone = response.clone();
      const data = await clone.json();
      const table = data && data.table;
      const tableData = table && table.tableData;
      if (tableData) {
        if (!Array.isArray(table.items) || !table.items.length) {
          table.items = normalizeEntries(tableData.popular);
        }
        if (!Array.isArray(table.related) || !table.related.length) {
          table.related = normalizeEntries(tableData.associations || tableData.similar);
        }
      }

      return new Response(JSON.stringify(data), {
        status: response.status,
        statusText: response.statusText,
        headers: { 'content-type': 'application/json; charset=utf-8' },
      });
    } catch (error) {
      console.warn('[WS_NORMALIZER] unable to normalize response', error);
      return response;
    }
  };

  const patchFetch = () => {
    if (typeof fetch !== 'function') {
      return;
    }
    const wrapped = wrapFetch(fetch.bind(globalThis));
    globalThis.fetch = wrapped;
    if (typeof window !== 'undefined') {
      window.fetch = wrapped;
    }
  };

  patchFetch();
})();
"""
