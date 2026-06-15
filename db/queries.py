"""Всі запити до бази даних."""

from db.schema import get_connection
from config import BATCH_INSERT_SIZE


# --- TZ Files ---

def insert_tz_file(name, source_url=None, import_session_id=None):
    """Додати запис ТЗ. Повертає id."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tz_files (name, source_url, import_session_id) VALUES (?, ?, ?)",
            (name, source_url, import_session_id)
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_tz_file(tz_id, **kwargs):
    """Оновити поля ТЗ файлу."""
    allowed = {"unique_acceptors", "unique_donors", "total_rows",
               "status", "error_message", "processed_at", "name"}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [tz_id]
    conn = get_connection()
    try:
        conn.execute(f"UPDATE tz_files SET {set_clause} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def get_tz_by_url(url):
    """Знайти ТЗ за URL (щоб не обробляти двічі)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tz_files WHERE source_url = ?", (url,)
        ).fetchone()
    finally:
        conn.close()


def get_all_tz_files():
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM tz_files ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()


def delete_tz_file(tz_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM stoplist_raw WHERE tz_file_id = ?", (tz_id,))
        conn.execute("DELETE FROM stoplist_full WHERE tz_file_id = ?", (tz_id,))
        conn.execute("DELETE FROM tz_files WHERE id = ?", (tz_id,))
        # Перебудувати stoplist з raw + full даних
        conn.execute("DELETE FROM stoplist")
        conn.execute("""
            INSERT OR IGNORE INTO stoplist (acceptor, donor)
            SELECT DISTINCT acceptor, donor FROM stoplist_raw
        """)
        conn.execute("""
            INSERT OR IGNORE INTO stoplist (acceptor, donor)
            SELECT DISTINCT acceptor, donor FROM stoplist_full
        """)
        conn.commit()
    finally:
        conn.close()


# --- Stoplist ---

def insert_stoplist_batch(rows, tz_file_id):
    """Вставити пакет записів.
    rows: list of (acceptor, donor, source_column, row_number)
    """
    conn = get_connection()
    try:
        # Вставляємо в raw (всі записи)
        raw_data = [(r[0], r[1], r[2], tz_file_id, r[3]) for r in rows]
        conn.executemany("""
            INSERT INTO stoplist_raw (acceptor, donor, source_column, tz_file_id, row_number)
            VALUES (?, ?, ?, ?, ?)
        """, raw_data)

        # Вставляємо унікальні пари в stoplist
        unique_data = [(r[0], r[1]) for r in rows]
        conn.executemany("""
            INSERT OR IGNORE INTO stoplist (acceptor, donor)
            VALUES (?, ?)
        """, unique_data)

        conn.commit()
    finally:
        conn.close()


def insert_stoplist_full_batch(rows, tz_file_id):
    """Вставити повні записи з Звіту замовнику.
    rows: list of (acceptor, month, donor, acceptor_url, anchor, final_url, backup_url, row_number)
    """
    conn = get_connection()
    try:
        data = [(r[0], r[1], r[2], r[3], r[4], r[5], r[6], tz_file_id, r[7]) for r in rows]
        conn.executemany("""
            INSERT INTO stoplist_full
                (acceptor, month, donor, acceptor_url, anchor, final_url, backup_url, tz_file_id, row_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, data)

        # Також в унікальні пари
        unique_data = [(r[0], r[2]) for r in rows]
        conn.executemany("""
            INSERT OR IGNORE INTO stoplist (acceptor, donor)
            VALUES (?, ?)
        """, unique_data)

        conn.commit()
    finally:
        conn.close()


def get_stoplist_full_export_cursor(session_ids=None):
    """Курсор для потокового експорту повного стоп-листа.

    session_ids: якщо передано — повертає тільки рядки з tz_files з цими
        import_session_id. Спеціальне значення '__legacy__' означає
        tz_files без import_session_id (старі імпорти до міграції).
    """
    conn = get_connection()

    if session_ids:
        real_ids = [s for s in session_ids if s != "__legacy__"]
        include_legacy = "__legacy__" in session_ids

        clauses = []
        params = []
        if real_ids:
            placeholders = ",".join("?" * len(real_ids))
            clauses.append(f"import_session_id IN ({placeholders})")
            params.extend(real_ids)
        if include_legacy:
            clauses.append("import_session_id IS NULL")

        where_tz = " OR ".join(clauses) if clauses else "1=0"

        sql = f"""
            SELECT acceptor, month, donor, acceptor_url, anchor, final_url, backup_url
            FROM stoplist_full
            WHERE tz_file_id IN (
                SELECT id FROM tz_files WHERE {where_tz}
            )
            ORDER BY acceptor, id
        """
        cursor = conn.execute(sql, params)
    else:
        cursor = conn.execute("""
            SELECT acceptor, month, donor, acceptor_url, anchor, final_url, backup_url
            FROM stoplist_full
            ORDER BY acceptor, id
        """)
    return conn, cursor


def count_rows_for_sessions(session_ids=None):
    """Кількість рядків у stoplist_full для заданих сесій (або всіх)."""
    conn = get_connection()
    try:
        if not session_ids:
            return conn.execute("SELECT COUNT(*) FROM stoplist_full").fetchone()[0]

        real_ids = [s for s in session_ids if s != "__legacy__"]
        include_legacy = "__legacy__" in session_ids

        clauses = []
        params = []
        if real_ids:
            placeholders = ",".join("?" * len(real_ids))
            clauses.append(f"import_session_id IN ({placeholders})")
            params.extend(real_ids)
        if include_legacy:
            clauses.append("import_session_id IS NULL")

        if not clauses:
            return 0
        where_tz = " OR ".join(clauses)

        sql = f"""
            SELECT COUNT(*) FROM stoplist_full
            WHERE tz_file_id IN (
                SELECT id FROM tz_files WHERE {where_tz}
            )
        """
        return conn.execute(sql, params).fetchone()[0]
    finally:
        conn.close()


def get_import_sessions(limit=50):
    """Список імпорт-сесій з агрегованою статистикою.

    Повертає список dict-ів, відсортованих за started_at DESC.
    Сесія '__legacy__' — це tz_files без import_session_id (до міграції).
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                COALESCE(import_session_id, '__legacy__') AS session_id,
                MIN(created_at) AS started_at,
                MAX(COALESCE(processed_at, created_at)) AS finished_at,
                COUNT(*) AS tz_count,
                COALESCE(SUM(total_rows), 0) AS total_rows,
                COALESCE(SUM(unique_acceptors), 0) AS sum_acceptors,
                COALESCE(SUM(unique_donors), 0) AS sum_donors
            FROM tz_files
            WHERE status = 'done'
            GROUP BY COALESCE(import_session_id, '__legacy__')
            ORDER BY started_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Статистика ---

def get_global_stats():
    conn = get_connection()
    try:
        total_acceptors = conn.execute(
            "SELECT COUNT(DISTINCT acceptor) FROM stoplist"
        ).fetchone()[0]
        total_donors = conn.execute(
            "SELECT COUNT(DISTINCT donor) FROM stoplist"
        ).fetchone()[0]
        total_pairs = conn.execute(
            "SELECT COUNT(*) FROM stoplist"
        ).fetchone()[0]
        total_raw = conn.execute(
            "SELECT COUNT(*) FROM stoplist_raw"
        ).fetchone()[0]
        total_tz = conn.execute(
            "SELECT COUNT(*) FROM tz_files WHERE status = 'done'"
        ).fetchone()[0]
        total_tz_all = conn.execute(
            "SELECT COUNT(*) FROM tz_files"
        ).fetchone()[0]
        return {
            "total_acceptors": total_acceptors,
            "total_unique_donors": total_donors,
            "total_unique_pairs": total_pairs,
            "total_raw_records": total_raw,
            "total_duplicates": total_raw - total_pairs,
            "total_tz_done": total_tz,
            "total_tz_all": total_tz_all,
        }
    finally:
        conn.close()


def get_acceptor_stats(limit=50, offset=0, search=None, sort_by="unique_donors", sort_dir="desc"):
    """Статистика по акцепторах з пагінацією."""
    conn = get_connection()
    try:
        where = ""
        params = []
        if search:
            where = "WHERE s.acceptor LIKE ?"
            params.append(f"%{search}%")

        # Дозволені поля для сортування
        allowed_sorts = {"acceptor", "unique_donors", "total_entries", "duplicates"}
        if sort_by not in allowed_sorts:
            sort_by = "unique_donors"
        if sort_dir not in ("asc", "desc"):
            sort_dir = "desc"

        total = conn.execute(
            f"SELECT COUNT(DISTINCT acceptor) FROM stoplist s {where.replace('s.acceptor', 'acceptor') if where else ''}",
            params
        ).fetchone()[0]

        rows = conn.execute(f"""
            SELECT
                s.acceptor,
                COUNT(DISTINCT s.donor) as unique_donors,
                COALESCE(r.total_entries, 0) as total_entries,
                COALESCE(r.total_entries, 0) - COUNT(DISTINCT s.donor) as duplicates
            FROM stoplist s
            LEFT JOIN (
                SELECT acceptor, COUNT(*) as total_entries
                FROM stoplist_raw
                GROUP BY acceptor
            ) r ON s.acceptor = r.acceptor
            {where}
            GROUP BY s.acceptor
            ORDER BY {sort_by} {sort_dir}
            LIMIT ? OFFSET ?
        """, params + [limit, offset]).fetchall()

        return {"total": total, "rows": [dict(r) for r in rows]}
    finally:
        conn.close()


def get_donors_for_acceptor(acceptor, limit=100, offset=0):
    """Отримати донорів для конкретного акцептора."""
    conn = get_connection()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM stoplist WHERE acceptor = ?", (acceptor,)
        ).fetchone()[0]

        rows = conn.execute("""
            SELECT donor FROM stoplist
            WHERE acceptor = ?
            ORDER BY donor
            LIMIT ? OFFSET ?
        """, (acceptor, limit, offset)).fetchall()

        return {"total": total, "donors": [r["donor"] for r in rows]}
    finally:
        conn.close()


def get_all_acceptors():
    """Всі унікальні акцептори."""
    conn = get_connection()
    try:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT acceptor FROM stoplist ORDER BY acceptor"
        ).fetchall()]
    finally:
        conn.close()


