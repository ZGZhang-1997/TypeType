# TypeType

一款英语打字练习桌面应用。读取英文书籍（txt 格式），按句子拆分，逐句显示原文、中文翻译和打字输入区域，配合单词和句子语音朗读，帮助提升英语能力。

## 功能特性

- **三行显示**：翻译（上）、原文（中）、打字输入（下）
- **逐字校验**：打对前进，打错回退到当前单词开头并闪红提示
- **单词语音循环**：打字过程中循环朗读当前单词（pyttsx3）
- **句子语音循环**：打完整句后循环播放句子朗读（edge-tts）
- **智能分句**：自动识别章节标题、短行等结构，对正文段落用 nltk 分句
- **中文翻译**：通过 DeepL API 自动翻译，结果本地缓存
- **进度保存**：自动保存打字进度，下次启动可继续
- **预加载**：打当前句时后台预加载下一句的翻译和音频
- **测试模式**：`main.py` 中将 `TEST_MODE` 设为 `True`，按 `t` 即视为输入正确，方便调试

## 环境要求

- Python 3.10+
- Windows 系统
- DeepL API Key（[免费注册](https://www.deepl.com/pro#developer)）

## 安装

```bash
# 创建虚拟环境
python -m venv venv

# 激活虚拟环境
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

## 配置

编辑 `config.ini`：

```ini
[deepl]
api_key_file = C:\path\to\deepl_key.txt

[audio]
voice = en-US-AriaNeural
```

- `api_key_file`：存放 DeepL API Key 的文件路径，文件内只写一行 Key
- `voice`：edge-tts 语音，可选值参考 [edge-tts 文档](https://github.com/rany2/edge-tts)

## 使用

```bash
python main.py
```

1. 首次启动会弹出文件选择框，选择一个英文 txt 书籍
2. 有存档时会提示：继续上次 / 选择新书 / 退出
3. 照着原文打字，打对前进，打错回退到词首
4. 打完一句后等句子朗读播完，按回车进入下一句
5. 选择新书时会自动清除所有缓存和进度

## 项目结构

```
├── main.py            # 入口：配置加载、选书、启动应用
├── app.py             # GUI 主窗口与打字逻辑
├── audio_manager.py   # 音频生成与播放管理
├── text_processor.py  # 书籍加载与分句
├── translator.py      # DeepL 翻译与缓存
├── progress.py        # 进度存取
├── config.ini         # 配置文件
├── requirements.txt   # Python 依赖
└── data/              # 运行时数据（自动生成）
    ├── progress.json
    ├── translation_cache.json
    └── audio_cache/
```

## 依赖

| 包 | 用途 |
|---|---|
| customtkinter | GUI 界面 |
| pyttsx3 | 单词语音生成（wav） |
| edge-tts | 句子语音生成（mp3） |
| pygame-ce | 音频播放 |
| deepl | DeepL 翻译 API |
| nltk | 英文分句 |
