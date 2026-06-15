import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "stoplist.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
MAX_EXCEL_ROWS = 1_000_000
SHEETS_DOWNLOAD_DELAY = 1.5  # секунд між запитами до Google
BATCH_INSERT_SIZE = 500
PORT = 5555
