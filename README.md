# LifeBook

把零散的信息（链接、文字、截图）变成结构化的知识笔记，再变成可搜索的语料库和播客音频。

## 它能做什么

```
粘贴链接/文字/截图
       ↓
   LLM 提取摘要、分类、打标签
       ↓
   生成结构化 Markdown 笔记
       ↓
   向量索引，支持语义搜索
       ↓
   （可选）生成播客音频
```

**输入**：一个 URL、一段文字、或一张图片
**输出**：一篇带标题、摘要、要点、标签、分类的 Markdown 笔记，存入你的知识库

附加能力：
- **写作助手**：从概念到成稿的交互式写作流程
- **语义搜索**：用自然语言在所有笔记中查找相关内容
- **播客生成**：把笔记变成双人对话风格的音频
- **飞书 Bot**：在飞书里直接录入、搜索、写作
- **Web 界面**：浏览器里浏览、搜索、管理笔记

## 快速开始

```bash
# 1. 安装
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. 初始化（创建目录结构和配置文件）
lifebook init

# 3. 配置 API Key
#    编辑 lifebook doctor 显示的配置文件，填入：
#    - llm.api_key：LLM API Key（必需）
#    - tavily.api_key：网页抓取 API Key（可选，不填则用 httpx 直接抓取）

# 4. 检查配置是否正确
lifebook doctor

# 5. 开始使用
lifebook ingest "https://example.com/article"
lifebook process
lifebook search "你想找的内容"
```

## 常用命令

### 录入与处理

```bash
lifebook ingest "https://example.com/article"   # 录入 URL
lifebook ingest "一段文字内容"                    # 录入文字
lifebook ingest image.png                        # 录入图片
lifebook process                                 # 处理收件箱中所有待处理文件
lifebook process --watch                         # 监听模式，自动处理新文件
lifebook process --file path/to/file.md          # 处理单个文件
lifebook recover                                 # 恢复卡在处理中的文件
lifebook retry                                   # 重试之前抓取失败的文件
```

### 搜索与浏览

```bash
lifebook search "机器学习的最新进展"              # 语义搜索
lifebook web                                     # 启动 Web 界面（http://127.0.0.1:8080）
lifebook web --port 3000                         # 自定义端口
```

### 索引

```bash
lifebook index                                   # 增量更新向量索引
lifebook index --full                            # 全量重建索引
```

### 写作

```bash
lifebook writer-status                           # 查看当前写作状态
lifebook publish                                 # 发布当前草稿为笔记
lifebook restore                                 # 从备份恢复草稿
lifebook restore-published                       # 恢复最近一次发布的草稿
```

### 播客

```bash
lifebook podcast path/to/note.md                 # 从单篇笔记生成播客
lifebook podcast path/to/note.md --send          # 生成并发送到飞书
lifebook podcast-multi --since 2026-04-22 --limit 10 --send  # 合集：最近 10 篇
```

### 飞书 Bot

```bash
lifebook serve                                   # 启动飞书 Bot（长驻进程）
```

飞书 Bot 支持的命令：
- `/process` — 处理收件箱
- `/search 关键词` — 语义搜索
- `/write` — 开始写作
- `/publish` — 发布草稿
- `/update-index` — 更新向量索引
- `/status` — 查看系统状态

## 配置

运行 `lifebook init` 后会生成配置文件（路径由 `lifebook doctor` 显示）。

```yaml
# 必填
llm:
  base_url: https://api.deepseek.com
  api_key: "your-api-key"
  model: deepseek-chat

knowledge:
  root: ~/Documents/Knowledge   # 知识库根目录

# 可选
feishu:                          # 飞书 Bot
  app_id: "cli_xxx"
  app_secret: "xxx"

tavily:                          # 网页抓取（不填则用 httpx）
  api_key: "your-tavily-key"

tts:                             # 语音合成（播客功能需要）
  base_url: https://your-tts-endpoint
  api_key: "your-key"
  model: your-tts-model
```

配置解析顺序：`--config` 参数 → `LIFEBOOK_CONFIG` 环境变量 → 指针文件 → 知识库根目录默认路径

## 目录结构

```
~/Documents/Knowledge/           # 知识库根目录
├── 10-sources/                  # 原始录入文件（URL、文字、图片）
├── 20-topics/                   # LLM 生成的结构化笔记（按分类组织）
├── 30-trajectories/             # 学习轨迹（可选）
├── 99-publish/                  # 写作发布的笔记
└── .lifebook/                   # 系统状态（索引、配置、草稿）
    ├── config.yaml
    ├── vector_store/            # ChromaDB 向量数据库
    └── draft.json               # 当前写作草稿
```

## Web 界面

```bash
# 启动后端（API + 静态文件）
lifebook web

# 前端开发（热更新）
cd frontend && npm install && npm run dev   # http://localhost:5173
```

前端构建产物输出到 `lifebook/web/static/`，由 FastAPI 自动托管。

## 技术栈

- **LLM**：Anthropic Claude / DeepSeek（通过 OpenAI 兼容 API）
- **向量搜索**：ChromaDB + SentenceTransformers (paraphrase-multilingual-MiniLM-L12-v2)
- **TTS**：MiMo TTS（OpenAI 兼容 API）
- **Web 后端**：FastAPI
- **Web 前端**：React + TypeScript + Vite + TanStack Query + shadcn/ui
- **飞书集成**：lark_oapi WebSocket

## 环境要求

- Python ≥ 3.10
- macOS / Linux（文件锁使用 `fcntl`，不支持 Windows）
- ffmpeg / ffprobe（播客音频处理需要）
