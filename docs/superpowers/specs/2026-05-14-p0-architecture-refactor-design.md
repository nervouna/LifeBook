# LifeBook P0 架构重构设计

**Date**: 2026-05-14
**Scope**: P0 — 业务核心层抽取 + DI 容器 + 拆三个上帝模块（writer / executor / cli）
**Status**: Draft，待用户复核

---

## 1. 背景与动机

仓库 38 个 Python 文件、~6000 行，三套入口（CLI / FastAPI / 飞书 Bot），四大业务（知识录入、向量检索、写作、播客）。架构审计发现 6 处贯穿性裂缝，分为 P0 / P1 / P2 三档，本 spec 仅覆盖 P0：

- **P0-1**：缺业务核心层。`web/services/` 已存在但仅 Web 用，CLI / 飞书直接调底层；同一动作的输入校验 / 结果格式化在三处重复（典型：`_format_results` 在 `feishu_commands.py:145` 与 `feishu_handler.py:110` 各写一遍）。每个 CLI 命令各自 `load_config()` + 各自 `LLMClient(cfg.llm)`，无 DI 容器。
- **P0-2**：三个上帝模块——`writer.py`（715 行）、`executor.py`（502 行）、`cli.py`（496 行），承担多个不同职责，修改成本高、可测试性差。

P1（持久化原子性 / Provider 抽象 / Config 拆分）和 P2（错误类型体系 / 测试结构 / Prompt 版本）留作后续 spec。

## 2. 目标与非目标

### 目标
- 提取 `lifebook/services/` 作为三入口共享的业务核心层
- 引入 `AppContext` 作为轻量 DI 容器
- 拆 `writer.py` 为 `lifebook/writer/` 包
- 拆 `executor.py` 为 `lifebook/pipeline/` 包
- 拆 `cli.py` 为按业务域分组的 `lifebook/cli/commands/*.py`
- 在重构前先补关键路径契约测试作为回归基线
- 5 阶段独立可合并，每阶段结束仓库仍可用

### 非目标
- 不在本次解决持久化原子性问题（P1）
- 不在本次抽象 LLM Provider（P1）
- 不在本次拆 Config 单体（P1）
- 不引入新的错误类型体系（P2）
- 不修改 Web API 路径
- 不修改飞书命令名
- 不修改持久化数据格式与目录结构

### 范围内的 CLI 行为变更
- CLI 子命令将分组重排（例 `lifebook ingest` → `lifebook inbox ingest`）。README 同步更新。

