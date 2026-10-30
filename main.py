"""程序入口模块，负责配置读取、选书流程和主窗口启动。"""

import configparser
import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox

# PyInstaller 单文件模式下，获取 exe 所在目录
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

import customtkinter as ctk

from app import TypeTypeApp, apply_dark_titlebar
from audio_manager import AudioManager
from progress import get_saved_book_path, load_progress, clear_progress
from text_processor import load_book, split_sentences, ensure_nltk_data
from translator import DeepLTranslator


CONFIG_PATH = os.path.join(APP_DIR, "config.ini")

# 复用主窗口的配色与字体，保证启动弹窗风格一致
Theme = TypeTypeApp

# 测试模式开关：默认：False
# 设为 True 时，按 't' 视为输入正确，按其他键视为输入错误
TEST_MODE = False


def ensure_config():
    """确保配置文件存在，并返回已加载的配置对象。"""
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
    """从配置指定的外部文件中读取 DeepL API Key。"""
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
    """清除所有缓存：进度、翻译缓存和音频缓存。"""
    import shutil

    clear_progress()
    cache_dir = os.path.join(APP_DIR, "data")
    for name in ("translation_cache.json", "audio_cache"):
        p = os.path.join(cache_dir, name)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
        elif os.path.isfile(p):
            os.remove(p)


def choose_book():
    """弹出文件选择框，返回用户选中的 txt 文件路径。"""
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title="选择英文书籍 (.txt)", filetypes=[("Text files", "*.txt")]
    )
    root.destroy()
    if not path:
        sys.exit(0)
    return path


def ask_resume(saved_book):
    """询问用户：继续上次的书、重新选书，还是退出。"""
    root = ctk.CTk()
    root.title("TypeType")
    root.resizable(False, False)
    root.configure(fg_color=Theme.BG)

    win_w, win_h = 460, 226
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    root.geometry(f"{win_w}x{win_h}+{(screen_w - win_w) // 2}+{(screen_h - win_h) // 2}")

    ctk.CTkLabel(
        root,
        text="继续上次的进度？",
        font=(Theme.FONT_UI, 18, "bold"),
        text_color=Theme.FG,
    ).pack(pady=(36, 6))

    ctk.CTkLabel(
        root,
        text=os.path.basename(saved_book),
        font=(Theme.FONT_UI, 12),
        text_color=Theme.MUTED,
    ).pack()

    result = {"value": None}

    def choose(value):
        result["value"] = value
        root.destroy()

    row = ctk.CTkFrame(root, fg_color="transparent")
    row.pack(pady=(28, 0))

    ctk.CTkButton(
        row,
        text="继续",
        width=104,
        height=36,
        corner_radius=10,
        font=(Theme.FONT_UI, 13),
        fg_color=Theme.ACCENT,
        hover_color="#6188d4",
        text_color=Theme.BG,
        command=lambda: choose(True),
    ).pack(side="left", padx=5)

    ctk.CTkButton(
        row,
        text="选择新书",
        width=104,
        height=36,
        corner_radius=10,
        font=(Theme.FONT_UI, 13),
        fg_color="transparent",
        hover_color=Theme.BORDER,
        border_width=1,
        border_color=Theme.BORDER,
        text_color=Theme.FG,
        command=lambda: choose(False),
    ).pack(side="left", padx=5)

    ctk.CTkButton(
        row,
        text="退出",
        width=80,
        height=36,
        corner_radius=10,
        font=(Theme.FONT_UI, 13),
        fg_color="transparent",
        hover_color=Theme.BORDER,
        border_width=1,
        border_color=Theme.BORDER,
        text_color=Theme.MUTED,
        command=lambda: choose(None),
    ).pack(side="left", padx=5)

    root.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    # 等窗口真正映射后再设置标题栏颜色，否则 DWM 会忽略
    root.after(80, lambda: apply_dark_titlebar(root))
    root.mainloop()
    return result["value"]


def main():
    """初始化运行环境，选择书籍，并启动主界面。"""
    # Ensure nltk data is ready
    ensure_nltk_data()

    # Load config
    cfg = ensure_config()
    api_key = get_api_key(cfg)
    voice = cfg.get("audio", "voice", fallback="en-US-AriaNeural")

    # Determine which book to open
    saved_book = get_saved_book_path()

    if saved_book:
        answer = ask_resume(saved_book)

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
