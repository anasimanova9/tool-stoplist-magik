"""StopList Tool — Інструмент стоп-листа донорів."""

import os
import sys
import time
import threading
import webbrowser
from datetime import datetime

from flask import (Flask, render_template, request, jsonify,
                   send_from_directory, redirect, url_for)

# Додаємо кореневу папку до sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import BASE_DIR, PORT, UPLOAD_DIR, EXPORT_DIR, SHEETS_DOWNLOAD_DELAY, BATCH_INSERT_SIZE
from db.schema import init_db
from db import queries
from services import parser, sheets, exporter

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB max upload

# --- Стан фонових задач ---
job_state = {
    "type": None,       # "import" або "export"
    "running": False,
    "cancelled": False,
    "total": 0,
    "processed": 0,
    "current_item": "",
    "errors": [],
    "failed_urls": [],   # список URL таблиць, які не вдалося скачати
    "completed_files": [],
    "stats": {},
}
job_lock = threading.Lock()


def reset_job():
    with job_lock:
        job_state.update({
            "type": None,
            "running": False,
            "cancelled": False,
            "total": 0,
            "processed": 0,
            "current_item": "",
            "errors": [],
            "failed_urls": [],
            "completed_files": [],
            "stats": {},
        })


# ============ СТОРІНКИ ============

@app.route("/")
def index():
    stats = queries.get_global_stats()
    return render_template("index.html", stats=stats)


@app.route("/import")
def import_page():
    return render_template("import.html")


@app.route("/stoplist")
def stoplist_page():
    return render_template("stoplist.html")


@app.route("/stats")
def stats_page():
    return render_template("stats.html")


@app.route("/export")
def export_page():
    stats = queries.get_global_stats()
    # Список вже створених файлів (повний + вибірковий експорт)
    existing = []
    if os.path.exists(EXPORT_DIR):
        existing = sorted([
            f for f in os.listdir(EXPORT_DIR)
            if (f.startswith("stoplist_part_") or f.startswith("stoplist_selected_part_"))
                and f.endswith(".xlsx")
        ])
    return render_template("export.html", stats=stats, existing_files=existing)


@app.route("/brands")
def brands_page():
    return render_template("brands.html")


# ============ API: ІМПОРТ ============

@app.route("/api/import/urls", methods=["POST"])
def api_import_urls():
    """Імпорт ТЗ за посиланнями на Google Sheets."""
    if job_state["running"]:
        return jsonify({"error": "Вже виконується інша задача. Зачекайте."}), 409

    data = request.get_json()
    urls = data.get("urls", [])
    is_master = data.get("is_master", False)

    if not urls:
        return jsonify({"error": "Не вказано жодного посилання."}), 400

    # Запускаємо фонову задачу
    thread = threading.Thread(
        target=_import_urls_worker,
        args=(urls, is_master),
        daemon=True
    )
    thread.start()

    return jsonify({"status": "started"})


@app.route("/api/import/files", methods=["POST"])
def api_import_files():
    """Імпорт ТЗ із завантажених файлів (Excel/CSV)."""
    if job_state["running"]:
        return jsonify({"error": "Вже виконується інша задача. Зачекайте."}), 409

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Не вибрано жодного файлу."}), 400

    # Зберігаємо файли
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved_paths = []
    for f in files:
        if f.filename:
            filepath = os.path.join(UPLOAD_DIR, f.filename)
            f.save(filepath)
            saved_paths.append((filepath, f.filename))

    if not saved_paths:
        return jsonify({"error": "Не вдалося зберегти файли."}), 400

    thread = threading.Thread(
        target=_import_files_worker,
        args=(saved_paths,),
        daemon=True
    )
    thread.start()

    return jsonify({"status": "started"})


@app.route("/api/import/progress")
def api_import_progress():
    """Стан поточної фонової задачі."""
    with job_lock:
        return jsonify({
            "type": job_state["type"],
            "running": job_state["running"],
            "total": job_state["total"],
            "processed": job_state["processed"],
            "current_item": job_state["current_item"],
            "errors": job_state["errors"][-50:],
            "total_errors": len(job_state["errors"]),
            "failed_urls": job_state["failed_urls"],
            "total_failed": len(job_state["failed_urls"]),
            "completed_files": job_state["completed_files"],
            "stats": job_state["stats"],
        })


