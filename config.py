#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从项目根目录的 .env 读取配置。"""

import os
from pathlib import Path


def load_env():
    """加载 .env 文件"""
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        raise FileNotFoundError(
            f".env 文件不存在！\n"
            f"请复制 .env.example 为 .env 并配置路径:\n"
            f"  cp .env.example .env\n"
            f"然后编辑 .env 文件设置正确的路径"
        )
    
    env_vars = {}
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    
    return env_vars

def get_database_path() -> Path:
    """读取数据库路径；Web 等只读功能不要求配置日记目录。"""
    database_path = os.environ.get('DATABASE_PATH')
    if not database_path:
        env = load_env()
        database_path = env.get('DATABASE_PATH')
    if not database_path:
        raise ValueError("DATABASE_PATH 未在 .env 中配置")

    return Path(database_path).expanduser()


def get_diary_base_path() -> Path:
    """读取并校验原始日记目录（仅导入脚本需要）。"""
    env = load_env()
    diary_base_path = env.get('DIARY_BASE_PATH')
    if not diary_base_path:
        raise ValueError("DIARY_BASE_PATH 未在 .env 中配置")

    diary_base_path = Path(diary_base_path).expanduser()
    if not diary_base_path.exists():
        raise FileNotFoundError(f"日记目录不存在: {diary_base_path}")
    return diary_base_path


def get_config():
    """获取导入脚本所需的完整路径配置。"""
    return {
        'diary_base_path': get_diary_base_path(),
        'database_path': get_database_path(),
    }


# ---------------- 情绪标签集（batch 与 Web 共用同一份配置） ----------------
# 默认 8 类：由 .env 的 EMOTION_LABELS 覆盖（逗号/中文逗号分隔，保序、去重）。
# 约定：最后一项是"无法归类"的兜底标签，改标签集会让情绪重新计算（摘要不受影响）。
DEFAULT_EMOTION_LABELS = ("快乐", "平淡", "悲伤", "生气", "焦虑", "疲惫", "期待", "其他")

EMOTION_LABEL_SEPARATORS = (",", "，", "、", ";", "；")


def split_emotion_labels(value):
    """把 ``EMOTION_LABELS`` 的原始字符串切成有序去重的标签列表（可被测试直接调用）。"""
    text = str(value or "")
    for separator in EMOTION_LABEL_SEPARATORS:
        text = text.replace(separator, ",")
    labels = []
    for item in text.split(","):
        label = item.strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def get_emotion_labels():
    """情绪标签集：优先读 .env，读不到（缺文件/未配置）时用默认 8 类。

    这里**不抛异常**：Web 的 /api/summaries 需要它来校验 emotion 参数，
    批量总结也要用它来构造 Prompt 与算法指纹；没有 .env 时退回默认值即可。
    """
    configured_labels = os.environ.get("EMOTION_LABELS")
    if configured_labels is None:
        try:
            configured_labels = load_env().get("EMOTION_LABELS")
        except Exception:
            configured_labels = None
    labels = split_emotion_labels(configured_labels)
    return labels or list(DEFAULT_EMOTION_LABELS)

