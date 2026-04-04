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
    sentences = sent_tokenize(text, language="english")
    return [s.strip() for s in sentences if s.strip()]