@app.route("/api/import/cancel", methods=["POST"])
def api_import_cancel():
    """Скасувати поточну задачу."""
    with job_lock:
        if job_state["running"]:
            job_state["cancelled"] = True
            return jsonify({"status": "cancelling"})
    return jsonify({"status": "not_running"})


# ============ API: СТОП-ЛИСТ ============

@app.route("/api/stoplist/acceptors")
def api_acceptor_stats():
    """Список акцепторів зі статистикою, з пагінацією і пошуком."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    search = request.args.get("search", "").strip() or None
    sort_by = request.args.get("sort_by", "unique_donors")
    sort_dir = request.args.get("sort_dir", "desc")

    offset = (page - 1) * per_page
    result = queries.get_acceptor_stats(
        limit=per_page, offset=offset,
        search=search, sort_by=sort_by, sort_dir=sort_dir
    )
    result["page"] = page
    result["per_page"] = per_page
    result["total_pages"] = (result["total"] + per_page - 1) // per_page if per_page else 1
    return jsonify(result)


@app.route("/api/stoplist/donors")
def api_donors_for_acceptor():
    """Список донорів для конкретного акцептора."""
    acceptor = request.args.get("acceptor", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 100, type=int)

    if not acceptor:
        return jsonify({"error": "Не вказано акцептор."}), 400

    offset = (page - 1) * per_page
    result = queries.get_donors_for_acceptor(acceptor, limit=per_page, offset=offset)
    result["page"] = page
    result["per_page"] = per_page
    result["total_pages"] = (result["total"] + per_page - 1) // per_page if per_page else 1
    return jsonify(result)


# ============ API: СТАТИСТИКА ============

@app.route("/api/stats/global")
def api_global_stats():
    return jsonify(queries.get_global_stats())


@app.route("/api/stats/tz")
def api_tz_stats():
    rows = queries.get_tz_stats()
    return jsonify([dict(r) for r in rows])


# ============ API: ЕКСПОРТ ============

@app.route("/api/export/start", methods=["POST"])
def api_export_start():
    """Почати експорт стоп-листа в Excel.

    Body (опційно): {"session_ids": ["20260512T153042", "__legacy__"]}
    Якщо session_ids передані — експортуються тільки рядки з цих сесій
    і файли отримують префікс stoplist_selected_part_*.
    """
    if job_state["running"]:
        return jsonify({"error": "Вже виконується інша задача."}), 409

    data = request.get_json(silent=True) or {}
    session_ids = data.get("session_ids") or None
    if session_ids and not isinstance(session_ids, list):
        return jsonify({"error": "session_ids має бути списком."}), 400

    thread = threading.Thread(target=_export_worker, args=(session_ids,), daemon=True)
    thread.start()

    return jsonify({"status": "started", "session_ids": session_ids})


@app.route("/api/export/sessions")
def api_export_sessions():
    """Список імпорт-сесій для UI вибору."""
    return jsonify(queries.get_import_sessions())


@app.route("/api/export/download/<filename>")
def api_export_download(filename):
    """Завантажити файл експорту."""
    return send_from_directory(EXPORT_DIR, filename, as_attachment=True)


# ============ API: БРЕНДИ ============

@app.route("/api/brands/import/urls", methods=["POST"])
def api_brands_import_urls():
    """Імпорт TitleKW з ТЗ за посиланнями."""
    if job_state["running"]:
        return jsonify({"error": "Вже виконується інша задача."}), 409

    data = request.get_json()
    urls = data.get("urls", [])
    is_master = data.get("is_master", False)

    if not urls:
        return jsonify({"error": "Не вказано жодного посилання."}), 400

    thread = threading.Thread(
        target=_import_brands_worker, args=(urls, is_master), daemon=True
    )
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/brands/import/files", methods=["POST"])
def api_brands_import_files():
    """Імпорт TitleKW із завантажених файлів."""
    if job_state["running"]:
        return jsonify({"error": "Вже виконується інша задача."}), 409

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Не вибрано жодного файлу."}), 400

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    saved_paths = []
    for f in files:
        if f.filename:
            filepath = os.path.join(UPLOAD_DIR, f.filename)
            f.save(filepath)
            saved_paths.append((filepath, f.filename))

    thread = threading.Thread(
        target=_import_brands_files_worker, args=(saved_paths,), daemon=True
    )
    thread.start()
    return jsonify({"status": "started"})


@app.route("/api/brands/stats")
def api_brands_stats():
    return jsonify(queries.get_brand_stats())


@app.route("/api/brands/groups")
def api_brands_groups():
    return jsonify(queries.get_brand_groups())


@app.route("/api/brands/merge", methods=["POST"])
def api_brands_merge():
    """Об'єднати дві групи брендів."""
    data = request.get_json()
    target_id = data.get("target_id")
    source_id = data.get("source_id")
    if target_id and source_id:
        queries.merge_brand_groups(target_id, source_id)
    return jsonify({"status": "ok"})


