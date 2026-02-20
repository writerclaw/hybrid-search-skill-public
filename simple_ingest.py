#!/usr/bin/env python3
"""
Hybrid Search Simple Ingest
简化版索引更新脚本 - 仅使用关键词检索
"""

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime

# 配置
DATA_DIR = Path(__file__).parent / "data"
INDEX_FILE = DATA_DIR / "hybrid_index.json"
LOG_FILE = DATA_DIR / "ingest.log"

# 源目录（相对于脚本位置）
SOURCE_DIRS = [
    ("../../memory", "memory"),
    ("../../reviews", "review"),
    ("../../sessions", "session"),
]

def log(message):
    """记录日志"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}"
    print(log_line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line + '\n')

def extract_keywords(text, top_n=10):
    """提取关键词"""
    # 简单的关键词提取
    # 移除标点，分词
    words = re.findall(r'\b[a-zA-Z]{3,}\b|\b[\u4e00-\u9fff]{2,}\b', text.lower())
    
    # 统计词频
    from collections import Counter
    word_freq = Counter(words)
    
    # 返回最常见的词
    return [word for word, count in word_freq.most_common(top_n)]

def process_file(file_path, doc_type):
    """处理单个文件"""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        
        # 限制内容长度
        if len(content) > 50000:
            content = content[:50000] + "..."
        
        # 提取关键词
        keywords = extract_keywords(content)
        
        # 创建文档对象
        doc = {
            "id": str(file_path),
            "title": file_path.name,
            "path": str(file_path),
            "type": doc_type,
            "keywords": keywords,
            "content_preview": content[:500] if len(content) > 500 else content,
            "size": len(content),
            "updated": datetime.now().isoformat()
        }
        
        return doc
    except Exception as e:
        log(f"Error processing {file_path}: {e}")
        return None

def build_index():
    """构建索引"""
    script_dir = Path(__file__).parent
    
    all_docs = []
    
    for rel_path, doc_type in SOURCE_DIRS:
        source_dir = (script_dir / rel_path).resolve()
        
        if not source_dir.exists():
            log(f"Directory not found: {source_dir}")
            continue
        
        log(f"Scanning {doc_type}: {source_dir}")
        
        # 收集文件
        files = []
        # 递归扫描，确保 memory/archive 也能被索引
        if doc_type == "session":
            files = [f for f in source_dir.rglob("*.jsonl") if f.is_file()]
        else:
            files = [f for f in source_dir.rglob("*.md") if f.is_file()]

        # 跳过常见无关目录，避免扫描虚拟环境或缓存
        files = [f for f in files if not any(part in {".git", "venv", ".venv", "node_modules", "__pycache__"} for part in f.parts)]
        
        log(f"  Found {len(files)} files")
        
        # 处理文件
        for file_path in files:
            doc = process_file(file_path, doc_type)
            if doc:
                all_docs.append(doc)
    
    log(f"Total documents indexed: {len(all_docs)}")
    
    # 保存索引
    index_data = {
        "version": "1.0",
        "created": datetime.now().isoformat(),
        "document_count": len(all_docs),
        "index_type": "keyword",
        "documents": all_docs
    }
    
    # 确保数据目录存在
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    with open(INDEX_FILE, 'w', encoding='utf-8') as f:
        json.dump(index_data, f, ensure_ascii=False, indent=2)
    
    log(f"Index saved to {INDEX_FILE}")
    
    return len(all_docs)

def main():
    """主函数"""
    try:
        # 确保数据目录存在
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        log("="*50)
        log("Starting Hybrid Search Index Update")
        log("="*50)
        
        doc_count = build_index()
        
        log("="*50)
        log(f"Index update completed: {doc_count} documents")
        log("="*50)
        
        return 0
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(main())
