"""翻译模块，负责调用 DeepL 并缓存翻译结果。"""

import hashlib
import json
import os
import sys

import deepl


def _default_cache_dir():
    """返回翻译缓存目录，兼容源码运行和打包运行。"""
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(sys.executable), "data")
    return "data"


class DeepLTranslator:
    """DeepL 翻译器封装，带本地 JSON 缓存。"""

    def __init__(self, api_key, cache_dir=None):
        """初始化 DeepL 客户端并加载缓存文件。"""
        self._translator = deepl.Translator(api_key)
        self._cache_dir = cache_dir or _default_cache_dir()
        self._cache_path = os.path.join(self._cache_dir, "translation_cache.json")
        self._cache = self._load_cache()

    def _load_cache(self):
        """从磁盘读取已有翻译缓存。"""
        if os.path.exists(self._cache_path):
            with open(self._cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_cache(self):
        """将当前翻译缓存写回磁盘。"""
        os.makedirs(self._cache_dir, exist_ok=True)
        with open(self._cache_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def _key(self, text):
        """为原文生成稳定的缓存键。"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def translate(self, sentence):
        """翻译单句文本，失败时返回占位提示。"""
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