@app.route("/api/brands/export")
def api_brands_export():
    """Експорт брендів в Excel."""
    import xlsxwriter

    filepath = os.path.join(EXPORT_DIR, "brands.xlsx")
    os.makedirs(EXPORT_DIR, exist_ok=True)

    groups = queries.get_brand_groups()

    wb = xlsxwriter.Workbook(filepath)
    ws = wb.add_worksheet("Бренди")

    # Формати
    header_fmt = wb.add_format({'bold': True, 'bg_color': '#2C3E50', 'font_color': 'white', 'font_size': 11})
    brand_fmt = wb.add_format({'bold': True, 'font_size': 11})
    num_fmt = wb.add_format({'font_size': 10})
    var_fmt = wb.add_format({'font_size': 10, 'text_wrap': True, 'font_color': '#666666'})

    ws.set_column(0, 0, 8)   # #
    ws.set_column(1, 1, 35)  # Бренд
    ws.set_column(2, 2, 15)  # Згадувань
    ws.set_column(3, 3, 80)  # Варіації

    # Заголовки
    ws.write(0, 0, "#", header_fmt)
    ws.write(0, 1, "Бренд", header_fmt)
    ws.write(0, 2, "Згадувань", header_fmt)
    ws.write(0, 3, "Варіації назв", header_fmt)

    for i, g in enumerate(groups):
        row = i + 1
        ws.write(row, 0, i + 1, num_fmt)
        ws.write(row, 1, g["brand_name"], brand_fmt)
        ws.write(row, 2, g["total_mentions"], num_fmt)
        ws.write(row, 3, g.get("variations", ""), var_fmt)

    wb.close()

    return send_from_directory(EXPORT_DIR, "brands.xlsx", as_attachment=True)


@app.route("/api/brands/clear", methods=["POST"])
def api_brands_clear():
    if job_state["running"]:
        return jsonify({"error": "Зачекайте завершення поточної задачі."}), 409
    queries.clear_brands()
    return jsonify({"status": "ok"})


# ============ API: УПРАВЛІННЯ ============

@app.route("/api/clear", methods=["POST"])
def api_clear_all():
    """Очистити всі дані стоп-листа."""
    if job_state["running"]:
        return jsonify({"error": "Зачекайте завершення поточної задачі."}), 409
    queries.clear_all()
    return jsonify({"status": "ok"})


@app.route("/api/tz/<int:tz_id>/delete", methods=["POST"])
def api_delete_tz(tz_id):
    """Видалити конкретний ТЗ і його дані."""
    if job_state["running"]:
        return jsonify({"error": "Зачекайте завершення поточної задачі."}), 409
    queries.delete_tz_file(tz_id)
    return jsonify({"status": "ok"})


# ============ ФОНОВІ ВОРКЕРИ ============

def _safe_remove(filepath):
    """Безпечно видалити тимчасовий файл."""
    try:
        if filepath and os.path.exists(filepath):
            os.remove(filepath)
    except OSError:
        pass


