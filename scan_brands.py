"""Окремий скрипт для сканування брендів (TitleKW).
Працює паралельно з основним сервером стоп-листа.

Використання:
  1. Створіть файл brand_urls.txt з посиланнями на ТЗ (по одному на рядок)
  2. Запустіть: python scan_brands.py
  Або: python scan_brands.py urls.txt
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SHEETS_DOWNLOAD_DELAY
from db.schema import init_db
from db.queries import (
    insert_brand_raw_batch, insert_brand_tz, is_brand_tz_processed,
    auto_group_brands, get_brand_stats, get_brand_groups
)
from services.sheets import download_sheet_as_xlsx
from services.parser import extract_titlekw_from_xlsx, parse_master_sheet_xlsx


def main():
    init_db()

    # Визначаємо файл з URL
    urls_file = sys.argv[1] if len(sys.argv) > 1 else "brand_urls.txt"

    if not os.path.exists(urls_file):
        print(f"Файл '{urls_file}' не знайдено!")
        print(f"Створіть файл '{urls_file}' з посиланнями на Google Sheets (по одному на рядок)")
        print("Або вкажіть файл: python scan_brands.py my_urls.txt")

        # Пропонуємо ввести вручну
        print("\nАбо вставте посилання зараз (порожній рядок = кінець):")
        urls = []
        while True:
            line = input().strip()
            if not line:
                break
            if 'docs.google.com/spreadsheets' in line:
                urls.append(line)
        if not urls:
            print("Немає посилань. Вихід.")
            return
    else:
        with open(urls_file, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]

    # Перевіряємо чи перше посилання — майстер-таблиця
    if len(urls) == 1 and 'docs.google.com/spreadsheets' in urls[0]:
        print(f"Одне посилання. Перевіряю чи це майстер-таблиця...")
        filepath, error = download_sheet_as_xlsx(urls[0])
        if error:
            print(f"Помилка: {error}")
            return
        master_urls = parse_master_sheet_xlsx(filepath)
        if len(master_urls) > 1:
            print(f"Це майстер-таблиця! Знайдено {len(master_urls)} посилань на ТЗ.")
            urls = master_urls
        else:
            # Це звичайне ТЗ
            pass
        try:
            os.remove(filepath)
        except OSError:
            pass

    # Фільтруємо тільки Google Sheets URLs
    urls = [u for u in urls if 'docs.google.com/spreadsheets' in u]
    total = len(urls)
    print(f"\nВсього URL для обробки: {total}")
    print(f"Затримка між запитами: {SHEETS_DOWNLOAD_DELAY} сек")
    print(f"Орієнтовний час: ~{total * SHEETS_DOWNLOAD_DELAY / 60:.0f} хвилин")
    print("=" * 60)

    processed = 0
    skipped = 0
    errors = 0
    brands_found = 0

    for idx, url in enumerate(urls):
        url = url.strip()
        if not url:
            continue

        # Перевіряємо чи вже оброблена
        if is_brand_tz_processed(url):
            skipped += 1
            processed += 1
            if skipped % 100 == 0:
                print(f"  [{processed}/{total}] Пропущено {skipped} вже оброблених...")
            continue

        print(f"  [{processed + 1}/{total}] {url[:80]}...", end=" ", flush=True)

        # Завантажуємо
        filepath, error = download_sheet_as_xlsx(url)
        if error:
            print(f"ПОМИЛКА: {error}")
            errors += 1
            processed += 1
            time.sleep(SHEETS_DOWNLOAD_DELAY)
            continue

        # Парсимо TitleKW
        try:
            brand_records = extract_titlekw_from_xlsx(filepath)
            if brand_records:
                rows = [(orig, norm, url) for orig, norm in brand_records]
                insert_brand_raw_batch(rows)
                brands_found += len(brand_records)
                print(f"OK ({len(brand_records)} записів)")
            else:
                print("(немає TitleKW)")
            insert_brand_tz(url, url[:100])
        except Exception as e:
            print(f"ПОМИЛКА парсингу: {e}")
            errors += 1
        finally:
            try:
                os.remove(filepath)
            except OSError:
                pass

        processed += 1
        time.sleep(SHEETS_DOWNLOAD_DELAY)

    # Автогрупування
    print("\nГрупування брендів...")
    auto_group_brands()

    # Результати
    stats = get_brand_stats()
    groups = get_brand_groups()

    print("\n" + "=" * 60)
    print("РЕЗУЛЬТАТИ:")
    print(f"  Оброблено ТЗ: {processed}")
    print(f"  Пропущено (вже оброблені): {skipped}")
    print(f"  Помилок: {errors}")
    print(f"  Знайдено записів TitleKW: {brands_found}")
    print(f"  Унікальних брендів: {stats['total_groups']}")
    print(f"  Варіацій назв: {stats['total_unique_normalized']}")
    print()

    if groups:
        print("ТОП-30 БРЕНДІВ:")
        print(f"{'#':>3}  {'Бренд':<30} {'Згадувань':>10}  Варіації")
        print("-" * 80)
        for i, g in enumerate(groups[:30]):
            print(f"{i+1:>3}  {g['brand_name']:<30} {g['total_mentions']:>10}  {g['variations'][:50] if g['variations'] else ''}")

    print("\nГотово! Результати збережено в базі.")
    print("Відкрийте http://localhost:5555/brands щоб переглянути у веб-інтерфейсі.")


if __name__ == "__main__":
    main()
