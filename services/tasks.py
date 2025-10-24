from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select

try:
    from ..core.db import SessionLocal
    from ..core.models import Account, Task
except ImportError:
    from core.db import SessionLocal
    from core.models import Account, Task

TASK_STATUS_LABELS = {
    'queued': 'В очереди',
    'running': 'В работе',
    'completed': 'Готово',
    'failed': 'Ошибка',
}


def enqueue_task(
    *,
    account_id: int | None,
    seed_file: str,
    region: int = 225,
    headless: bool = False,
    dump_json: bool = False,
    kind: str = 'frequency',
    params: str | None = None,
) -> Task:
    with SessionLocal() as session:
        if account_id is not None:
            account = session.get(Account, account_id)
            if account is None:
                raise ValueError(f'Account {account_id} not found')
        elif kind == 'frequency':
            raise ValueError('Frequency task requires linked account')
        task = Task(
            account_id=account_id,
            seed_file=seed_file,
            region=region,
            headless=int(headless),
            dump_json=int(dump_json),
            kind=kind,
            params=params,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task


def list_pending_tasks() -> list[Task]:
    with SessionLocal() as session:
        result = session.execute(
            select(Task)
            .where(Task.status.in_(['queued', 'running']))
            .order_by(Task.created_at)
        )
        return list(result.scalars())


def list_recent_tasks(limit: int | None = 50) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        stmt = select(Task, Account).join(Account, Task.account_id == Account.id, isouter=True)
        stmt = stmt.order_by(Task.created_at.desc())
        if limit:
            stmt = stmt.limit(limit)
        rows = session.execute(stmt).all()
        tasks: list[dict[str, Any]] = []
        for task, account in rows:
            tasks.append({
                'id': task.id,
                'account_id': task.account_id,
                'account_name': account.name if account else None,
                'seed_file': task.seed_file,
                'region': task.region,
                'status': task.status,
                'status_label': get_status_label(task.status),
                'kind': task.kind,
                'params': task.params,
                'created_at': task.created_at,
                'started_at': task.started_at,
                'finished_at': task.finished_at,
                'output_path': task.output_path,
                'log_path': task.log_path,
                'error_message': task.error_message,
            })
        return tasks


def update_task_status(
    task_id: int,
    status: str,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    log_path: str | None = None,
    output_path: str | None = None,
    error_message: str | None = None,
) -> Task:
    with SessionLocal() as session:
        task = session.get(Task, task_id)
        if task is None:
            raise ValueError(f'Task {task_id} not found')
        task.status = status
        if started_at:
            task.started_at = started_at
        if finished_at:
            task.finished_at = finished_at
        if log_path:
            task.log_path = log_path
        if output_path:
            task.output_path = output_path
        if error_message:
            task.error_message = error_message
        session.commit()
        session.refresh(task)
        return task


def get_status_label(status: str) -> str:
    return TASK_STATUS_LABELS.get(status, status)