def _import_urls_worker(urls, is_master=False):
    """Фоновий воркер для імпорту за URL."""
    reset_job()
    with job_lock:
        job_state["type"] = "import"
        job_state["running"] = True

    import_session_id = datetime.now().strftime("%Y%m%dT%H%M%S")

    try:
        all_urls = []

        if is_master and len(urls) == 1:
            # Завантажуємо майстер-таблицю і витягуємо URLs
            with job_lock:
                job_state["current_item"] = "Завантаження майстер-таблиці..."
            filepath, error = sheets.download_sheet_as_xlsx(urls[0])
            if error:
                with job_lock:
                    job_state["errors"].append(f"Майстер-таблиця: {error}")
                    job_state["running"] = False
                return
            try:
                all_urls = parser.parse_master_sheet_xlsx(filepath)
            finally:
                _safe_remove(filepath)
            if not all_urls:
                with job_lock:
                    job_state["errors"].append("Не знайдено посилань на ТЗ в майстер-таблиці.")
                    job_state["running"] = False
                return
        else:
            all_urls = urls

        with job_lock:
            job_state["total"] = len(all_urls)

        for idx, url in enumerate(all_urls):
            if job_state["cancelled"]:
                break

            url = url.strip()
            if not url:
                continue

            with job_lock:
                job_state["current_item"] = f"[{idx+1}/{len(all_urls)}] {url[:80]}..."

            # Перевіряємо чи вже оброблена успішно
            existing = queries.get_tz_by_url(url)
            if existing and existing["status"] == "done" and existing["total_rows"] > 0:
                with job_lock:
                    job_state["processed"] = idx + 1
                continue
            # Якщо була помилка або 0 рядків — перепробуємо
            if existing:
                queries.delete_tz_file(existing["id"])

            # Завантажуємо як XLSX
            filepath, error = sheets.download_sheet_as_xlsx(url)
            if error:
                with job_lock:
                    job_state["errors"].append(f"{url}: {error}")
                    job_state["failed_urls"].append({
                        "url": url,
                        "reason": error
                    })
                tz_id = queries.insert_tz_file(name=url[:100], source_url=url, import_session_id=import_session_id)
                queries.update_tz_file(tz_id, status="error", error_message=error)
                with job_lock:
                    job_state["processed"] = idx + 1
                time.sleep(SHEETS_DOWNLOAD_DELAY)
                continue

            # Парсимо — шукаємо аркуш "Звіт замовнику"
            try:
                records, full_records, parse_error = parser.parse_report_xlsx(filepath)
                if parse_error:
                    # Немає аркуша "Звіт замовнику" — пропускаємо (не помилка, просто неопублікований)
                    tz_id = queries.insert_tz_file(name=url[:100], source_url=url, import_session_id=import_session_id)
                    queries.update_tz_file(tz_id, status="done", total_rows=0,
                                           unique_acceptors=0, unique_donors=0,
                                           processed_at=datetime.now().isoformat(),
                                           error_message=parse_error)
                    with job_lock:
                        job_state["processed"] = idx + 1
                    _safe_remove(filepath)
                    time.sleep(SHEETS_DOWNLOAD_DELAY)
                    continue
            except Exception as e:
                with job_lock:
                    job_state["errors"].append(f"{url}: Помилка парсингу: {str(e)}")
                tz_id = queries.insert_tz_file(name=url[:100], source_url=url, import_session_id=import_session_id)
                queries.update_tz_file(tz_id, status="error", error_message=str(e))
                with job_lock:
                    job_state["processed"] = idx + 1
                _safe_remove(filepath)
                time.sleep(SHEETS_DOWNLOAD_DELAY)
                continue

            _safe_remove(filepath)

            # Зберігаємо
            _save_records(records, name=url[:100], source_url=url, full_records=full_records,
                          import_session_id=import_session_id)

            with job_lock:
                job_state["processed"] = idx + 1

            # Затримка між запитами
            time.sleep(SHEETS_DOWNLOAD_DELAY)

    except Exception as e:
        with job_lock:
            job_state["errors"].append(f"Критична помилка: {str(e)}")
    finally:
        with job_lock:
            job_state["running"] = False
            job_state["current_item"] = "Завершено" if not job_state["cancelled"] else "Скасовано"
            job_state["stats"] = queries.get_global_stats()


