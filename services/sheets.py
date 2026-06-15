"""Завантаження Google Sheets як XLSX без API ключа."""

import os
import re
import time
import tempfile
import requests

EXPORT_XLSX_URL = "https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
SHEETS_URL_PATTERN = re.compile(r'/spreadsheets/d/([a-zA-Z0-9_-]+)')

# Назви аркуша, який шукаємо (в порядку пріоритету)
REPORT_SHEET_NAMES = [
    "звіт замовнику",
    "звіт замовника",
    "звіт",
    "отчет заказчику",
    "отчет",
    "report",
]


def extract_sheet_id(url):
    """Витягнути ID таблиці з URL Google Sheets."""
    match = SHEETS_URL_PATTERN.search(url)
    if not match:
        return None
    return match.group(1)


def download_sheet_as_xlsx(url, timeout=60, max_retries=3):
    """Завантажити Google Sheet як XLSX файл.

    Повертає (filepath, error_message).
    filepath — шлях до тимчасового .xlsx файлу (потрібно видалити після обробки).
    """
    sheet_id = extract_sheet_id(url)
    if not sheet_id:
        return None, f"Невалідний URL Google Sheets: {url}"

    export_url = EXPORT_XLSX_URL.format(sheet_id=sheet_id)

    for attempt in range(max_retries):
        try:
            response = requests.get(
                export_url,
                timeout=timeout,
                allow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StopListTool/1.0"
                }
            )

            if response.status_code == 200:
                content_type = response.headers.get('content-type', '')

                if 'text/html' in content_type:
                    return None, "Немає доступу. Переконайтесь що доступ 'Усі, хто має посилання' увімкнено."

                # Зберігаємо в тимчасовий файл
                tmp = tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False)
                tmp.write(response.content)
                tmp.close()
                return tmp.name, None

            elif response.status_code == 429:
                wait_time = (attempt + 1) * 5
                time.sleep(wait_time)
                continue

            elif response.status_code in (401, 403):
                return None, "Немає доступу. Переконайтесь що доступ 'Усі, хто має посилання' увімкнено."

            elif response.status_code == 404:
                return None, "Таблицю не знайдено. Перевірте URL."

            else:
                return None, f"Помилка HTTP {response.status_code}"

        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None, "Таймаут при завантаженні. Спробуйте пізніше."

        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            return None, "Помилка з'єднання. Перевірте інтернет."

        except Exception as e:
            return None, f"Помилка: {str(e)}"

    return None, "Не вдалося завантажити після кількох спроб."


def find_report_sheet(workbook):
    """Знайти аркуш 'Звіт замовнику' в робочій книзі.

    Повертає назву аркуша або None.
    """
    sheet_names_lower = {name.lower().strip(): name for name in workbook.sheetnames}

    for target in REPORT_SHEET_NAMES:
        if target in sheet_names_lower:
            return sheet_names_lower[target]

    # Пошук часткового збігу
    for target in REPORT_SHEET_NAMES:
        for lower_name, original_name in sheet_names_lower.items():
            if target in lower_name:
                return original_name

    return None
