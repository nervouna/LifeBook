# LifeBook 向量索引模块设计文档

## 概述

为 LifeBook 个人知识库添加语义搜索能力，基于本地向量数据库（ChromaDB）和本地 embedding 模型（sentence-transformers），实现增量索引和实时检索。

## 架构

### 模块结构
```
lifebook/
├── vector.py           # 向量索引核心逻辑（ChromaDB + sentence-transformers 封装）
├── indexer.py          # 增量更新服务（后台线程 + 定时轮询）
├── feishu.py           # 飞书机器人（新增 /update-index, /search 命令）
└── cli.py              # CLI（新增 lifebook index, lifebook search 命令）
```

### 数据流
1. **索引构建**：扫描 `20-topics/` 目录下的 Markdown 笔记
2. **文档提取**：提取标题、摘要、要点、正文，拼接为索引文本
3. **向量化**：使用 sentence-transformers 模型生成 embedding
4. **存储**：ChromaDB 持久化存储向量 + 元数据
5. **检索**：用户查询 → embedding → 相似度搜索 → 返回相关笔记

### 增量更新机制
- **状态跟踪**：`.lifebook/vector_meta.json` 记录已索引文件的 mtime
- **轮询间隔**：默认 5 分钟（可配置）
- **触发方式**：
  - 定时轮询（后台线程）
  - 飞书 slash 命令 `/update-index`
  - CLI 命令 `lifebook index --full`（全量重建）
- **变更检测**：对比文件 mtime，新增/修改 → upsert，删除 → delete

## 技术栈

### 核心依赖
- **chromadb** >= 0.5.0：本地向量数据库
- **sentence-transformers** >= 2.7.0：本地 embedding 模型

### 模型选择
- **paraphrase-multilingual-MiniLM-L12-v2**（默认）
  - 支持中英文
  - 模型大小适中（~470MB）
  - 在语义相似度任务上表现良好
  - 适合 CPU 推理

### 存储路径
```
~/Documents/Knowledge/.lifebook/
├── vector_store/          # ChromaDB 数据目录
└── vector_meta.json       # 索引元数据（文件 mtime 映射）
```

## API 设计

### VectorIndex 类（vector.py）
```python
class VectorIndex:
    def __init__(self, persist_dir: Path, model_name: str = "...")
    def upsert(self, doc_id: str, text: str, metadata: dict) -> None
    def upsert_batch(self, docs: list[dict]) -> None
    def delete(self, doc_id: str) -> None
    def search(self, query: str, n_results: int = 5, where: dict = None) -> list[SearchResult]
    def count(self) -> int
    def has(self, doc_id: str) -> bool

@dataclass
class SearchResult:
    doc_id: str
    distance: float
    metadata: dict[str, Any]
    text: str
```

### Indexer 类（indexer.py）
```python
class Indexer:
    def __init__(self, cfg: Config, interval: int = 300)
    def start(self) -> None                    # 启动后台线程
    def stop(self) -> None                     # 停止后台线程
    def incremental_update(self) -> dict       # 增量更新，返回统计
    def full_rebuild(self) -> dict             # 全量重建
```

## 集成点

### 飞书机器人（feishu.py）
新增 slash 命令：
- `/update-index`：立即触发增量索引更新
- `/search <query>`：语义搜索，返回最相关的 5 条笔记

### CLI（cli.py）
新增命令：
- `lifebook index [--full]`：手动触发索引更新（默认增量，--full 全量重建）
- `lifebook search <query> [--category CATEGORY]`：命令行搜索

### 主程序启动
LifeBook 启动时（`feishu.py` 或 `cli.py` 的 `main`）自动启动 Indexer 后台线程。

## 部署与运维

### 首次部署
1. 安装依赖：`pip install chromadb sentence-transformers`
2. 首次运行会自动下载 embedding 模型（~470MB）
3. 初始索引构建：`lifebook index --full`

### 监控
- 日志级别：INFO 记录索引统计，DEBUG 记录详细操作
- 索引状态：`.lifebook/vector_meta.json` 可查看已索引文件列表
- 向量库大小：`lifebook search` 返回文档数

### 性能考虑
- **内存**：sentence-transformers 模型加载后常驻内存
- **磁盘**：ChromaDB 存储向量和元数据，每文档约 1-10KB
- **CPU**：embedding 计算为 CPU 密集型，批量处理优化

## 测试策略

### 单元测试
- `tests/test_vector.py`：mock ChromaDB 和 sentence-transformers
- `tests/test_indexer.py`：mock 文件系统和 VectorIndex

### 集成测试
- 真实 ChromaDB + 小型测试数据集
- 验证端到端索引和检索流程

### 测试命令
```bash
cd /Users/damao/Projects/LifeBook
.venv/bin/python -m pytest tests/test_vector.py tests/test_indexer.py -v
```

## 后续扩展

### 短期
1. 支持按 category/tag 过滤搜索
2. 搜索结果格式化（飞书卡片/CLI 表格）
3. 索引性能监控（耗时统计）

### 中期
1. 多模型支持（可配置 embedding 模型）
2. 混合检索（向量 + 关键词）
3. 增量索引优化（仅索引新文件，跳过未修改）

### 长期
1. 分布式索引（多机部署）
2. 实时索引（文件系统监听替代轮询）
3. 检索质量评估（人工反馈循环）

---

**文档版本**：v1.0  
**最后更新**：2026-04-19  
**维护者**：二毛（毛哥的工作搭档）
