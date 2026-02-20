# Hybrid Search Skill - 混合检索技能

OpenClaw 混合检索系统 - 向量检索 + 全文检索融合

## 功能特性

- ✅ 向量检索（DashScope text-embedding-v4）
- ✅ 全文检索（关键词匹配）
- ✅ 混合融合（综合排序）
- ✅ 记忆管理（MEMORY.md + daily memory）
- ✅ 定时更新（cron 每小时自动更新）

## 文件结构

```
hybrid-search/
├── cli.py              # 命令行接口
├── config.yaml         # 配置文件
├── cron_ingest.sh      # 定时索引更新
├── db.py               # 数据库操作
├── embed.py            # 向量嵌入
├── embed_local.py      # 本地嵌入
├── hybrid_search.py    # 混合检索核心
├── ingest.py           # 索引构建
├── ingest_memory.py    # 记忆索引
├── quick_test.py       # 快速测试
├── search.py           # 搜索功能
├── simple_ingest.py    # 简单索引
├── simple_search.py    # 简单搜索
└── emergency_reindex.sh # 紧急重建索引
```

## 安装使用

1. 配置 `config.yaml` 中的 API Key 和路径
2. 运行 `python3 ingest.py` 构建索引
3. 使用 `python3 cli.py search "关键词"` 搜索

## 更新日志

**2026-02-18**:
- 优化索引构建：增量更新 + 每日全量
- 修复 API Key 管理：使用环境变量
- 新增紧急重建索引脚本

**2026-02-15**:
- 初始版本发布
- 支持向量 + 关键词混合检索

## 依赖

- Python 3.12+
- DashScope API
- SQLite3

## 许可证

MIT License