def _import_files_worker(file_list):
    """Фоновий воркер для імпорту файлів."""
    reset_job()
    with job_lock:
        job_state["type"] = "import"
        job_state["running"] = True
        job_state["total"] = len(file_list)

    import_session_id = datetime.now().strftime("%Y%m%dT%H%M%S")

    try:
        for idx, (filepath, filename) in enumerate(file_list):
            if job_state["cancelled"]:
                break

            with job_lock:
                job_state["current_item"] = f"[{idx+1}/{len(file_list)}] {filename}"

            try:
                ext = os.path.splitext(filename)[1].lower()
                if ext == '.csv':
                    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                        content = f.read()
                    records = parser.parse_csv_content(content, filename=filename)
                elif ext in ('.xlsx', '.xls'):
                    records = parser.parse_excel_file(filepath)
                else:
                    with job_lock:
                        job_state["errors"].append(f"{filename}: Непідтримуваний формат ({ext})")
                    with job_lock:
                        job_state["processed"] = idx + 1
                    continue

                _save_records(records, name=filename, import_session_id=import_session_id)

            except Exception as e:
                with job_lock:
                    job_state["errors"].append(f"{filename}: {str(e)}")
                tz_id = queries.insert_tz_file(name=filename, import_session_id=import_session_id)
                queries.update_tz_file(tz_id, status="error", error_message=str(e))

            with job_lock:
                job_state["processed"] = idx + 1

            # Видаляємо тимчасовий файл
            try:
                os.remove(filepath)
            except OSError:
                pass

    except Exception as e:
        with job_lock:
            job_state["errors"].append(f"Критична помилка: {str(e)}")
    finally:
        with job_lock:
            job_state["running"] = False
            job_state["current_item"] = "Завершено" if not job_state["cancelled"] else "Скасовано"
            job_state["stats"] = queries.get_global_stats()


def _save_records(records, name, source_url=None, full_records=None, import_session_id=None):
    """Зберегти записи в БД."""
    if not records and not full_records:
        tz_id = queries.insert_tz_file(name=name, source_url=source_url,
                                       import_session_id=import_session_id)
        queries.update_tz_file(tz_id, status="done", total_rows=0,
                               unique_acceptors=0, unique_donors=0,
                               processed_at=datetime.now().isoformat())
        return

    tz_id = queries.insert_tz_file(name=name, source_url=source_url,
                                   import_session_id=import_session_id)

    # Вставляємо пакетами (raw — для статистики)
    for i in range(0, len(records), BATCH_INSERT_SIZE):
        batch = records[i:i + BATCH_INSERT_SIZE]
        queries.insert_stoplist_batch(batch, tz_id)

    # Вставляємо повні записи (для експорту)
    if full_records:
        for i in range(0, len(full_records), BATCH_INSERT_SIZE):
            batch = full_records[i:i + BATCH_INSERT_SIZE]
            queries.insert_stoplist_full_batch(batch, tz_id)

    # Оновлюємо статистику ТЗ
    unique_acceptors = len(set(r[0] for r in records))
    unique_donors = len(set(r[1] for r in records))

    queries.update_tz_file(
        tz_id,
        status="done",
        total_rows=len(records),
        unique_acceptors=unique_acceptors,
        unique_donors=unique_donors,
        processed_at=datetime.now().isoformat()
    )


def _export_worker(session_ids=None):
    """Фоновий воркер для експорту.

    session_ids: список import_session_id для вибіркового експорту,
        або None для повного.
    """
    reset_job()
    with job_lock:
        job_state["type"] = "export"
        job_state["running"] = True

    def progress_cb(current, total, filename):
        with job_lock:
            job_state["processed"] = current
            job_state["total"] = total
            job_state["current_item"] = filename

    try:
        files = exporter.export_stoplist(progress_callback=progress_cb,
                                         session_ids=session_ids)
        with job_lock:
            job_state["completed_files"] = files
    except Exception as e:
        with job_lock:
            job_state["errors"].append(f"Помилка експорту: {str(e)}")
    finally:
        with job_lock:
            job_state["running"] = False
            job_state["current_item"] = "Завершено"


