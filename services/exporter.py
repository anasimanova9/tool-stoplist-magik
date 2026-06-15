"""Експорт стоп-листа в Excel файли."""

import os
import xlsxwriter
from config import EXPORT_DIR, MAX_EXCEL_ROWS
from db.queries import (
    get_stoplist_full_export_cursor,
    get_global_stats,
    count_rows_for_sessions,
)


def export_stoplist(progress_callback=None, session_ids=None):
    """Експортувати стоп-лист в Excel файли.

    Новий формат:
    - Рядок акцептора (жирний, з фоном)
    - Заголовки: Місяць | Домен | Анкор | Final URL | Запаска
    - Рядки даних
    - 2 порожні рядки
    - Наступний акцептор...

    Якщо той самий акцептор зустрічається в різних ТЗ — дописується до існуючого блоку.

    Розбиває на кілька файлів якщо більше MAX_EXCEL_ROWS рядків.

    session_ids: якщо передано — експортуються тільки рядки з tz_files,
        чий import_session_id у цьому списку. Файли отримують префікс
        stoplist_selected_part_ замість stoplist_part_.

    Повертає список створених файлів.
    """
    os.makedirs(EXPORT_DIR, exist_ok=True)

    file_prefix = "stoplist_selected_part_" if session_ids else "stoplist_part_"

    # Очищаємо тільки файли свого префіксу
    for f in os.listdir(EXPORT_DIR):
        if f.startswith(file_prefix) and f.endswith(".xlsx"):
            os.remove(os.path.join(EXPORT_DIR, f))

    if session_ids:
        total_records = count_rows_for_sessions(session_ids)
    else:
        stats = get_global_stats()
        total_records = stats["total_raw_records"]

    conn, cursor = get_stoplist_full_export_cursor(session_ids=session_ids)

    files_created = []
    file_num = 1
    current_row = 0
    current_acceptor = None
    acceptor_rows = []  # список (month, donor, acceptor_url, anchor, final_url, backup_url)
    processed = 0

    workbook = None
    worksheet = None
    acceptor_fmt = None
    header_fmt = None
    data_fmt = None
    url_fmt = None

    def start_new_file():
        nonlocal workbook, worksheet, acceptor_fmt, header_fmt, data_fmt, url_fmt
        nonlocal current_row, file_num
        filename = f"{file_prefix}{file_num:02d}.xlsx"
        filepath = os.path.join(EXPORT_DIR, filename)
        workbook = xlsxwriter.Workbook(filepath, {'constant_memory': True})
        worksheet = workbook.add_worksheet("Стоп-лист")

        acceptor_fmt = workbook.add_format({
            'bold': True,
            'bg_color': '#2C3E50',
            'font_color': 'white',
            'font_size': 12,
        })
        header_fmt = workbook.add_format({
            'bold': True,
            'bg_color': '#D6EAF8',
            'font_size': 10,
            'border': 1,
        })
        data_fmt = workbook.add_format({'font_size': 10})
        url_fmt = workbook.add_format({'font_size': 10})

        # Ширина колонок
        worksheet.set_column(0, 0, 14)  # Місяць
        worksheet.set_column(1, 1, 35)  # Домен
        worksheet.set_column(2, 2, 35)  # Акцептор
        worksheet.set_column(3, 3, 35)  # Анкор
        worksheet.set_column(4, 4, 55)  # Final URL
        worksheet.set_column(5, 5, 55)  # Запаска

        current_row = 0
        files_created.append(filename)
        file_num += 1

    def write_acceptor_block(acceptor, rows):
        nonlocal current_row, workbook, worksheet

        # Перевіряємо чи потрібен новий файл
        # акцептор + заголовки + дані + 2 порожні рядки
        block_size = 1 + 1 + len(rows) + 2
        if current_row + block_size > MAX_EXCEL_ROWS:
            workbook.close()
            start_new_file()

        # Рядок акцептора
        worksheet.merge_range(current_row, 0, current_row, 5, acceptor, acceptor_fmt)
        current_row += 1

        # Заголовки колонок
        headers = ["Місяць", "Домен", "Акцептор", "Анкор", "Final URL", "Запаска"]
        for col, h in enumerate(headers):
            worksheet.write(current_row, col, h, header_fmt)
        current_row += 1

        # Дані
        for row_data in rows:
            month, donor, acceptor_url, anchor, final_url, backup_url = row_data
            worksheet.write_string(current_row, 0, month or '', data_fmt)
            worksheet.write_string(current_row, 1, donor or '', data_fmt)
            worksheet.write_string(current_row, 2, acceptor_url or '', data_fmt)
            worksheet.write_string(current_row, 3, anchor or '', data_fmt)
            worksheet.write_string(current_row, 4, final_url or '', data_fmt)
            worksheet.write_string(current_row, 5, backup_url or '', data_fmt)
            current_row += 1

        # 2 порожні рядки-розділювачі
        current_row += 2

    start_new_file()

    try:
        for row in cursor:
            acceptor = row[0]
            month = row[1]
            donor = row[2]
            acceptor_url = row[3]
            anchor = row[4]
            final_url = row[5]
            backup_url = row[6]
            processed += 1

            if acceptor != current_acceptor:
                # Записуємо попередній блок
                if current_acceptor is not None and acceptor_rows:
                    write_acceptor_block(current_acceptor, acceptor_rows)
                current_acceptor = acceptor
                acceptor_rows = []

            acceptor_rows.append((month, donor, acceptor_url, anchor, final_url, backup_url))

            if progress_callback and processed % 5000 == 0:
                progress_callback(processed, total_records,
                                  files_created[-1] if files_created else "")

        # Записуємо останній блок
        if current_acceptor is not None and acceptor_rows:
            write_acceptor_block(current_acceptor, acceptor_rows)

    finally:
        if workbook:
            workbook.close()
        conn.close()

    if progress_callback:
        progress_callback(total_records, total_records,
                          files_created[-1] if files_created else "")

    return files_created
