#!/bin/bash
# Hybrid Search Cron Ingest Script
# 更新索引并记录日志

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
LOG_FILE="$DATA_DIR/ingest.log"
INDEX_FILE="$DATA_DIR/hybrid_index.json"

# 加载环境变量（从 systemd 服务或用户配置）
if [ -f ~/.bashrc ]; then
    source ~/.bashrc 2>/dev/null || true
fi
# 确保关键环境变量存在
export DASHSCOPE_EMBEDDING_API_KEY="${DASHSCOPE_EMBEDDING_API_KEY:-}"
export DASHSCOPE_BASE_URL="${DASHSCOPE_BASE_URL:-https://dashscope.aliyuncs.com/compatible-mode/v1}"

# 确保数据目录存在
mkdir -p "$DATA_DIR"

# 记录开始时间
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting hybrid search index update..." >> "$LOG_FILE"

# 检查 Python 脚本是否存在（优先使用简单版）
PYTHON_SCRIPT="$SCRIPT_DIR/simple_ingest.py"
if [ ! -f "$PYTHON_SCRIPT" ]; then
    PYTHON_SCRIPT="$SCRIPT_DIR/ingest.py"
fi

if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: No ingest script found" >> "$LOG_FILE"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Using script: $PYTHON_SCRIPT" >> "$LOG_FILE"

# 运行 Python 索引脚本
cd "$SCRIPT_DIR" && python3 "$PYTHON_SCRIPT" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

# 记录结果
if [ $EXIT_CODE -eq 0 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Index update completed successfully" >> "$LOG_FILE"
    # 输出文件信息
    if [ -f "$INDEX_FILE" ]; then
        INDEX_SIZE=$(stat -c%s "$INDEX_FILE" 2>/dev/null || stat -f%z "$INDEX_FILE" 2>/dev/null || echo "unknown")
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Index file size: $INDEX_SIZE bytes" >> "$LOG_FILE"
    fi
    echo "OK"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Index update failed with exit code $EXIT_CODE" >> "$LOG_FILE"
    echo "ERROR"
    exit $EXIT_CODE
fi
