"""文本处理模块，负责加载书籍内容并拆分为可练习的句子。"""

import os
import re
import sys

import nltk
from nltk.tokenize import sent_tokenize


def ensure_nltk_data():
    """确保分句所需的 nltk 数据已可用。"""
    # PyInstaller 打包时，nltk 数据在临时解压目录中
    if getattr(sys, "frozen", False):
        nltk.data.path.insert(0, os.path.join(sys._MEIPASS, "nltk_data"))
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)


def load_book(filepath):
    """读取整本 txt 书籍内容并返回字符串。"""
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def split_sentences(text):
    """按标题、短行和正文规则将文本拆分成句子列表。"""
    ensure_nltk_data()
    results = []

    # Split into paragraphs by blank lines
    paragraphs = re.split(r"\n\s*\n", text)

    for para in paragraphs:
        # Split paragraph into individual lines
        lines = [ln.strip() for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue

        # If the paragraph has multiple separate short lines
        # (e.g. chapter headings, titles, dates), treat each as its own sentence
        if len(lines) > 1 and all(len(ln) < 80 for ln in lines):
            results.extend(lines)
            continue

        # For single short lines (headings, numbers, etc.), keep as-is
        joined = " ".join(lines)
        if len(joined) < 80 and not any(c in joined for c in ".!?"):
            results.append(joined)
            continue

        # For normal prose, use nltk sentence tokenizer
        sents = sent_tokenize(joined, language="english")
        for s in sents:
            s = s.strip()
            if s:
                results.append(s)

    return results
