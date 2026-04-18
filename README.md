# LifeBook

个人知识库系统。详细愿景见 `~/Documents/Knowledge/product-vision.md`。

## 当前阶段：Phase 0（裸奔记录）

目标：跑通"录入 → 异步加工 → 每日摘要推送"的最小闭环。

## 项目结构

```
LifeBook/
├── lifebook/           # 主包
│   ├── __init__.py
│   ├── config.py       # 配置加载
│   ├── executor.py     # 加工流程
│   ├── llm.py          # LLM 客户端（Anthropic 兼容接口）
│   ├── feishu.py       # 飞书机器人
│   ├── digest.py       # 每日摘要
│   └── cli.py          # 命令行入口
├── scripts/            # 启动脚本、launchd plist
├── tests/
├── config.example.yaml # 配置模板
└── pyproject.toml
```

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
lifebook digest               # 生成并推送今日摘要
lifebook serve                # 启动飞书机器人监听
```
