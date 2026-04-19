# LifeBook 向量索引开发计划

## 当前状态（2026-04-19）

### ✅ 已完成
1. **vector.py** — VectorIndex 类（ChromaDB + sentence-transformers 封装）
   - 完整 API：upsert/upsert_batch/delete/search/count/has
   - SearchResult dataclass
   - 单元测试：12 个测试全部通过

2. **indexer.py** — 增量更新服务
   - 后台线程定时轮询（默认 5 分钟）
   - 增量检测（文件 mtime 对比）
   - 元数据持久化（.lifebook/vector_meta.json）
   - 单元测试：10 个测试全部通过

3. **依赖管理**
   - pyproject.toml 已添加 chromadb 和 sentence-transformers
   - 项目 venv 已安装

4. **设计文档**
   - VECTOR_INDEX_DESIGN.md（架构、技术栈、API、部署）

### 🔄 进行中
1. **飞书集成** — `/update-index` 和 `/search` 命令
2. **CLI 集成** — `lifebook index` 和 `lifebook search` 命令
3. **文档** — 用户指南和部署说明

## 剩余任务

### 优先级 1：飞书 slash 命令集成
- [ ] 在 `feishu.py` 中添加 `/update-index` 命令处理
  - 调用 `indexer.incremental_update()`
  - 返回统计信息（upserted/deleted/unchanged/errors）
- [ ] 在 `feishu.py` 中添加 `/search <query>` 命令处理
  - 调用 `vector.search(query, n_results=5)`
  - 格式化搜索结果（标题、摘要、距离、链接）
- [ ] 更新飞书机器人启动逻辑：自动启动 Indexer 后台线程

### 优先级 2：CLI 命令集成
- [ ] 在 `cli.py` 中添加 `lifebook index` 命令
  - 选项：`--full` 全量重建
  - 选项：`--interval` 设置轮询间隔
  - 输出统计信息
- [ ] 在 `cli.py` 中添加 `lifebook search` 命令
  - 参数：查询字符串
  - 选项：`--category` 按目录过滤
  - 选项：`--limit` 结果数量
  - 表格化输出
- [ ] 更新 CLI 主入口：启动时自动运行 Indexer（后台模式）

### 优先级 3：文档与部署
- [ ] 用户指南：如何启用向量索引
- [ ] 部署说明：首次运行步骤
- [ ] 故障排除：常见问题
- [ ] 性能调优建议

### 优先级 4：增强功能（可选）
- [ ] 搜索结果缓存
- [ ] 索引进度显示
- [ ] 按 tag 过滤搜索
- [ ] 混合检索（向量 + 关键词）

## 测试计划

### 单元测试（已完成）
- `tests/test_vector.py` — 12 tests
- `tests/test_indexer.py` — 10 tests

### 集成测试（待进行）
1. **真实索引测试**
   - 使用真实 topic notes 数据
   - 验证端到端索引流程
   - 验证搜索质量

2. **飞书命令测试**
   - 模拟飞书消息
   - 验证命令响应格式

3. **CLI 命令测试**
   - 测试 `lifebook index` 和 `lifebook search`
   - 验证输出格式

### 性能测试（可选）
- 索引 1000 篇笔记的耗时
- 搜索延迟（P95）
- 内存占用

## 部署检查清单

### 首次部署
1. [ ] 安装依赖：`pip install chromadb sentence-transformers`
2. [ ] 下载 embedding 模型（自动，~470MB）
3. [ ] 运行全量索引：`lifebook index --full`
4. [ ] 验证搜索：`lifebook search "测试查询"`
5. [ ] 启动飞书机器人：`lifebook feishu`

### 日常运维
- 索引自动更新（后台线程）
- 日志监控：`logs/lifebook.log`
- 磁盘空间监控：`.lifebook/vector_store/`

## 风险与缓解

### 技术风险
1. **模型下载失败** — 国内网络可能慢
   - 缓解：使用镜像源，提供离线包选项
2. **内存占用高** — sentence-transformers 模型 ~500MB
   - 缓解：使用更小模型，支持按需加载
3. **索引性能** — 大量文件时首次索引慢
   - 缓解：分批处理，进度显示

### 功能风险
1. **搜索质量不佳** — embedding 模型不适合某些领域
   - 缓解：支持多模型切换，混合检索
2. **增量更新遗漏** — mtime 不可靠
   - 缓解：增加 content hash 校验

## 时间估算

| 任务 | 估算工时 | 优先级 |
|------|----------|--------|
| 飞书集成 | 2-3 小时 | P1 |
| CLI 集成 | 2-3 小时 | P1 |
| 文档 | 1-2 小时 | P2 |
| 集成测试 | 2-3 小时 | P2 |
| 增强功能 | 4-6 小时 | P4 |

**总计**：7-11 小时（P1+P2）

---

**更新记录**
- 2026-04-19：创建文档，记录已完成模块
- 2026-04-19：vector.py 和 indexer.py 开发完成，测试通过

**负责人**：二毛