def get_stoplist_export_cursor():
    """Курсор для потокового експорту стоп-листа."""
    conn = get_connection()
    cursor = conn.execute("""
        SELECT acceptor, donor
        FROM stoplist
        ORDER BY acceptor, donor
    """)
    return conn, cursor


def get_tz_stats():
    """Статистика по кожному ТЗ."""
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT
                t.id, t.name, t.source_url, t.status,
                t.unique_acceptors, t.unique_donors, t.total_rows,
                t.error_message, t.processed_at, t.created_at
            FROM tz_files t
            ORDER BY t.created_at DESC
        """).fetchall()
    finally:
        conn.close()


def clear_all():
    """Очистити всі дані стоп-листа."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM stoplist_raw")
        conn.execute("DELETE FROM stoplist")
        conn.execute("DELETE FROM tz_files")
        conn.commit()
    finally:
        conn.close()
    conn = get_connection()
    try:
        conn.execute("VACUUM")
    finally:
        conn.close()


# --- Бренди ---

def insert_brand_raw_batch(rows):
    """Вставити пакет сирих записів брендів.
    rows: list of (original_value, normalized, source_url)
    """
    conn = get_connection()
    try:
        conn.executemany(
            "INSERT INTO brand_raw (original_value, normalized, source_url) VALUES (?, ?, ?)",
            rows
        )
        conn.commit()
    finally:
        conn.close()


