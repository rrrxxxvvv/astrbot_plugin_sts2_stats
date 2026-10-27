from __future__ import annotations

import json
from pathlib import Path

from astrbot.api import logger


def load_json(path: Path, default):
    """从 JSON 文件读取数据，文件不存在或解析失败时返回 default。"""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[sts2_stats] 读取 {path} 失败: {e}")
    return default


def save_json(path: Path, data) -> None:
    """将数据序列化写入 JSON 文件。"""
    try:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"[sts2_stats] 写入 {path} 失败: {e}")
