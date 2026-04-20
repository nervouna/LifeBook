# LifeBook

个人知识库系统。详细愿景见 `~/Documents/Knowledge/product-vision.md`。

## 当前阶段：Phase 0（裸奔记录）

目标：跑通"录入 → 异步加工 → 每日摘要推送"的最小闭环。

## 项目结构

```
LifeBook/
├── lifebook/                # 主包
│   ├── cli.py              # 命令行入口
│   ├── config.py           # 配置加载
│   ├── executor.py         # 加工流程（8 步 pipeline）
│   ├── feishu.py           # 飞书机器人（命令路由 + 业务逻辑）
│   ├── feishu_transport.py # 飞书 WebSocket 通信层
│   ├── fetcher.py          # 网页抓取
│   ├── indexer.py          # 向量索引增量更新
│   ├── ingest.py           # 录入（文本 / URL）
│   ├── llm.py              # LLM 客户端（Anthropic Messages API）
│   ├── notes.py            # 笔记文件读写原语
│   ├── protocols.py        # Protocol 接口定义（LLM / Fetcher / Store）
│   ├── store.py            # 文件系统笔记存储（fcntl 锁）
│   ├── vector.py           # 向量检索
│   ├── writer.py           # 交互式写作代理
│   └── prompts/            # LLM 提示词
│       ├── extract.py      #   内容提取提示词
│       └── writer.py       #   写作提示词
├── tests/
├── config.example.yaml     # 配置模板
└── pyproject.toml
```

## 架构

核心流水线：inbox 素材 → LLM 提取 → 主题笔记 → 向量索引。

- **executor.py** — 8 步 pipeline：claim → fetch → extract → validate → link → compose → write → mark
- **feishu.py** — 飞书命令路由（`/write`, `/publish`, `/process`, `/search`, `/status`）
- **feishu_transport.py** — 飞书 WebSocket 生命周期 + 消息收发
- **protocols.py** — `LLMProtocol` / `FetcherProtocol` / `StoreProtocol` 接口定义，支持依赖注入
- **store.py** — 基于 fcntl 的文件锁，macOS/Linux only

## 数据位置

```
~/Documents/Knowledge/
├── 10-sources/         # 原始素材
├── 20-topics/          # 加工后的主题笔记
├── 30-trajectories/    # 演化轨迹（Phase 1）
└── .lifebook/
    ├── config.yaml     # 实际配置（拷贝自 config.example.yaml）
    ├── state.json
    ├── logs/
    └── graph.json
```

## 安装

```bash
cd /Users/damao/Projects/LifeBook
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.yaml ~/Documents/Knowledge/.lifebook/config.yaml
# 编辑配置，填入 LLM API key 和飞书凭证
```

## 使用

```bash
lifebook process              # 加工 inbox 中所有 status: inbox 的文件
lifebook process --file PATH  # 加工单个文件
lifebook serve                # 启动飞书机器人监听
lifebook index --full         # 重建向量索引
lifebook search "query"       # 语义搜索
lifebook doctor               # 检查配置和环境
```

## 自动启动（launchd）

飞书机器人通过 launchd 管理，开机自启、崩溃自动重启。

```bash
# 启动
launchctl load ~/Library/LaunchAgents/com.lifebook.serve.plist

# 停止
launchctl unload ~/Library/LaunchAgents/com.lifebook.serve.plist

# 重启
launchctl kickstart -k gui/$(id -u)/com.lifebook.serve

# 查看状态
launchctl list | grep lifebook

# 查看日志
tail -f ~/Library/Logs/lifebook-serve.log
```
