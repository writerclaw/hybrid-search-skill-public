#!/bin/bash
# 紧急修复：全量重建索引
# 用途：解决当前索引覆盖率仅4%的问题

SCRIPT_DIR="/home/writer/.openclaw/workspace/tools/hybrid_search"
LOG_FILE="$SCRIPT_DIR/logs/emergency_reindex.log"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"
CLI_PY="$SCRIPT_DIR/cli.py"

mkdir -p "$SCRIPT_DIR/logs"

echo "========================================" | tee -a "$LOG_FILE"
echo "紧急索引重建开始: $(date)" | tee -a "$LOG_FILE"
echo "========================================" | tee -a "$LOG_FILE"

# 统计重建前状态
echo "" | tee -a "$LOG_FILE"
echo "重建前统计：" | tee -a "$LOG_FILE"
echo "- 记忆文件数: $(find ~/.openclaw/workspace/memory/ -name '*.md' | wc -l)" | tee -a "$LOG_FILE"
echo "- 笔记文件数: $(find ~/.openclaw/workspace/notes/ -name '*.md' | wc -l)" | tee -a "$LOG_FILE"
echo "- 当前索引数: $(sqlite3 $SCRIPT_DIR/data/index.db 'SELECT COUNT(*) FROM docs;' 2>/dev/null || echo 0)" | tee -a "$LOG_FILE"

# 备份当前索引
echo "" | tee -a "$LOG_FILE"
echo "备份当前索引..." | tee -a "$LOG_FILE"
BACKUP_DIR="$SCRIPT_DIR/data/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r "$SCRIPT_DIR/data/"*.index "$SCRIPT_DIR/data/"*.db "$BACKUP_DIR/" 2>/dev/null || true
echo "备份完成: $BACKUP_DIR" | tee -a "$LOG_FILE"

# 方法A：通过CLI工具重建（推荐）
echo "" | tee -a "$LOG_FILE"
echo "执行全量索引重建..." | tee -a "$LOG_FILE"
echo "（这可能需要几分钟，取决于文件数量）" | tee -a "$LOG_FILE"

cd "$SCRIPT_DIR"

# 使用强制重建模式（--full-scan 替代 --mode full）
$VENV_PYTHON "$CLI_PY" ingest \
  --sources notes,summary,logs \
  --full-scan 2>&1 | tee -a "$LOG_FILE"

REINDEX_EXIT=${PIPESTATUS[0]}

# 统计重建后状态
echo "" | tee -a "$LOG_FILE"
echo "重建后统计：" | tee -a "$LOG_FILE"
NEW_COUNT=$(sqlite3 "$SCRIPT_DIR/data/index.db" 'SELECT COUNT(*) FROM docs;' 2>/dev/null || echo 0)
echo "- 新索引数: $NEW_COUNT" | tee -a "$LOG_FILE"
echo "- 新增: $((NEW_COUNT - $(sqlite3 $SCRIPT_DIR/data/index.db 'SELECT COUNT(*) FROM docs;' 2>/dev/null || echo 0)))" | tee -a "$LOG_FILE"

if [ $REINDEX_EXIT -eq 0 ]; then
    echo "" | tee -a "$LOG_FILE"
    echo "✅ 全量索引重建成功！" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
    exit 0
else
    echo "" | tee -a "$LOG_FILE"
    echo "⚠️  索引重建遇到问题（退出码: $REINDEX_EXIT）" | tee -a "$LOG_FILE"
    echo "可从日志排查问题" | tee -a "$LOG_FILE"
    echo "========================================" | tee -a "$LOG_FILE"
    exit 1
fi