def insert_brand_tz(source_url, name):
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO brand_tz_files (source_url, name) VALUES (?, ?)",
            (source_url, name)
        )
        conn.commit()
    finally:
        conn.close()


def is_brand_tz_processed(source_url):
    conn = get_connection()
    try:
        r = conn.execute(
            "SELECT id FROM brand_tz_files WHERE source_url = ?", (source_url,)
        ).fetchone()
        return r is not None
    finally:
        conn.close()


def get_brand_raw_grouped():
    """Отримати всі сирі записи згруповані по normalized."""
    conn = get_connection()
    try:
        return conn.execute("""
            SELECT normalized, COUNT(*) as cnt,
                   GROUP_CONCAT(DISTINCT original_value) as variations
            FROM brand_raw
            GROUP BY normalized
            ORDER BY cnt DESC
        """).fetchall()
    finally:
        conn.close()


def get_brand_groups():
    """Отримати всі групи брендів з аліасами."""
    conn = get_connection()
    try:
        groups = conn.execute("""
            SELECT bg.id, bg.brand_name, bg.normalized,
                   COUNT(DISTINCT br.id) as total_mentions,
                   GROUP_CONCAT(DISTINCT br.original_value) as variations
            FROM brand_groups bg
            LEFT JOIN brand_aliases ba ON bg.id = ba.brand_group_id
            LEFT JOIN brand_raw br ON br.normalized = ba.alias_normalized
            GROUP BY bg.id
            ORDER BY total_mentions DESC
        """).fetchall()
        return [dict(g) for g in groups]
    finally:
        conn.close()


