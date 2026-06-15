"""Створення та ініціалізація бази даних SQLite."""

import sqlite3
import os
from config import DB_PATH


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA mmap_size=268435456")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Створити таблиці якщо їх немає."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tz_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            source_url TEXT,
            unique_acceptors INTEGER DEFAULT 0,
            unique_donors INTEGER DEFAULT 0,
            total_rows INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            processed_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_tz_source_url
            ON tz_files(source_url) WHERE source_url IS NOT NULL;

        CREATE TABLE IF NOT EXISTS stoplist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acceptor TEXT NOT NULL,
            donor TEXT NOT NULL,
            UNIQUE(acceptor, donor)
        );

        CREATE INDEX IF NOT EXISTS idx_stoplist_acceptor
            ON stoplist(acceptor);
        CREATE INDEX IF NOT EXISTS idx_stoplist_donor
            ON stoplist(donor);

        -- Повні дані стоп-листа (всі колонки з Звіт замовнику)
        CREATE TABLE IF NOT EXISTS stoplist_full (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acceptor TEXT NOT NULL,
            month TEXT,
            donor TEXT NOT NULL,
            acceptor_url TEXT,
            anchor TEXT,
            final_url TEXT,
            backup_url TEXT,
            tz_file_id INTEGER NOT NULL,
            row_number INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_full_acceptor
            ON stoplist_full(acceptor);
        CREATE INDEX IF NOT EXISTS idx_full_tz
            ON stoplist_full(tz_file_id);
        CREATE INDEX IF NOT EXISTS idx_full_donor
            ON stoplist_full(donor);

        CREATE TABLE IF NOT EXISTS stoplist_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            acceptor TEXT NOT NULL,
            donor TEXT NOT NULL,
            source_column TEXT,
            tz_file_id INTEGER NOT NULL,
            row_number INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_raw_acceptor
            ON stoplist_raw(acceptor);
        CREATE INDEX IF NOT EXISTS idx_raw_tz
            ON stoplist_raw(tz_file_id);
        CREATE INDEX IF NOT EXISTS idx_raw_donor
            ON stoplist_raw(donor);

        -- Бренди (TitleKW)
        CREATE TABLE IF NOT EXISTS brand_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            original_value TEXT NOT NULL,
            normalized TEXT NOT NULL,
            source_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_brand_normalized
            ON brand_raw(normalized);

        CREATE TABLE IF NOT EXISTS brand_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_name TEXT NOT NULL UNIQUE,
            normalized TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS brand_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_group_id INTEGER NOT NULL,
            alias_normalized TEXT NOT NULL UNIQUE,
            FOREIGN KEY (brand_group_id) REFERENCES brand_groups(id)
        );

        CREATE INDEX IF NOT EXISTS idx_alias_norm
            ON brand_aliases(alias_normalized);

        CREATE TABLE IF NOT EXISTS brand_tz_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_url TEXT UNIQUE,
            name TEXT,
            status TEXT DEFAULT 'done',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Міграція: додати import_session_id у tz_files якщо немає
    cur = conn.execute("PRAGMA table_info(tz_files)")
    existing_cols = {row[1] for row in cur.fetchall()}
    if "import_session_id" not in existing_cols:
        conn.execute("ALTER TABLE tz_files ADD COLUMN import_session_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tz_session ON tz_files(import_session_id)"
    )

    conn.commit()
    conn.close()
