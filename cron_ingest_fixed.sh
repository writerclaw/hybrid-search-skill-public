#!/bin/bash
# Hybrid Search - Fixed Cron Ingestion Script
# 修复版：全量扫描模式，确保所有文件都被索引

SCRIPT_DIR="/home/writer/.openclaw/workspace/tools/hybrid_search"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/ingest.log"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python"
CLI_PY="$SCRIPT_DIR/cli.py"
DB_PATH="$SCRIPT_DIR/data/index.db"

# 加载环境变量
ENV_FILE="/home/writer/.openclaw/secrets/hybrid_search.env"
if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
fi

mkdir -p "$LOG_DIR"

echo "========================================" >> "$LOG_FILE"
echo "=== Ingestion started at $(date) ===" >> "$LOG_FILE"
echo "========================================" >> "$LOG_FILE"

# 检查环境
if [ ! -f "$VENV_PYTHON" ]; then
    echo "[ERROR] Virtual environment not found at $VENV_PYTHON" >> "$LOG_FILE"
    exit 1
fi
if [ ! -f "$CLI_PY" ]; then
    echo "[ERROR] CLI script not found at $CLI_PY" >> "$LOG_FILE"
    exit 1
fi

cd "$SCRIPT_DIR"

# ===== 关键修复：全量扫描，而非仅最近1天 =====
echo "" >> "$LOG_FILE"
echo "[INFO] Mode: FULL SCAN (scanning all sources, not just recent)" >> "$LOG_FILE"
echo "[INFO] Sources: notes, summary, logs" >> "$LOG_FILE"

# 统计当前索引状态
BEFORE_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM docs;" 2>/dev/null || echo "0")
echo "[INFO] Documents before: $BEFORE_COUNT" >> "$LOG_FILE"

# 执行全量扫描和索引（--full-scan 替代 --mode full）
$VENV_PYTHON "$CLI_PY" ingest \
  --sources notes,summary,logs \
  --full-scan \
  >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

# 统计更新后状态
AFTER_COUNT=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM docs;" 2>/dev/null || echo "0")
ADDED=$((AFTER_COUNT - BEFORE_COUNT))

echo "" >> "$LOG_FILE"
echo "[INFO] Documents after: $AFTER_COUNT" >> "$LOG_FILE"
echo "[INFO] New documents added: $ADDED" >> "$LOG_FILE"

if [ $EXIT_CODE -eq 0 ]; then
    echo "[SUCCESS] Ingestion completed at $(date)" >> "$LOG_FILE"
else
    echo "[WARNING] Ingestion exited with code $EXIT_CODE at $(date)" >> "$LOG_FILE"
    echo "[WARNING] Some documents may not have been indexed" >> "$LOG_FILE"
fi

echo "========================================" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"

exit $EXIT_CODE