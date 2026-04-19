# LifeBook 项目约束与规范

## 项目结构
- 代码：`/Users/damao/Projects/LifeBook/`（Python 3.11 + venv）
- 数据：`~/Documents/Knowledge/`（10-sources / 20-topics / 30-trajectories / .lifebook/config.yaml）
- 核心愿景："认知演化伙伴"，详见 `~/Documents/Knowledge/product-vision.md`

## Category/Tag 规则（2026-04 锁定）

### Category 固定 11 选一
- AI技术
- 开发者工具  
- 半导体
- 消费电子
- 媒体生态
- 组织与劳动
- 科技监管
- 经济与产业
- 3D打印与数字制造
- 游戏
- 生活方式

**不得新建、不得改名**

### 边界优先级（避免打架）
1. 游戏里的 AI → AI技术
2. CAD 库主线是 SDK → 开发者工具，主线是打印工作流 → 3D打印与数字制造
3. 硬件参数 → 消费电子，使用体验 → 生活方式
4. 管理实践 → 组织与劳动，个人状态 → 生活方式
5. 宏观产业 → 经济与产业，个人消费 → 生活方式
6. AI/平台监管统一 → 科技监管
7. 芯片全流程 → 半导体

### Tag 规则
- **内容性质白名单**（每篇必有 1 个）：资讯、趣闻、教程、观点、深度分析、参考文档、工具介绍、案例研究
- **主体/概念/交叉领域**（2-3 个）
- tag 不得与 category 同名
- tag 必须合规 Obsidian 语法（仅中文/英文/数字/连字符/下划线）→ 代码 `sanitize_tags` 兜底

### Wikilink 规则
- wikilink 文本和文件名必须走同一套 `slugify` 规则（见 `notes.py:wikilink_text`）

## 技术决策
- DeepSeek 支持 tool_use（function calling），但 Anthropic 兼容端点不稳定——有时返回结构化 tool_use block，有时退化为文本输出（自定义 `<｜DSML｜...>` 标记）。已讨论切换到 DeepSeek 原生 OpenAI 兼容端点（`https://api.deepseek.com/v1`）以获得更稳定的 function calling 支持，待定。

## 部署注意事项
- Hermes $HOME 是 `/Users/damao/.hermes/profiles/ermao/home`（非真实 home）。LifeBook 部署时 config 路径需复制或用绝对路径。
- 飞书 SDK WebSocket 连接成功后无 stdout 日志，用 lsof 检查网络连接确认 bot 状态。