# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# nltk 的 punkt_tab 分词模型必须随包分发。
# 默认取当前用户的 nltk_data 目录，可用 NLTK_DATA 环境变量覆盖。
_nltk_root = os.environ.get(
    "NLTK_DATA",
    os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "nltk_data"),
)
_punkt_dir = os.path.join(_nltk_root, "tokenizers", "punkt_tab")
if not os.path.exists(_punkt_dir):
    raise SystemExit(
        "缺少 nltk 数据 punkt_tab: %s\n"
        "请先运行: python -c \"import nltk; nltk.download('punkt_tab')\"" % _punkt_dir
    )

datas = [(_punkt_dir, "nltk_data/tokenizers/punkt_tab")]

# customtkinter 的主题与字体资源需要随包分发
_ctk_dir = os.path.join(sys.prefix, "Lib", "site-packages", "customtkinter")
if os.path.isdir(_ctk_dir):
    datas.append((_ctk_dir, "customtkinter"))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=['pyttsx3.drivers', 'pyttsx3.drivers.sapi5'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='TypeType',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
