# -*- coding: utf-8 -*-
"""Проверка аккаунтов в БД для отладки"""
from services.accounts import list_accounts

def test_accounts():
    """Проверить какие аккаунты есть в БД"""
    accounts = list_accounts()

    print(f"\n{'='*70}")
    print(f"ВСЕГО АККАУНТОВ В БД: {len(accounts)}")
    print(f"{'='*70}\n")

    for idx, account in enumerate(accounts, 1):
        print(f"{idx}. {account.name}")
        print(f"   profile_path: {account.profile_path}")
        print(f"   proxy: {account.proxy}")
        print(f"   status: {account.status}")
        print(f"   created_at: {account.created_at}")
        print()

    # Фильтрация как в parsing_tab.py
    valid_accounts = []
    skipped = []

    for account in accounts:
        # Служебные аккаунты
        if account.name in ["demo_account", "wordstat_main"]:
            skipped.append((account.name, "служебный аккаунт"))
            continue

        # Нет profile_path
        if not account.profile_path or account.profile_path.strip() == "":
            skipped.append((account.name, "нет profile_path"))
            continue

        valid_accounts.append(account)

    print(f"{'='*70}")
    print(f"ВАЛИДНЫХ АККАУНТОВ ДЛЯ ПАРСИНГА: {len(valid_accounts)}")
    print(f"{'='*70}\n")

    for account in valid_accounts:
        print(f"✅ {account.name} → {account.profile_path}")

    if skipped:
        print(f"\n{'='*70}")
        print(f"ПРОПУЩЕНО: {len(skipped)}")
        print(f"{'='*70}\n")
        for name, reason in skipped:
            print(f"⏭ {name} → {reason}")

if __name__ == "__main__":
    test_accounts()
