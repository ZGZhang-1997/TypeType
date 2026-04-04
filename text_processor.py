import re

import nltk
from nltk.tokenize import sent_tokenize


def ensure_nltk_data():
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)


def load_book(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


def split_sentences(text):
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
