﻿from __future__ import annotations

import re
from pathlib import Path

from . import accounts as account_service

ACCOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def parse_accounts_from_text(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines()]
    entries: list[dict] = []
    current: dict | None = None

    def push_entry():
        nonlocal current
        if current and current.get('name'):
            entries.append(current)
        current = None

    for line in lines:
        if not line:
            continue
        if ACCOUNT_NAME_RE.match(line):
            push_entry()
            current = {'name': line}
            continue
        if current is None:
            continue
        if ':' in line:
            key_part, value_part = line.split(':', 1)
            key = key_part.strip().lower()
            value = value_part.strip()
        else:
            key = ''
            value = line
        if not value:
            continue
        if key in ('логин', 'login'):
            current['login'] = value
            continue
        if key in ('пароль', 'password', 'pass', 'pwd'):
            current['password'] = value
            continue
        if key in ('прокси', 'proxy'):
            current['proxy'] = value
            continue
        current.setdefault('notes_extra', []).append(line)
    push_entry()
    return entries


def import_accounts_from_file(path: str | Path, profiles_root: str | Path = '.profiles') -> int:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        text = path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        text = path.read_text(encoding='cp1251', errors='ignore')
    entries = parse_accounts_from_text(text)
    imported = 0
    for entry in entries:
        name = entry['name']
        profile_path = str(Path(profiles_root) / name)
        proxy = entry.get('proxy')
        notes_parts = []
        if entry.get('login'):
            notes_parts.append(f"Логин: {entry['login']}")
        if entry.get('password'):
            notes_parts.append(f"Пароль: {entry['password']}")
        if entry.get('notes_extra'):
            notes_parts.extend(entry['notes_extra'])
        notes = '\n'.join(notes_parts) if notes_parts else None
        account_service.upsert_account(name=name, profile_path=profile_path, proxy=proxy, notes=notes)
        imported += 1
    return imported