def save_brand_group(brand_name, normalized, alias_list):
    """Зберегти групу бренду з аліасами."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT OR REPLACE INTO brand_groups (brand_name, normalized) VALUES (?, ?)",
            (brand_name, normalized)
        )
        group_id = cur.lastrowid
        for alias in alias_list:
            conn.execute(
                "INSERT OR IGNORE INTO brand_aliases (brand_group_id, alias_normalized) VALUES (?, ?)",
                (group_id, alias)
            )
        conn.commit()
        return group_id
    finally:
        conn.close()


def merge_brand_groups(target_id, source_id):
    """Об'єднати дві групи брендів."""
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE brand_aliases SET brand_group_id = ? WHERE brand_group_id = ?",
            (target_id, source_id)
        )
        conn.execute("DELETE FROM brand_groups WHERE id = ?", (source_id,))
        conn.commit()
    finally:
        conn.close()


def auto_group_brands():
    """Автоматично згрупувати бренди за normalized значенням.
    Створює групу для кожного унікального normalized.
    """
    conn = get_connection()
    try:
        # Очищаємо існуючі групи
        conn.execute("DELETE FROM brand_aliases")
        conn.execute("DELETE FROM brand_groups")

        # Отримуємо всі унікальні normalized значення
        rows = conn.execute("""
            SELECT DISTINCT normalized FROM brand_raw ORDER BY normalized
        """).fetchall()

        for row in rows:
            norm = row[0]
            if not norm:
                continue
            # Шукаємо найчастіше оригінальне значення як назву бренду
            best_name = conn.execute("""
                SELECT original_value, COUNT(*) as cnt
                FROM brand_raw WHERE normalized = ?
                GROUP BY original_value ORDER BY cnt DESC LIMIT 1
            """, (norm,)).fetchone()

            brand_name = best_name[0] if best_name else norm
            cur = conn.execute(
                "INSERT INTO brand_groups (brand_name, normalized) VALUES (?, ?)",
                (brand_name, norm)
            )
            group_id = cur.lastrowid
            conn.execute(
                "INSERT INTO brand_aliases (brand_group_id, alias_normalized) VALUES (?, ?)",
                (group_id, norm)
            )

        conn.commit()

        # Тепер мерджимо схожі групи (де один normalized є підрядком іншого)
        groups = conn.execute(
            "SELECT id, normalized FROM brand_groups ORDER BY LENGTH(normalized)"
        ).fetchall()

        merged = set()
        for i, g1 in enumerate(groups):
            if g1[0] in merged:
                continue
            for g2 in groups[i+1:]:
                if g2[0] in merged:
                    continue
                # Якщо коротший normalized є підрядком довшого — мерджимо
                if g1[1] in g2[1] and len(g1[1]) >= 3:
                    conn.execute(
                        "UPDATE brand_aliases SET brand_group_id = ? WHERE brand_group_id = ?",
                        (g1[0], g2[0])
                    )
                    conn.execute("DELETE FROM brand_groups WHERE id = ?", (g2[0],))
                    merged.add(g2[0])

        conn.commit()
    finally:
        conn.close()


def get_brand_stats():
    """Загальна статистика по брендах."""
    conn = get_connection()
    try:
        total_raw = conn.execute("SELECT COUNT(*) FROM brand_raw").fetchone()[0]
        total_unique_norm = conn.execute("SELECT COUNT(DISTINCT normalized) FROM brand_raw").fetchone()[0]
        total_groups = conn.execute("SELECT COUNT(*) FROM brand_groups").fetchone()[0]
        total_tz = conn.execute("SELECT COUNT(*) FROM brand_tz_files").fetchone()[0]
        return {
            "total_raw": total_raw,
            "total_unique_normalized": total_unique_norm,
            "total_groups": total_groups,
            "total_tz": total_tz,
        }
    finally:
        conn.close()


def clear_brands():
    """Очистити всі дані брендів."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM brand_raw")
        conn.execute("DELETE FROM brand_aliases")
        conn.execute("DELETE FROM brand_groups")
        conn.execute("DELETE FROM brand_tz_files")
        conn.commit()
    finally:
        conn.close()
