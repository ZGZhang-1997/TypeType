import hashlib
import json
import os
import sys

import deepl


def _default_cache_dir():
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return "data"


class DeepLTranslator:
    def __init__(self, api_key, cache_dir=None):
        self._translator = deepl.Translator(api_key)
        self._cache_dir = cache_dir or _default_cache_dir()
        self._cache_path = os.path.join(self._cache_dir, "translation_cache.json")
        self._cache = self._load_cache()

    def _load_cache(self):
        if os.path.exists(self._cache_path):
            with open(self._cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_cache(self):
        os.makedirs(self._cache_dir, exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def _key(self, text):
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def translate(self, sentence):
        k = self._key(sentence)
        if k in self._cache:
            return self._cache[k]
        try:
            result = self._translator.translate_text(sentence, target_lang="ZH")
            translation = result.text
        except Exception:
            translation = "[翻译失败]"
        self._cache[k] = translation
        self._save_cache()
        return translation
