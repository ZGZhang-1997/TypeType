import configparser
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

from app import TypeTypeApp
from audio_manager import AudioManager
from progress import get_saved_book_path, load_progress, clear_progress
from text_processor import load_book, split_sentences, ensure_nltk_data
from translator import DeepLTranslator


CONFIG_PATH = "config.ini"

# 测试模式开关：默认：False
# 设为 True 时，按 't' 视为输入正确，按其他键视为输入错误
TEST_MODE = True


def ensure_config():
    if not os.path.exists(CONFIG_PATH):
        cfg = configparser.ConfigParser()
        cfg["deepl"] = {"api_key_file": r"C:\path\to\deepl_key.txt"}
        cfg["audio"] = {"voice": "en-US-AriaNeural"}
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def get_api_key(cfg):
    key_file = cfg.get("deepl", "api_key_file", fallback="")
    if not key_file or key_file == r"C:\path\to\deepl_key.txt":
        messagebox.showwarning(
            "配置缺失",
            f"请在 {os.path.abspath(CONFIG_PATH)} 中设置 api_key_file 为存放 DeepL API Key 的文件路径，\n"
            "然后重新启动程序。\n\n"
            "免费注册: https://www.deepl.com/pro#developer",
        )
        sys.exit(0)
    if not os.path.exists(key_file):
        messagebox.showwarning(
            "文件不存在",
            f"API Key 文件不存在：\n{key_file}\n\n"
            "请创建该文件并写入 DeepL API Key（仅一行）。",
        )
        sys.exit(0)
    key = open(key_file, encoding="utf-8").read().strip()
    if not key:
        messagebox.showwarning(
            "Key 为空",
            f"API Key 文件为空：\n{key_file}\n\n" "请在文件中写入 DeepL API Key。",
        )
        sys.exit(0)
    return key


def clear_all_cache():
    """清除所有缓存：进度、翻译缓存、音频缓存"""
    import shutil

    clear_progress()
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    for name in ("translation_cache.json", "audio_cache"):
        p = os.path.join(cache_dir, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.isfile(p):
            os.remove(p)


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
        root.title("是否继续上次进度")
        root.resizable(False, False)
        root.configure(bg="#2b2b2b")

        result = {"value": None}

        tk.Label(
            root,
            text=f"检测到上次打字存档：\n{os.path.basename(saved_book)}",
            justify="left",
            padx=20,
            pady=15,
            bg="#2b2b2b",
            fg="#ffffff",
            font=("Microsoft YaHei", 11),
        ).pack()

        btn_frame = tk.Frame(root, bg="#2b2b2b")
        btn_frame.pack(pady=(0, 15))

        btn_style = {
            "bg": "#3c3c3c",
            "fg": "#ffffff",
            "activebackground": "#505050",
            "activeforeground": "#ffffff",
            "relief": "flat",
            "font": ("Microsoft YaHei", 10),
        }

        def on_continue():
            result["value"] = True
            root.destroy()

        def on_new():
            result["value"] = False
            root.destroy()

        def on_cancel():
            root.destroy()

        tk.Button(
            btn_frame, text="继续上次选择", width=14, command=on_continue, **btn_style
        ).pack(side="left", padx=5)
        tk.Button(
            btn_frame, text="选择新书", width=14, command=on_new, **btn_style
        ).pack(side="left", padx=5)
        tk.Button(btn_frame, text="退出", width=8, command=on_cancel, **btn_style).pack(
            side="left", padx=5
        )

        root.protocol("WM_DELETE_WINDOW", on_cancel)
        root.eval("tk::PlaceWindow . center")
        root.mainloop()

        answer = result["value"]

        if answer is None:
            sys.exit(0)
        elif answer:
            book_path = saved_book
        else:
            book_path = choose_book()
            clear_all_cache()
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
        test_mode=TEST_MODE,
    )
    app.mainloop()


if __name__ == "__main__":
    main()
