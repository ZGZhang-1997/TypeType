import hashlib
import json
import os


PROGRESS_DIR = "data"
PROGRESS_PATH = os.path.join(PROGRESS_DIR, "progress.json")


def _file_hash(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_progress(book_path):
    if not os.path.exists(PROGRESS_PATH):
        return 0
    with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    abs_path = os.path.abspath(book_path)
    if data.get("book_path") != abs_path:
        return 0
    if data.get("book_hash") != _file_hash(book_path):
        return 0
    return data.get("sentence_index", 0)


def save_progress(book_path, sentence_index):
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    data = {
        "book_path": os.path.abspath(book_path),
        "sentence_index": sentence_index,
        "book_hash": _file_hash(book_path),
    }
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_saved_book_path():
    if not os.path.exists(PROGRESS_PATH):
        return None
    with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    path = data.get("book_path")
    if path and os.path.exists(path):
        return path
    return None


def clear_progress():
    if os.path.exists(PROGRESS_PATH):
        os.remove(PROGRESS_PATH)
