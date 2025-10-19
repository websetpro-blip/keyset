from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import sqlite3

from sqlalchemy import create_engine, inspect, text, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / 'data'
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / 'keyset.db'

DATABASE_URL = f'sqlite:///{DB_PATH.as_posix()}'


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    """Perform lightweight SQLite migrations for the tasks table."""
    engine = ensure_schema.engine  # type: ignore[attr-defined]
    inspector = inspect(engine)
    
    # Create new tables for turbo parser pipeline
    with engine.begin() as conn:
        # Frequencies table (Wordstat results)
        if not inspector.has_table('frequencies'):
            conn.execute(text('''
                CREATE TABLE frequencies (
                    phrase TEXT PRIMARY KEY,
                    freq INTEGER,
                    region INTEGER DEFAULT 225,
                    processed BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_freq_phrase ON frequencies(phrase)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_freq_processed ON frequencies(processed)"))
        
        # Forecasts table (Direct budget results)
        if not inspector.has_table('forecasts'):
            conn.execute(text('''
                CREATE TABLE forecasts (
                    phrase TEXT PRIMARY KEY,
                    cpc REAL,
                    impressions INTEGER,
                    budget REAL,
                    freq_ref TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (freq_ref) REFERENCES frequencies(phrase)
                )
            '''))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_forecast_phrase ON forecasts(phrase)"))
        
        # Clusters table (grouped/clustered results)
        if not inspector.has_table('clusters'):
            conn.execute(text('''
                CREATE TABLE clusters (
                    stem TEXT PRIMARY KEY,
                    phrases TEXT,
                    avg_freq REAL,
                    total_budget REAL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cluster_stem ON clusters(stem)"))
    
    if inspector.has_table('accounts'):
        with engine.begin() as conn:
            columns = {row[1] for row in conn.execute(text('PRAGMA table_info(accounts)'))}
            if 'proxy_id' not in columns:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN proxy_id VARCHAR(64)"))
            if 'proxy_strategy' not in columns:
                conn.execute(text("ALTER TABLE accounts ADD COLUMN proxy_strategy VARCHAR(32) DEFAULT 'fixed'"))
                conn.execute(text("UPDATE accounts SET proxy_strategy = 'fixed' WHERE proxy_strategy IS NULL"))

    if not inspector.has_table('tasks'):
        return

    if not inspector.has_table('freq_results'):
        with engine.begin() as conn:
            conn.execute(text('''
                CREATE TABLE freq_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mask TEXT NOT NULL,
                    region INTEGER NOT NULL DEFAULT 225,
                    status TEXT NOT NULL DEFAULT 'queued',
                    freq_total INTEGER NOT NULL DEFAULT 0,
                    freq_exact INTEGER NOT NULL DEFAULT 0,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(mask, region)
                )
            '''))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_freq_status ON freq_results(status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_freq_updated ON freq_results(updated_at)"))

    with engine.begin() as conn:
        info_rows = list(conn.execute(text('PRAGMA table_info(tasks)')))
        if not info_rows:
            return
        col_names = {row[1] for row in info_rows}
        account_notnull = any(row[1] == 'account_id' and row[3] == 1 for row in info_rows)
        needs_kind = 'kind' not in col_names
        needs_params = 'params' not in col_names

        if account_notnull:
            conn.execute(text('PRAGMA foreign_keys=OFF'))
            kind_select = 'kind' if 'kind' in col_names else "'frequency'"
            params_select = 'params' if 'params' in col_names else 'NULL'
            conn.execute(text('''
                CREATE TABLE tasks_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER REFERENCES accounts(id),
                    seed_file VARCHAR(255) NOT NULL,
                    region INTEGER DEFAULT 225,
                    headless INTEGER DEFAULT 0,
                    dump_json INTEGER DEFAULT 0,
                    created_at DATETIME NOT NULL,
                    started_at DATETIME,
                    finished_at DATETIME,
                    status VARCHAR(32) DEFAULT 'queued',
                    log_path VARCHAR(255),
                    output_path VARCHAR(255),
                    error_message TEXT,
                    kind VARCHAR(16) DEFAULT 'frequency',
                    params TEXT
                )
            '''))
            conn.execute(text(f'''INSERT INTO tasks_new (
                    id, account_id, seed_file, region, headless, dump_json,
                    created_at, started_at, finished_at, status,
                    log_path, output_path, error_message, kind, params
                )
                SELECT
                    id, account_id, seed_file, region, headless, dump_json,
                    created_at, started_at, finished_at, status,
                    log_path, output_path, error_message,
                    {kind_select}, {params_select}
                FROM tasks
            '''))
            conn.execute(text('DROP TABLE tasks'))
            conn.execute(text('ALTER TABLE tasks_new RENAME TO tasks'))
            conn.execute(text('PRAGMA foreign_keys=ON'))
            needs_kind = False
            needs_params = False
        if needs_kind:
            conn.execute(text("ALTER TABLE tasks ADD COLUMN kind VARCHAR(16) DEFAULT 'frequency'"))
            conn.execute(text("UPDATE tasks SET kind = 'frequency' WHERE kind IS NULL"))
        if needs_params:
            conn.execute(text('ALTER TABLE tasks ADD COLUMN params TEXT'))


engine = create_engine(
    DATABASE_URL, 
    echo=False, 
    future=True,
    connect_args={"check_same_thread": False}
)


# Enable WAL mode for better concurrency
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


ensure_schema.engine = engine  # type: ignore[attr-defined]

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    future=True,
    expire_on_commit=False,
)


@contextmanager
def get_db_connection():
    """Context manager for direct SQLite connection (for batch operations)."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row  # Access columns by name
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


__all__ = ['Base', 'engine', 'SessionLocal', 'DB_PATH', 'ensure_schema', 'get_db_connection']
