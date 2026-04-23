"""进度模块，负责保存、读取和清除当前书籍的练习进度。"""

import hashlib
import json
import os
import sys


def _app_dir():
    """返回应用运行目录，兼容源码运行和打包运行。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


PROGRESS_DIR = os.path.join(_app_dir(), "data")
PROGRESS_PATH = os.path.join(PROGRESS_DIR, "progress.json")


def _file_hash(filepath):
    """计算书籍文件内容的 SHA256，用于校验进度是否仍然有效。"""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def load_progress(book_path):
    """读取指定书籍的已保存进度，不匹配则返回 0。"""
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
    """保存当前书籍路径、句子序号和文件校验信息。"""
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    data = {
        "book_path": os.path.abspath(book_path),
        "sentence_index": sentence_index,
        "book_hash": _file_hash(book_path),
    }
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_saved_book_path():
    """获取上次保存进度对应的书籍路径。"""
    if not os.path.exists(PROGRESS_PATH):
        return None
    with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    path = data.get("book_path")
    if path and os.path.exists(path):
        return path
    return None


def clear_progress():
    """删除本地进度文件。"""
    if os.path.exists(PROGRESS_PATH):
        os.remove(PROGRESS_PATH)