def _import_brands_worker(urls, is_master=False):
    """Фоновий воркер для імпорту брендів за URL."""
    reset_job()
    with job_lock:
        job_state["type"] = "brands"
        job_state["running"] = True

    try:
        all_urls = []
        if is_master and len(urls) == 1:
            with job_lock:
                job_state["current_item"] = "Завантаження майстер-таблиці..."
            filepath, error = sheets.download_sheet_as_xlsx(urls[0])
            if error:
                with job_lock:
                    job_state["errors"].append(f"Майстер-таблиця: {error}")
                    job_state["running"] = False
                return
            try:
                all_urls = parser.parse_master_sheet_xlsx(filepath)
            finally:
                _safe_remove(filepath)
        else:
            all_urls = urls

        with job_lock:
            job_state["total"] = len(all_urls)

        for idx, url in enumerate(all_urls):
            if job_state["cancelled"]:
                break
            url = url.strip()
            if not url:
                continue

            with job_lock:
                job_state["current_item"] = f"[{idx+1}/{len(all_urls)}] {url[:80]}..."

            if queries.is_brand_tz_processed(url):
                with job_lock:
                    job_state["processed"] = idx + 1
                continue

            filepath, error = sheets.download_sheet_as_xlsx(url)
            if error:
                with job_lock:
                    job_state["errors"].append(f"{url}: {error}")
                    job_state["failed_urls"].append({"url": url, "reason": error})
                    job_state["processed"] = idx + 1
                time.sleep(SHEETS_DOWNLOAD_DELAY)
                continue

            try:
                brand_records = parser.extract_titlekw_from_xlsx(filepath)
                if brand_records:
                    rows = [(orig, norm, url) for orig, norm in brand_records]
                    queries.insert_brand_raw_batch(rows)
                queries.insert_brand_tz(url, url[:100])
            except Exception as e:
                with job_lock:
                    job_state["errors"].append(f"{url}: {str(e)}")
            finally:
                _safe_remove(filepath)

            with job_lock:
                job_state["processed"] = idx + 1
            time.sleep(SHEETS_DOWNLOAD_DELAY)

        # Автогрупування
        with job_lock:
            job_state["current_item"] = "Групування брендів..."
        queries.auto_group_brands()

    except Exception as e:
        with job_lock:
            job_state["errors"].append(f"Критична помилка: {str(e)}")
    finally:
        with job_lock:
            job_state["running"] = False
            job_state["current_item"] = "Завершено" if not job_state["cancelled"] else "Скасовано"
            job_state["stats"] = queries.get_brand_stats()


def _import_brands_files_worker(file_list):
    """Фоновий воркер для імпорту брендів з файлів."""
    reset_job()
    with job_lock:
        job_state["type"] = "brands"
        job_state["running"] = True
        job_state["total"] = len(file_list)

    try:
        for idx, (filepath, filename) in enumerate(file_list):
            if job_state["cancelled"]:
                break
            with job_lock:
                job_state["current_item"] = f"[{idx+1}/{len(file_list)}] {filename}"
            try:
                brand_records = parser.extract_titlekw_from_xlsx(filepath)
                if brand_records:
                    rows = [(orig, norm, filename) for orig, norm in brand_records]
                    queries.insert_brand_raw_batch(rows)
            except Exception as e:
                with job_lock:
                    job_state["errors"].append(f"{filename}: {str(e)}")
            finally:
                _safe_remove(filepath)

            with job_lock:
                job_state["processed"] = idx + 1

        with job_lock:
            job_state["current_item"] = "Групування брендів..."
        queries.auto_group_brands()

    except Exception as e:
        with job_lock:
            job_state["errors"].append(f"Критична помилка: {str(e)}")
    finally:
        with job_lock:
            job_state["running"] = False
            job_state["current_item"] = "Завершено" if not job_state["cancelled"] else "Скасовано"
            job_state["stats"] = queries.get_brand_stats()


# ============ ЗАПУСК ============

if __name__ == "__main__":
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)
    init_db()

    # Відкриваємо браузер через 1.5 секунди
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{PORT}")

    threading.Thread(target=open_browser, daemon=True).start()

    print(f"\n{'='*50}")
    print(f"  Стоп-лист донорів — запущено!")
    print(f"  Відкрийте: http://localhost:{PORT}")
    print(f"{'='*50}\n")

    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
