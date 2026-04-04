import configparser
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

from app import TypeTypeApp
from audio_manager import AudioManager
from progress import get_saved_book_path, load_progress
from text_processor import load_book, split_sentences, ensure_nltk_data
from translator import DeepLTranslator


CONFIG_PATH = "config.ini"


def ensure_config():
    if not os.path.exists(CONFIG_PATH):
        cfg = configparser.ConfigParser()
        cfg["deepl"] = {"api_key": "YOUR_KEY_HERE"}
        cfg["audio"] = {"voice": "en-US-AriaNeural"}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def get_api_key(cfg):
    key = cfg.get("deepl", "api_key", fallback="YOUR_KEY_HERE")
    if not key or key == "YOUR_KEY_HERE":
        messagebox.showwarning(
            "配置缺失",
            f"请在 {os.path.abspath(CONFIG_PATH)} 中填入 DeepL API Key，\n"
            "然后重新启动程序。\n\n"
            "免费注册: https://www.deepl.com/pro#developer",
        )
        sys.exit(0)
    return key


def choose_book():
    """Show file dialog to choose a txt file. Returns path or exits."""
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="选择英文书籍 (.txt)", filetypes=[("Text files", "*.txt")]
    )
    root.destroy()
    if not path:
        sys.exit(0)
    return path


def main():
    # Ensure nltk data is ready
    ensure_nltk_data()

    # Load config
    cfg = ensure_config()
    api_key = get_api_key(cfg)
    voice = cfg.get("audio", "voice", fallback="en-US-AriaNeural")

    # Determine which book to open
    saved_book = get_saved_book_path()

    if saved_book:
        # Ask user: continue or new book?
        root = tk.Tk()
        root.withdraw()
        answer = messagebox.askyesnocancel(
            "继续上次进度",
            f"检测到上次打字存档：\n{os.path.basename(saved_book)}\n\n"
            "是 = 继续上次进度\n"
            "否 = 选择新书\n"
            "取消 = 退出",
        )
        root.destroy()

        if answer is None:
            sys.exit(0)
        elif answer:
            book_path = saved_book
        else:
            book_path = choose_book()
    else:
        book_path = choose_book()

    # Load and split book
    text = load_book(book_path)
    sentences = split_sentences(text)
    if not sentences:
        messagebox.showerror("错误", "文件中没有找到英文句子。")
        sys.exit(1)

    # Determine start index
    start_index = load_progress(book_path)
    if start_index >= len(sentences):
        start_index = 0

    # Create components
    translator = DeepLTranslator(api_key)
    audio = AudioManager(voice=voice)

    # Launch app
    app = TypeTypeApp(
        sentences=sentences,
        book_path=book_path,
        start_index=start_index,
        translator=translator,
        audio_manager=audio,
    )
    app.mainloop()


if __name__ == "__main__":
    main()
