"""主界面模块，负责窗口布局、打字判定、预加载和流程切换。"""

import enum
import re
import threading
from concurrent.futures import ThreadPoolExecutor, Future

import customtkinter as ctk

from audio_manager import AudioManager
from progress import save_progress
from translator import DeepLTranslator


class State(enum.Enum):
    """界面当前所处的工作状态。"""

    LOADING = "loading"
    TYPING = "typing"
    SENTENCE_COMPLETE = "sentence_complete"
    BOOK_COMPLETE = "book_complete"


class TypeTypeApp(ctk.CTk):
    """英语打字练习主窗口。"""

    def __init__(
        self,
        sentences,
        book_path,
        start_index,
        translator,
        audio_manager,
        test_mode=False,
    ):
        """初始化窗口、状态和后台预加载器。"""
        super().__init__()

        self.sentences = sentences
        self.book_path = book_path
        self.translator = translator
        self.audio = audio_manager
        self.current_index = start_index
        self.app_state = State.LOADING
        self.test_mode = test_mode

        # Typing state
        self.sentence = ""
        self.cursor_pos = 0
        self.word_boundaries = []  # [(start, end), ...]
        self.current_word_idx = 0
        self.display_words = []  # words split by space (for audio key)

        # Prefetch state: cache for next sentence
        self._prefetch_cache = {}  # index -> {sentence, translation, words}
        self._prefetch_executor = ThreadPoolExecutor(max_workers=2)
        self._prefetch_future = None

        self._setup_ui()
        # Use a hidden Entry to reliably capture keyboard input
        self._key_sink = ctk.CTkEntry(self, width=0, height=0, border_width=0)
        self._key_sink.place(x=-10, y=-10)
        self._key_sink.bind("<Key>", self._on_key_press)
        self._key_sink.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start first sentence
        self.after(100, self._update_wraplength)
        self.after(100, lambda: self._load_sentence(self.current_index))

    # ── UI Setup ──────────────────────────────────────────────────

    def _setup_ui(self):
        """创建主窗口中的标签、按钮和整体布局。"""
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("TypeType")
        self.resizable(True, True)

        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = 1500
        h = 400
        x = 120
        y = 700
        self.geometry(f"{w}x{h}+{x}+{y}")

        # Main container
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(expand=True, fill="both", padx=40, pady=(30, 5))
        container.grid_rowconfigure(0, weight=0)  # translation (fixed height)
        container.grid_rowconfigure(1, weight=0)  # original (fixed height)
        container.grid_rowconfigure(2, weight=0)  # input (fixed height)
        container.grid_rowconfigure(3, weight=1)  # spacer (pushes everything up)
        container.grid_rowconfigure(4, weight=0)  # status
        container.grid_columnconfigure(0, weight=1)

        # Translation label (top)
        self.lbl_translation = ctk.CTkLabel(
            container,
            text="",
            font=("Microsoft YaHei", 24),
            text_color="#555555",
            justify="left",
            anchor="w",
            padx=0,
            pady=0,
        )
        self.lbl_translation.grid(row=0, column=0, sticky="sew", pady=(0, 8))

        # Original sentence (middle)
        self.lbl_original = ctk.CTkLabel(
            container,
            text="",
            font=("Consolas", 26),
            text_color="#FFFFFF",
            justify="left",
            anchor="w",
            padx=0,
            pady=0,
        )
        self.lbl_original.grid(row=1, column=0, sticky="sew", pady=(0, 0))

        # User input (bottom)
        self.lbl_input = ctk.CTkLabel(
            container,
            text="",
            font=("Consolas", 26),
            text_color="#4CAF50",
            justify="left",
            anchor="w",
            padx=0,
            pady=0,
        )
        self.lbl_input.grid(row=2, column=0, sticky="new", pady=(15, 0))

        # Dynamic wraplength: bind to window resize
        self._container = container
        self.bind("<Configure>", self._on_window_resize)

        # Status bar
        status_frame = ctk.CTkFrame(container, fg_color="transparent")
        status_frame.grid(row=4, column=0, sticky="ew", pady=(20, 0))

        self.lbl_progress = ctk.CTkLabel(
            status_frame, text="", font=("Microsoft YaHei", 14), text_color="#666666"
        )
        self.lbl_progress.pack(side="right")

        # Hint label: centered at bottom, hidden until sentence audio finishes
        self.lbl_hint = ctk.CTkLabel(
            container,
            text="",
            font=("Microsoft YaHei", 24),
            text_color="#4CAF50",
            anchor="center",
        )
        self.lbl_hint.grid(row=3, column=0, sticky="s", pady=(0, 5))

        # Completion overlay (hidden by default)
        self.completion_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.lbl_complete = ctk.CTkLabel(
            self.completion_frame,
            text="🎉 恭喜完成全书！",
            font=("Microsoft YaHei", 32),
            text_color="#4CAF50",
        )
        self.lbl_complete.pack(pady=(60, 30))

        self.btn_restart = ctk.CTkButton(
            self.completion_frame,
            text="重新开始",
            font=("Microsoft YaHei", 18),
            width=200,
            fg_color="#3c3c3c",
            hover_color="#505050",
            command=self._restart_book,
        )
        self.btn_restart.pack(pady=10)

        self.btn_new_book = ctk.CTkButton(
            self.completion_frame,
            text="打开新书",
            font=("Microsoft YaHei", 18),
            width=200,
            fg_color="#3c3c3c",
            hover_color="#505050",
            command=self._open_new_book,
        )
        self.btn_new_book.pack(pady=10)

        # Error flash state
        self._flash_after_id = None
        self._original_fg = None

    # ── Sentence loading ──────────────────────────────────────────

    def _load_sentence(self, index):
        """加载指定序号的句子，并准备翻译和音频资源。"""
        if index >= len(self.sentences):
            self._show_completion()
            return

        self.app_state = State.LOADING
        self.lbl_original.configure(
            text="加载中...", text_color="#4A9EFF", anchor="center"
        )
        self.lbl_translation.configure(text="")
        self.lbl_input.configure(text="")
        self.lbl_hint.configure(text="")
        self._update_progress(index)

        # Check if prefetch cache has this sentence ready
        if index in self._prefetch_cache:
            cached = self._prefetch_cache.pop(index)

            # Audio still needs to be prepared (can't prefetch pygame Sounds across calls)
            def _bg_audio():
                self.audio.prepare_sentence(cached["sentence"], cached["words"])
                self.after(
                    0,
                    self._display_sentence,
                    cached["sentence"],
                    cached["translation"],
                    cached["words"],
                )

            threading.Thread(target=_bg_audio, daemon=True).start()
            return

        def _bg():
            """在后台线程中并行生成翻译和当前句音频。"""
            sentence = self.sentences[index]
            words = sentence.split()
            # Run translation and audio generation in parallel
            translate_future = self._prefetch_executor.submit(
                self.translator.translate, sentence
            )
            audio_future = self._prefetch_executor.submit(
                self.audio.prepare_sentence, sentence, words
            )
            translation = translate_future.result()
            audio_future.result()
            self.after(0, self._display_sentence, sentence, translation, words)

        threading.Thread(target=_bg, daemon=True).start()

    def _display_sentence(self, sentence, translation, words):
        """将当前句子的文本、翻译和输入状态显示到界面上。"""
        self.sentence = sentence
        self.cursor_pos = 0
        self.display_words = words
        self.word_boundaries = self._compute_word_boundaries(sentence)
        self.current_word_idx = 0
        self.app_state = State.TYPING

        self.lbl_translation.configure(text=translation)
        self.lbl_original.configure(text=sentence, text_color="#FFFFFF", anchor="w")
        self.lbl_input.configure(text="▏")
        self.lbl_hint.configure(text="")

        # Ensure keyboard focus on hidden input sink
        self._key_sink.focus_set()

        # Start playing the first word
        if words:
            self.audio.play_word(words[0])

        # Prefetch the next sentence's translation in background
        self._start_prefetch(self.current_index + 1)

    # ── Prefetch ──────────────────────────────────────────────────

    def _start_prefetch(self, index):
        """在用户输入当前句时预加载下一句的翻译和音频文件。"""
        if index >= len(self.sentences):
            return
        if index in self._prefetch_cache:
            return

        def _prefetch():
            """后台准备下一句的翻译结果和音频缓存。"""
            sentence = self.sentences[index]
            words = sentence.split()
            # Run translation and audio file generation in parallel
            translate_future = self._prefetch_executor.submit(
                self.translator.translate, sentence
            )
            audio_future = self._prefetch_executor.submit(
                self.audio.pregenerate_files, sentence, words
            )
            translation = translate_future.result()
            audio_future.result()
            self._prefetch_cache[index] = {
                "sentence": sentence,
                "translation": translation,
                "words": words,
            }

        self._prefetch_future = self._prefetch_executor.submit(_prefetch)

    # ── Word boundary computation ─────────────────────────────────

    @staticmethod
    def _compute_word_boundaries(sentence):
        """计算每个单词片段在整句中的起止范围。"""
        boundaries = []
        i = 0
        n = len(sentence)
        while i < n:
            # Start of a word-segment
            start = i
            # Advance past non-space chars
            while i < n and sentence[i] != " ":
                i += 1
            # Include trailing spaces (they belong to this word-segment)
            while i < n and sentence[i] == " ":
                i += 1
            # But if this is the last word, don't include trailing space
            # Actually: include spaces as part of the segment so user
            # must type them before moving to next word
            boundaries.append((start, i))
        return boundaries

    @staticmethod
    def _normalize_char(ch):
        """将常见排版字符归一化，避免智能标点导致误判。"""
        mapping = {
            "’": "'",
            "‘": "'",
            "“": '"',
            "”": '"',
            "–": "-",
            "—": "-",
        }
        return mapping.get(ch, ch)

    # ── Keyboard handling ─────────────────────────────────────────

    def _on_key_press(self, event):
        """处理键盘输入，并推进或回退当前打字进度。"""
        # Clear the hidden entry to prevent text buildup
        self.after(1, lambda: self._key_sink.delete(0, "end"))
        if self.app_state == State.LOADING or self.app_state == State.BOOK_COMPLETE:
            return "break"

        if self.app_state == State.SENTENCE_COMPLETE:
            if event.keysym == "Return" and self.audio.has_sentence_played_once():
                self.audio.stop()
                self.current_index += 1
                save_progress(self.book_path, self.current_index)
                self._load_sentence(self.current_index)
            return "break"

        # TYPING state
        ch = event.char
        if not ch or len(ch) != 1:
            return "break"

        # Ignore control chars, keep printable Unicode for punctuation compatibility
        if ord(ch) < 32:
            return "break"

        expected = self._normalize_char(self.sentence[self.cursor_pos])
        typed = self._normalize_char(ch)

        # 测试模式：按 't' 视为正确，其他键视为错误
        if self.test_mode:
            correct = typed == "t"
        else:
            correct = typed == expected

        if correct:
            self.cursor_pos += 1
            self._update_input_display()

            # Check if we moved to a new word segment
            new_word_idx = self._get_word_index(self.cursor_pos)
            if new_word_idx != self.current_word_idx and new_word_idx < len(
                self.display_words
            ):
                self.current_word_idx = new_word_idx
                self.audio.transition_to_word(self.display_words[new_word_idx])

            # Check if sentence is complete
            if self.cursor_pos >= len(self.sentence):
                self.app_state = State.SENTENCE_COMPLETE
                self.audio.play_sentence()
                self._poll_sentence_played()
        else:
            # Wrong character: reset to start of current word
            if self.word_boundaries:
                start, end = self.word_boundaries[self.current_word_idx]
                self.cursor_pos = start
                self._update_input_display()
            self._flash_error()

        return "break"

    def _get_word_index(self, pos):
        """根据字符位置返回所在的单词片段索引。"""
        for i, (start, end) in enumerate(self.word_boundaries):
            if pos < end:
                return i
        return len(self.word_boundaries) - 1

    def _flash_error(self):
        """打错时短暂闪红，提示用户输入错误。"""
        if self._flash_after_id is not None:
            self.after_cancel(self._flash_after_id)
        if self._original_fg is None:
            # Save the actual background color on first flash
            self._original_fg = self.cget("fg_color")
        self.configure(fg_color="#3a0000")
        self._flash_after_id = self.after(150, self._clear_flash)

    def _clear_flash(self):
        """恢复窗口原本的背景色。"""
        self.configure(fg_color=self._original_fg)
        self._flash_after_id = None

    def _poll_sentence_played(self):
        """轮询整句音频是否至少播放一遍，随后显示回车提示。"""
        if self.app_state != State.SENTENCE_COMPLETE:
            return
        if self.audio.has_sentence_played_once():
            self.lbl_hint.configure(text="按回车键继续")
        else:
            self.after(200, self._poll_sentence_played)

    def _on_window_resize(self, event):
        """窗口尺寸变化后，重新计算文本换行宽度。"""
        if event.widget is not self:
            return
        # Schedule after layout so winfo_width is accurate
        self.after(5, self._update_wraplength)

    def _update_wraplength(self):
        """直接设置底层 tkinter Label 的换行宽度。"""
        w = self.lbl_original.winfo_width() - 4
        if w > 100:
            # Access the internal tkinter Label to avoid CTk's DPI scaling
            self.lbl_translation._label.configure(wraplength=w)
            self.lbl_original._label.configure(wraplength=w)
            self.lbl_input._label.configure(wraplength=w)

    def _update_input_display(self):
        """刷新输入行，显示已输入部分与光标位置。"""
        typed = self.sentence[: self.cursor_pos]
        remaining_len = len(self.sentence) - self.cursor_pos
        if remaining_len > 0:
            # Pad with spaces to keep same width as original sentence
            self.lbl_input.configure(text=typed + "\u258f" + " " * (remaining_len - 1))
        else:
            self.lbl_input.configure(text=typed)

    def _update_progress(self, index):
        """更新右下角的句子进度显示。"""
        total = len(self.sentences)
        self.lbl_progress.configure(text=f"第 {index + 1} / {total} 句")

    # ── Completion ────────────────────────────────────────────────

    def _show_completion(self):
        """展示整本书完成后的收尾界面。"""
        self.app_state = State.BOOK_COMPLETE
        self.audio.stop()
        self.lbl_translation.configure(text="")
        self.lbl_original.configure(text="")
        self.lbl_input.configure(text="")
        self.lbl_hint.configure(text="")
        self.lbl_progress.configure(text="")
        self.completion_frame.place(
            relx=0.5, rely=0.5, anchor="center", relwidth=0.6, relheight=0.6
        )

    def _restart_book(self):
        """从头重新开始当前这本书。"""
        self.completion_frame.place_forget()
        self.current_index = 0
        save_progress(self.book_path, 0)
        self._load_sentence(0)

    def _open_new_book(self):
        """选择一本新书，并清空旧书相关缓存后重新载入。"""
        from tkinter import filedialog
        from main import clear_all_cache

        path = filedialog.askopenfilename(
            title="选择英文书籍", filetypes=[("Text files", "*.txt")]
        )
        if not path:
            return
        from text_processor import load_book, split_sentences

        text = load_book(path)
        sentences = split_sentences(text)
        if not sentences:
            return
        clear_all_cache()
        self.completion_frame.place_forget()
        self.sentences = sentences
        self.book_path = path
        self.current_index = 0
        self._load_sentence(0)

    # ── Cleanup ───────────────────────────────────────────────────

    def _on_close(self):
        """关闭窗口前保存必要进度并释放音频资源。"""
        if self.app_state == State.TYPING:
            save_progress(self.book_path, self.current_index)
        self.audio.cleanup()
        self.destroy()
