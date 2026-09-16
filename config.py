#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从项目根目录的 .env 读取配置。"""

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