## 3. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│  入口适配层（Adapters）                                  │
│  cli/commands/*  |  web/api/*  |  feishu/handlers/*     │
└──────────────┬──────────────────────────────────────────┘
               │ DTOs (dataclass)
               ▼
┌─────────────────────────────────────────────────────────┐
│  服务层（lifebook/services/）                           │
│  InboxService · WriterService · SearchService           │
│  · IndexService · PodcastService                        │
└──────────────┬──────────────────────────────────────────┘
               │ AppContext 注入
               ▼
┌─────────────────────────────────────────────────────────┐
│  领域 / 基础设施层                                      │
│  writer/  pipeline/ (FetchStage→…→WriteStage)           │
│  store · vector · indexer · llm · prompts · podcast     │
└─────────────────────────────────────────────────────────┘
```

四个核心改动：
1. `AppContext` —— dataclass，启动时构造一次，三入口共享
2. `lifebook/services/` —— 5 个 service 类，构造收 `AppContext`、方法收 DTO 返回 DTO
3. `lifebook/writer/` —— 把 715 行的 `writer.py` 拆为 `state` / `repository` / `prompt` / `service` 四文件
4. `lifebook/pipeline/` —— 把 `executor.py` 改为 `Pipeline + 4 stage`，用例编排留在 `InboxService`

## 4. 服务层契约

### 4.1 目录结构

```
lifebook/services/
├── __init__.py        # 导出 AppContext
├── dto.py             # 全部请求 / 响应 dataclass
├── inbox.py           # InboxService
├── writer.py          # WriterService
├── search.py          # SearchService
├── index.py           # IndexService
└── podcast.py         # PodcastService
```

### 4.2 AppContext

- dataclass，字段：`config: Config`、`llm_client: LLMClient`、`note_store: NoteStore`、`vector_index: VectorIndex`
- `vector_index` 用 lazy property（不调用就不加载 sentence-transformers），避免 CLI 启动慢
- 每个入口启动时构造一次，全程透传给所有 service

### 4.3 DTO 设计

- 全部放 `dto.py`，纯 `dataclass`，不引入 Pydantic
- Web schemas（在 `web/schemas.py`）继续作为 HTTP 边界的 Pydantic 模型，由 `web/api/*.py` 在边界完成 schema → DTO 的转换
- 这是有意的两层模型：边界做严格校验、内部统一 DTO

### 4.4 5 个 Service

| Service | 当前实现位置 | 公共方法（草） |
|---|---|---|
| `InboxService` | `ingest.py` + `executor.py` | `ingest_url` / `ingest_text` / `ingest_image` / `process_pending` / `process_one` / `recover_stale` / `retry_failed` |
| `WriterService` | `writer.py` | `start_writing` / `continue_writing` / `publish` / `status` / `restore` / `restore_published` |
| `SearchService` | `vector.find_related` 的封装 | `search` |
| `IndexService` | `indexer.py` | `incremental_update` / `full_rebuild` |
| `PodcastService` | `podcast.py` | `from_note` / `from_recent_notes` |

### 4.5 边界澄清

- **飞书被动 ingest**（`feishu_handler.py` 收 URL/图片/文字消息那段）：改为调 `InboxService.ingest_*`
- **search 是否触发 process**：保持现状，本次不改业务行为
- **PodcastService 边界**：service 层只做"用例编排"，不把 TTS / audio 等基础设施拆到 service 层

## 5. writer/ 包拆分

### 5.1 目录结构

```
lifebook/writer/
├── __init__.py       # re-export 旧 Writer 名称作为兼容层（一阶段后清理）
├── state.py          # DraftStateMachine — 纯状态机，无 LLM、无 I/O
├── repository.py     # DraftRepository  — draft.json/.md/.history.json 读写、备份恢复
├── prompt.py         # WriterPromptBuilder — 拼接 system + 上下文 + 历史
└── service.py        # WriterService 实现 — 编排上述三者 + 调 ctx.llm_client
```

### 5.2 职责切分

- **`DraftStateMachine`**：定义 4 stage（concept / framework / content / review）+ 合法转移表 + 转移产生的元数据 patch。**不依赖**文件系统、LLM、外部资源；纯内存可测。
- **`DraftRepository`**：唯一负责 draft 三件套的读写、备份、恢复、`restore-published`。所有路径计算集中于此。
- **`WriterPromptBuilder`**：根据 stage + 输入参数选择模板（保留 `prompts/writer.py` 的字符串模板）并填充。
- **`WriterService`**：service 层方法的真正实现，**不直接读文件、不拼 prompt**，只协调上述三者 + 调 `ctx.llm_client`。

### 5.3 关键决定

- 状态机原语保持轻量，不引入通用 FSM 框架
- draft 文件路径不变（`.lifebook/draft.json` 等保持原位置），无数据迁移
- 现有 `test_writer.py` / `test_writer_e2e.py` / `test_writer_coverage.py` 不删，按层级重新归档：
  - `tests/writer/test_state.py`、`tests/writer/test_repository.py`、`tests/writer/test_service_e2e.py`
- 旧 `Writer` 类如有外部 import，在 `lifebook/writer/__init__.py` re-export 等价构造（接收旧参数返回 `WriterService` 实例），跨一个阶段再清理

## 6. pipeline/ 包（executor 管道化）

### 6.1 目录结构

```
lifebook/pipeline/
├── __init__.py       # 导出 Pipeline、PipelineStage 协议、PipelineContext
├── stage.py          # PipelineStage 协议 + PipelineContext 数据类
├── fetch.py          # FetchStage   — fetch_if_needed
├── extract.py        # ExtractStage — LLM 抽取（含图像分支）
├── link.py           # LinkStage    — 关联笔记发现
└── write.py          # WriteStage   — 写 topic 文件 + 更新源文件
```

### 6.2 核心约定

- **`PipelineContext`**：dataclass，stage 间传递。字段：`source_path`、`meta`（frontmatter）、`body`（正文）、`extracted`（LLM 输出）、`topic_path`（写完后填入）、`cfg`、`llm_client`、`note_store`。stage 就地修改 ctx。
- **`PipelineStage` 协议**：`def run(self, ctx: PipelineContext) -> None`，使用 `typing.Protocol`，不强制继承
- **同步**：保持现有同步语义，不引入 async
- **抛错语义**：stage 抛 `StageError`（含 `recoverable` 标志）→ Pipeline 捕获 → 写回源文件状态（`fetch_failed` / `processing_error`）

### 6.3 职责归位

| 原 executor 职责 | 去处 |
|---|---|
| claim / mark_processed / dedup / recover_stale / retry_failed | `InboxService` |
| `fetch_if_needed` | `FetchStage` |
| `_extract` / `_extract_image` / `_build_extract_prompt` | `ExtractStage`（prompt 构造以函数形式放在 `prompts/extract.py`） |
| `_validate` | `ExtractStage` 末尾 |
| `_link_related` | `LinkStage` |
| `_write_topic` | `WriteStage` |

### 6.4 兼容层

- 旧 `executor.py` 改为薄壳，re-export 自 `pipeline/` + `services/inbox.py`，至少跨一个阶段再清理

## 7. CLI 子命令分组

### 7.1 目录结构

```
lifebook/cli/
├── __init__.py
├── main.py                       # Click 主入口
├── _shared.py                    # 共享 utils（_mask、format helpers 等）
└── commands/
    ├── __init__.py
    ├── inbox.py                  # ingest / process / recover / retry
    ├── writer.py                 # writer-status / publish / restore / restore-published
    ├── search.py                 # search
    ├── index.py                  # index
    ├── podcast.py                # podcast / podcast-multi
    └── system.py                 # init / doctor / web / serve
```

### 7.2 命令重排

CLI 子命令将变化（README 同步更新）。示例：
- `lifebook ingest <url>` → `lifebook inbox ingest <url>`
- `lifebook process` → `lifebook inbox process`
- `lifebook recover` → `lifebook inbox recover`
- `lifebook retry` → `lifebook inbox retry`
- `lifebook search <q>` → `lifebook search <q>`（已是单词，保留）
- `lifebook publish` → `lifebook writer publish`
- `lifebook writer-status` → `lifebook writer status`
- `lifebook restore` → `lifebook writer restore`
- `lifebook restore-published` → `lifebook writer restore-published`
- `lifebook podcast <note>` → `lifebook podcast from-note <note>`
- `lifebook podcast-multi …` → `lifebook podcast multi …`
- `lifebook index` → `lifebook index`（保留）
- `lifebook web` → `lifebook system web`
- `lifebook serve` → `lifebook system serve`
- `lifebook doctor` → `lifebook system doctor`
- `lifebook init` → `lifebook system init`

### 7.3 入口配置

- `pyproject.toml` 中 `lifebook = "lifebook.cli:main"` → `"lifebook.cli.main:main"`
- 每个 commands 子模块导出一个 Click `Group`，由 `main.py` 通过 `add_command` 组装

## 8. 数据流（典型路径示例）

### 8.1 process 一份收件箱文件（CLI）

```
$ lifebook inbox process
  ↓
cli/commands/inbox.py: process()
  ↓ 构造 AppContext（一次）
services/inbox.py: InboxService.process_pending()
  ↓ 遍历 pending 文件、claim 一份
services/inbox.py: InboxService.process_one(path)
  ↓ 构造 PipelineContext
pipeline.Pipeline([FetchStage, ExtractStage, LinkStage, WriteStage]).run(ctx)
  ↓ 成功 → mark_processed；失败 → 写回错误状态
```

### 8.2 写作（飞书）

```
飞书消息 "/write 想法"
  ↓
feishu/handlers: 解析为 WriterStartRequest DTO
  ↓
services/writer.py: WriterService.start_writing(req)
  ↓ DraftStateMachine 决定下一 stage
  ↓ DraftRepository 保存 draft.json
  ↓ WriterPromptBuilder 构造 prompt
  ↓ ctx.llm_client.call(...)
  ↓ 返回 WriterStartResponse DTO
feishu transport 渲染回复
```

## 9. 错误处理

本次重构不引入新错误类型体系（P2）。但为承接 P2，约定：
- service 层方法**不**捕获底层异常做转换；让 stage / 底层模块原样抛
- adapter 层（CLI / Web / 飞书）按入口习惯做最终的异常 → 用户消息映射
- Pipeline 内 `StageError(recoverable=…)` 仅用于决定"是否写 fetch_failed 状态便于 retry"

## 10. 测试策略

### 10.1 阶段 1 契约测试（新增 `tests/contract/`）

```
tests/contract/
├── conftest.py                  # TempKnowledgeRoot / FakeLLMClient / 真实 ChromaDB（tmp dir）
├── test_inbox_lifecycle.py      # ingest → process → 笔记落盘 → status 转移
├── test_inbox_recovery.py       # processing 中断 → recover → 再 process 成功
├── test_inbox_retry.py          # fetch_failed → retry → 成功
├── test_search_after_index.py   # process 后 → index → search 命中
├── test_writer_lifecycle.py     # start → continue → publish → 写入 99-publish/
└── test_writer_restore.py       # 写到一半 → 备份 → restore → 还原
```

- LLM 用 `FakeLLMClient`（按入参返回固定结构），其他全走真实路径
- ChromaDB 走真实模型（`paraphrase-multilingual-MiniLM-L12-v2`），session-scoped fixture 复用
- 断言"外部可观测的行为"（文件、frontmatter、向量库内容、DTO 字段），不断言私有方法 / 调用顺序

### 10.2 后续阶段单测

- 阶段 3：`tests/writer/test_state.py`（状态机单测）、`tests/writer/test_repository.py`（持久化单测）、保留 e2e
- 阶段 4：`tests/pipeline/test_<stage>.py` 每个 stage 单测
- 阶段 5：契约测试**无需变更**（契约测试直接调 service 层，不通过 CLI subprocess）

### 10.3 现有测试

- 21 个飞书测试不删、不重构
- `test_writer.py` 等保留，按层级搬入子目录

## 11. 阶段路线图

每阶段独立可合并，独立可暂停。

### 阶段 1：契约测试安全网
- **新增**：`tests/contract/` 6-8 个用例
- **不改**：任何业务代码
- **完成标志**：`pytest tests/contract` 全绿
- **预估**：300-500 行新测试

### 阶段 2：抽 services 层 + AppContext
- **新增**：`lifebook/services/` 目录（含 `AppContext` / `dto.py` / 5 个 service）
- **改造**：`web/services/*` 内容**移动**到 `lifebook/services/`，原文件 re-export；`web/api/*` 改调新位置
- **改造**：CLI 与飞书入口都构造一次 `AppContext`，调 service（底层 writer/executor/store 还没拆，service 当下是"门面"）
- **完成标志**：契约测试切换为调 `services/`，全绿；三入口手测主流程
- **预期变更面**：CLI 命令文件、飞书 handler、web/api/* 路由

### 阶段 3：拆 writer/ 包
- **新增**：`lifebook/writer/{state,repository,prompt,service}.py`
- **改造**：`WriterService`（services 层）转发给 `writer/service.py`；旧 `writer.py` 变 re-export
- **改造**：测试按层级分目录
- **完成标志**：阶段 1 契约测试全绿 + 状态机单测全绿

### 阶段 4：executor → pipeline
- **新增**：`lifebook/pipeline/{stage,fetch,extract,link,write}.py`
- **改造**：`InboxService.process_one` 改用 `Pipeline`；旧 `executor.py` 薄壳
- **改造**：每个 stage 加单测
- **完成标志**：阶段 1 inbox 三个契约测试全绿；stage 单测全绿

### 阶段 5：CLI 子命令分组
- **新增**：`lifebook/cli/main.py`、`lifebook/cli/commands/*.py`
- **改造**：`pyproject.toml` 入口路径；README 命令清单同步
- **完成标志**：契约测试（不调 CLI）全绿；端到端手测三入口主命令

整体预估：1-2 周（每阶段 1-3 天）。

## 12. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 重构中途破坏外部行为 | 阶段 1 契约测试作为黑盒回归基线 |
| 旧 import 路径破坏外部脚本 | 兼容 re-export 跨一个阶段，最后统一清理 |
| writer 拆分粒度过细难维护 | 限定为 4 文件，不引入通用 FSM 框架；状态机只管转移与元数据 |
| Pipeline 抽象提前过度 | 只引入 `PipelineStage` 协议 + `PipelineContext` dataclass，不抽象出"拦截器 / 中间件" |
| services 层与现有 web/services 命名冲突 | 物理移动 + re-export 兼容，原 `web/services/` 跨阶段保留薄壳后清理 |
| 单阶段中途中断 | 每阶段独立可合，各自完成标志清晰 |

## 13. 范围外的事项（明确推迟）

- **P1-3 持久化原子性**：知识库文件 / ChromaDB / `.lifebook/vector_meta.json` 三处独立写入的一致性
- **P1-4 Provider 抽象**：当前 `llm.py` 硬编码 Anthropic SDK；`vector.py` 硬编码 ChromaDB
- **P1-5 Config 单体拆分**：按域拆分为 `WriterContext` / `PodcastContext` 等
- **P2-6 错误类型体系**：定义 `LifebookError` 体系
- **P2-6 测试结构平衡**：补 podcast / 飞书 transport 契约测试、加 `test_architecture.py`
- **P2-6 重复 markdown 解析**：`NoteSchema` dataclass 集中字段定义
- **P2-6 prompt 版本化**

这些会在 P0 完成后另起 spec。
