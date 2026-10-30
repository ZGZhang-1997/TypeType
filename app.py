"""主界面模块，负责窗口布局、打字判定、预加载和流程切换。"""

import enum
import os
import threading
import tkinter as tk
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from tkinter import font as tkfont

import customtkinter as ctk

from progress import save_progress


def apply_dark_titlebar(window):
    """让 Windows 标题栏跟随深色主题，失败时静默忽略。"""
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE 及其旧编号
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
            )
            if result == 0:
                break
    except Exception:
        pass


class State(enum.Enum):
    """界面当前所处的工作状态。"""

    LOADING = "loading"
    TYPING = "typing"
    SENTENCE_COMPLETE = "sentence_complete"
    BOOK_COMPLETE = "book_complete"


class TypeTypeApp(ctk.CTk):
    """英语打字练习主窗口。"""

    # ── 视觉主题（Tokyo Night 配色）──────────────────────────────
    BG = "#16161e"  # 窗口底色
    SURFACE = "#1a1b26"  # 卡片底色
    BORDER = "#262b40"  # 分隔线与描边
    FG = "#c0caf5"  # 原文
    TRANSLATION = "#6b7394"  # 译文
    MUTED = "#565f89"  # 次要信息
    ACCENT = "#7aa2f7"  # 当前词 / 进度
    SUCCESS = "#9ece6a"  # 已输入
    GHOST = "#2f3550"  # 尚未输入的文字
    FLASH_BG = "#2a1a24"  # 打错时的背景闪色
    FONT_UI = "Microsoft YaHei UI"
    FONT_MONO = "Cascadia Mono"

    # 不需要输入的字符：引号只是排版包裹。空格仍需输入。
    # 注意不含 ’（U+2019），本书中它 2095 次全部用作缩写符（couldn’t / They’d）。
    SKIP_CHARS = "“”\"‘"

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

        # 字体回退：优先 Cascadia Mono，缺失时退回 Consolas
        available = set(tkfont.families())
        for name in ("Cascadia Mono", "Consolas", "Courier New"):
            if name in available:
                self.FONT_MONO = name
                break

        self.sentences = sentences
        self.book_path = book_path
        self.translator = translator
        self.audio = audio_manager
        self.current_index = start_index
        self.app_state = State.LOADING
        self.test_mode = test_mode

        # Typing state
        self.sentence = ""  # 原文（用于显示，可能含 …）
        self.compare_sentence = ""  # … 展开为 ...（用于打字判定）
        self.cursor_pos = 0
        self.word_boundaries = []  # [(start, end), ...]
        self.current_word_idx = 0
        self.display_words = []  # words split by space (for audio key)
        self._cmp_to_disp = []  # compare_sentence 下标 -> 原文显示下标

        # Prefetch state: cache for next sentence
        self._prefetch_cache = {}  # index -> {sentence, translation, words}
        self._prefetch_executor = ThreadPoolExecutor(max_workers=2)

        self._setup_ui()
        # Use a hidden Entry to reliably capture keyboard input
        self._key_sink = ctk.CTkEntry(
            self, width=1, height=1, border_width=0, fg_color=self.BG, text_color=self.BG
        )
        self._key_sink.place(x=-60, y=-60)
        self._key_sink.bind("<Key>", self._on_key_press)
        self._key_sink.focus_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start first sentence
        self.after(100, self._refit_texts)
        self.after(100, lambda: self._load_sentence(self.current_index))

    # ── UI Setup ──────────────────────────────────────────────────

    def _setup_ui(self):
        """创建主窗口中的标签、按钮和整体布局。"""
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("TypeType")
        self.configure(fg_color=self.BG)
        self.resizable(True, True)

        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width, height = 1180, 680
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 2 - 30)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.minsize(900, 560)

        root = ctk.CTkFrame(self, fg_color="transparent")
        root.pack(fill="both", expand=True, padx=56, pady=(34, 30))
        root.grid_columnconfigure(0, weight=1)
        root.grid_rowconfigure(2, weight=1)

        # ── 顶栏：品牌与进度计数 ──
        header = ctk.CTkFrame(root, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            header,
            text="TypeType",
            font=(self.FONT_UI, 15, "bold"),
            text_color=self.ACCENT,
        ).grid(row=0, column=0, sticky="w")

        self.lbl_progress = ctk.CTkLabel(
            header, text="", font=(self.FONT_UI, 12), text_color=self.MUTED
        )
        self.lbl_progress.grid(row=0, column=1, sticky="e")

        # ── 细进度条 ──
        self.progress_bar = ctk.CTkProgressBar(
            root,
            height=2,
            corner_radius=1,
            border_width=0,
            fg_color=self.BORDER,
            progress_color=self.ACCENT,
        )
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(14, 0))

        # ── 内容卡片 ──
        card = ctk.CTkFrame(
            root,
            fg_color=self.SURFACE,
            corner_radius=16,
            border_width=1,
            border_color=self.BORDER,
        )
        card.grid(row=2, column=0, sticky="ew", pady=(26, 0))
        card.grid_columnconfigure(0, weight=1)

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=0, column=0, sticky="ew", padx=52, pady=(46, 34))
        inner.grid_columnconfigure(0, weight=1)

        # 译文（小字，弱化）
        self.txt_translation = self._make_text(
            inner, 2, 18, self.TRANSLATION, self.FONT_UI
        )
        self.txt_translation.grid(row=0, column=0, sticky="ew")
        self.txt_translation.tag_configure("muted", foreground=self.MUTED)

        # 原文（主视觉，当前单词高亮）
        self.txt_original = self._make_text(inner, 3, 29, self.FG, self.FONT_MONO)
        self.txt_original.grid(row=1, column=0, sticky="ew", pady=(20, 0))
        self.txt_original.tag_configure("current", foreground=self.ACCENT)
        self.txt_original.tag_configure("muted", foreground=self.MUTED)

        # 输入行（已输入 / 光标 / 未输入三态）
        self.txt_input = self._make_text(inner, 3, 29, self.SUCCESS, self.FONT_MONO)
        self.txt_input.grid(row=2, column=0, sticky="ew", pady=(28, 0))
        self.txt_input.tag_configure("typed", foreground=self.SUCCESS)
        # 自动跳过的引号保持暗色，与"尚未输入"视觉一致
        self.txt_input.tag_configure("skipped", foreground=self.GHOST)
        # 光标用背景色块覆盖下一个待输入字符，避免插入额外字符导致串位
        self.txt_input.tag_configure("caret", background=self.ACCENT, foreground=self.BG)
        self.txt_input.tag_configure("ghost", foreground=self.GHOST)
        self.txt_input.tag_configure("muted", foreground=self.MUTED)

        # 窗口尺寸变化后重算行高
        self.bind("<Configure>", self._on_resize)

        # ── 卡片底部状态栏：书名 + 提示 ──
        ctk.CTkFrame(card, height=1, fg_color="#2c3350").grid(
            row=1, column=0, sticky="ew", padx=52
        )

        footer = ctk.CTkFrame(card, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=52, pady=(14, 20))
        footer.grid_columnconfigure(1, weight=1)

        book_name = os.path.basename(self.book_path)
        if len(book_name) > 44:
            book_name = book_name[:22] + "…" + book_name[-18:]

        self.lbl_book = ctk.CTkLabel(
            footer, text=book_name, font=(self.FONT_UI, 11), text_color=self.MUTED
        )
        self.lbl_book.grid(row=0, column=0, sticky="w")

        self.lbl_hint = ctk.CTkLabel(
            footer, text="", font=(self.FONT_UI, 12), text_color=self.SUCCESS
        )
        self.lbl_hint.grid(row=0, column=1, sticky="e")

        # ── 完成页（整窗覆盖，默认隐藏）──
        self.completion_frame = ctk.CTkFrame(
            self, fg_color=self.BG, corner_radius=0
        )
        panel = ctk.CTkFrame(self.completion_frame, fg_color="transparent")
        panel.place(relx=0.5, rely=0.5, anchor="center")

        self.lbl_complete = ctk.CTkLabel(
            panel,
            text="🎉",
            font=(self.FONT_UI, 44),
            text_color=self.ACCENT,
        )
        self.lbl_complete.pack(pady=(0, 10))

        ctk.CTkLabel(
            panel,
            text="全书完成",
            font=(self.FONT_UI, 26, "bold"),
            text_color=self.FG,
        ).pack(pady=(0, 8))

        ctk.CTkLabel(
            panel,
            text="这本书的每一句都打完了",
            font=(self.FONT_UI, 12),
            text_color=self.MUTED,
        ).pack(pady=(0, 32))

        buttons = ctk.CTkFrame(panel, fg_color="transparent")
        buttons.pack()

        self.btn_restart = ctk.CTkButton(
            buttons,
            text="重新开始",
            width=126,
            height=38,
            corner_radius=10,
            font=(self.FONT_UI, 13),
            fg_color=self.ACCENT,
            hover_color="#6188d4",
            text_color=self.BG,
            command=self._restart_book,
        )
        self.btn_restart.pack(side="left", padx=(0, 10))

        self.btn_new_book = ctk.CTkButton(
            buttons,
            text="打开新书",
            width=126,
            height=38,
            corner_radius=10,
            font=(self.FONT_UI, 13),
            fg_color="transparent",
            hover_color=self.BORDER,
            border_width=1,
            border_color=self.BORDER,
            text_color=self.FG,
            command=self._open_new_book,
        )
        self.btn_new_book.pack(side="left")

        self._flash_after_id = None

        self.update_idletasks()
        apply_dark_titlebar(self)
        self._disable_ime()

    # ── 文本控件辅助 ──────────────────────────────────────────────

    def _make_text(self, parent, rows, size, color, family):
        """创建只读、无边框、支持标签着色的文本控件。"""
        widget = tk.Text(
            parent,
            width=1,  # 宽度交给 grid 的 sticky="ew"，避免按默认 80 字符撑开布局
            height=rows,
            font=(family, size),
            fg=color,
            bg=self.SURFACE,
            bd=0,
            relief="flat",
            highlightthickness=0,
            wrap="word",
            cursor="arrow",
            takefocus=0,
            padx=0,
            pady=0,
            spacing1=0,
            spacing2=8,
            spacing3=0,
            insertwidth=0,
            selectbackground=self.SURFACE,
            selectforeground=color,
        )
        widget.configure(state="disabled")
        return widget

    def _set_text(self, widget, parts, fit=True):
        """用 (文本, 标签) 片段重写控件内容，可选择是否重算行高。"""
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for content, tag in parts:
            widget.insert("end", content, tag if tag else ())
        widget.configure(state="disabled")
        if fit:
            self._fit_height(widget)

    def _fit_height(self, widget):
        """按实际折行数收紧行高，避免多余空白或被裁掉。

        不用 count(-displaylines)：它只统计可见区域内的行，行高越小结果越少，
        会形成"越裁越少"的循环。这里按 display line 索引递推，结果与可见高度无关。
        """
        widget.update_idletasks()
        rows = 1
        index = widget.index("1.0")
        while rows < 100:
            nxt = widget.index(f"{index} + 1 display lines")
            if widget.compare(nxt, ">=", "end") or nxt == index:
                break
            rows += 1
            index = nxt
        if int(widget.cget("height")) != rows:
            widget.configure(height=rows)

    def _refit_texts(self):
        """窗口尺寸变化后重新计算三块文本的行高。"""
        for widget in (self.txt_translation, self.txt_original, self.txt_input):
            self._fit_height(widget)

    def _on_resize(self, event):
        """只响应主窗口自身的尺寸变化。"""
        if event.widget is not self:
            return
        self.after_idle(self._refit_texts)

    # ── Sentence loading ──────────────────────────────────────────

    def _load_sentence(self, index):
        """加载指定序号的句子，并准备翻译和音频资源。"""
        if index >= len(self.sentences):
            self._show_completion()
            return

        self.app_state = State.LOADING
        self._set_text(self.txt_translation, [("", None)])
        self._set_text(self.txt_original, [("正在准备…", "muted")])
        self._set_text(self.txt_input, [("", None)])
        self.lbl_hint.configure(text="")
        self._update_progress(index)

        # Check if prefetch cache has this sentence ready
        if index in self._prefetch_cache:
            cached = self._prefetch_cache.pop(index)

            # Audio still needs to be prepared (can't prefetch pygame Sounds across calls)
            def _bg_audio():
                try:
                    self.audio.prepare_sentence(cached["sentence"], cached["words"])
                except Exception:
                    # 音频生成失败不应阻塞正文显示
                    pass
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
            try:
                audio_future.result()
            except Exception:
                # 音频生成失败（如 TTS 服务不可用）时仍然显示句子
                pass
            self.after(0, self._display_sentence, sentence, translation, words)

        threading.Thread(target=_bg, daemon=True).start()

    def _display_sentence(self, sentence, translation, words):
        """将当前句子的文本、翻译和输入状态显示到界面上。"""
        self.sentence = sentence
        # 用于比对版本：将 … 展开为 ...，让用户打三个句号即可匹配
        self.compare_sentence = sentence.replace("…", "...")
        # compare_sentence 下标 → 原文显示下标（… 会展开成三个字符）
        mapping = []
        display_index = 0
        for ch in sentence:
            repeat = 3 if ch == "…" else 1
            mapping.extend([display_index] * repeat)
            display_index += 1
        mapping.append(display_index)
        self._cmp_to_disp = mapping
        self.cursor_pos = 0
        # 引号只是排版包裹，不作为输入内容：自动跳过
        self._skip_quotes()
        self.display_words = (
            self.compare_sentence.split()
        )  # 展开后的单词（与词边界一致）
        self.word_boundaries = self._compute_word_boundaries(self.compare_sentence)
        self.current_word_idx = 0
        self.app_state = State.TYPING

        self._set_text(self.txt_translation, [(translation, None)])
        self._set_text(self.txt_original, [(sentence, None)])
        self._update_input_display()
        self._fit_height(self.txt_input)
        self._highlight_word()
        self.lbl_hint.configure(text="")
        # 首次测量可能发生在布局完成前，等空闲时再校正一次折行高度
        self.after_idle(self._refit_texts)

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
            try:
                audio_future.result()
            except Exception:
                pass  # 预取失败时下次会重新生成
            self._prefetch_cache[index] = {
                "sentence": sentence,
                "translation": translation,
                "words": words,
            }

        self._prefetch_executor.submit(_prefetch)

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
    def _char_from_keysym(keysym):
        """event.char 为空时，用 keysym 推断要输入的字符。"""
        if len(keysym) == 1 and keysym.isprintable():
            return keysym
        if keysym.startswith("KP_") and keysym[3:].isdigit():
            return keysym[3:]
        return ""

    def _disable_ime(self):
        """关闭本窗口的输入法，避免中文 IME 吞掉按键。"""
        try:
            import ctypes

            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            ctypes.windll.imm32.ImmAssociateContext(hwnd, None)
        except Exception:
            pass

    @staticmethod
    def _normalize_char(ch):
        """归一化字符：全角转半角，智能标点转 ASCII。"""
        # NFKC 把 "１"→"1"、"ａ"→"a"、"！"→"!" 等全角/兼容字符折叠为半角，
        # 避免输入法处于全角模式时"明明打对了却判错"。
        ch = unicodedata.normalize("NFKC", ch)
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
        if not ch:
            # 输入法拦截或小键盘按键可能不带 char，退回用 keysym 推断
            ch = self._char_from_keysym(event.keysym)
        if not ch or len(ch) != 1:
            return "break"

        # Ignore control chars, keep printable Unicode for punctuation compatibility
        if ord(ch) < 32:
            return "break"

        self._skip_quotes()
        if self.cursor_pos >= len(self.compare_sentence):
            return "break"
        expected = self._normalize_char(self.compare_sentence[self.cursor_pos])
        typed = self._normalize_char(ch)

        # 测试模式：按 't' 视为正确，其他键视为错误
        if self.test_mode:
            correct = typed == "t"
        else:
            correct = typed == expected

        if correct:
            self.cursor_pos += 1
            self._skip_quotes()
            self._update_input_display()

            # Check if we moved to a new word segment
            new_word_idx = self._get_word_index(self.cursor_pos)
            if new_word_idx != self.current_word_idx and new_word_idx < len(
                self.display_words
            ):
                self.current_word_idx = new_word_idx
                self._highlight_word()
                self.audio.transition_to_word(self.display_words[new_word_idx])

            # Check if sentence is complete (使用 compare_sentence 的长度判断)
            if self.cursor_pos >= len(self.compare_sentence):
                self.app_state = State.SENTENCE_COMPLETE
                self.audio.play_sentence()
                self._poll_sentence_played()
        else:
            # Wrong character: reset to start of current word
            if self.word_boundaries:
                start, end = self.word_boundaries[self.current_word_idx]
                self.cursor_pos = start
                self._skip_quotes()
                self._update_input_display()
            self._flash_error()

        return "break"

    def _get_word_index(self, pos):
        """根据字符位置返回所在的单词片段索引。"""
        for i, (_, end) in enumerate(self.word_boundaries):
            if pos < end:
                return i
        return len(self.word_boundaries) - 1

    def _flash_error(self):
        """打错时窗口背景短暂染上暗红。"""
        if self._flash_after_id is not None:
            self.after_cancel(self._flash_after_id)
        self.configure(fg_color=self.FLASH_BG)
        self._flash_after_id = self.after(140, self._clear_flash)

    def _clear_flash(self):
        """恢复窗口原本的背景色。"""
        self.configure(fg_color=self.BG)
        self._flash_after_id = None

    def _poll_sentence_played(self):
        """轮询整句音频是否至少播放一遍，随后显示回车提示。"""
        if self.app_state != State.SENTENCE_COMPLETE:
            return
        if self.audio.has_sentence_played_once():
            self.lbl_hint.configure(text="按回车键继续")
        else:
            self.after(200, self._poll_sentence_played)

    def _highlight_word(self):
        """在原文行高亮当前正在输入的单词。"""
        self.txt_original.tag_remove("current", "1.0", "end")
        if not self.word_boundaries or not self._cmp_to_disp:
            return
        start, end = self.word_boundaries[self.current_word_idx]
        # 前导引号已自动跳过，不计入当前单词的高亮范围
        while start < end and self.compare_sentence[start] in self.SKIP_CHARS:
            start += 1
        # 尾部空格不参与高亮，视觉上更贴近单词本身
        while end > start and self.compare_sentence[end - 1] == " ":
            end -= 1
        if end <= start:
            return
        begin_display = self._cmp_to_disp[start]
        end_display = self._cmp_to_disp[end]
        self.txt_original.tag_add(
            "current",
            f"1.0 + {begin_display} chars",
            f"1.0 + {end_display} chars",
        )

    def _skip_quotes(self):
        """把光标推进到下一个需要输入的字符，跳过引号。"""
        text = self.compare_sentence
        total = len(text)
        while self.cursor_pos < total and text[self.cursor_pos] in self.SKIP_CHARS:
            self.cursor_pos += 1

    def _typed_runs(self, text):
        """把已输入文本按「跳过的引号 / 实际输入」切成 (片段, 标签)。"""
        runs = []
        for ch in text:
            tag = "skipped" if ch in self.SKIP_CHARS else "typed"
            if runs and runs[-1][1] == tag:
                runs[-1][0] += ch
            else:
                runs.append([ch, tag])
        return [(chunk, tag) for chunk, tag in runs]

    def _update_input_display(self):
        """刷新输入行：已输入、光标所在的待输入字符、其余未输入字符。"""
        parts = list(self._typed_runs(self.compare_sentence[: self.cursor_pos]))
        rest = self.compare_sentence[self.cursor_pos :]
        if rest:
            # 光标覆盖当前待输入的字符，不额外占用位置，保证与原文逐字对齐
            parts.append((rest[0], "caret"))
            if len(rest) > 1:
                parts.append((rest[1:], "ghost"))
        # 打字过程中总长度不变，无需重算行高
        self._set_text(self.txt_input, parts, fit=False)

    def _update_progress(self, index):
        """更新顶栏的句子计数与进度条。"""
        total = len(self.sentences)
        self.lbl_progress.configure(text=f"{index + 1} / {total}")
        self.progress_bar.set((index + 1) / total if total else 0)

    # ── Completion ────────────────────────────────────────────────

    def _show_completion(self):
        """展示整本书完成后的收尾界面。"""
        self.app_state = State.BOOK_COMPLETE
        self.audio.stop()
        self._set_text(self.txt_translation, [("", None)])
        self._set_text(self.txt_original, [("", None)])
        self._set_text(self.txt_input, [("", None)])
        self.lbl_hint.configure(text="")
        self.completion_frame.place(relx=0, rely=0, relwidth=1, relheight=1)

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
