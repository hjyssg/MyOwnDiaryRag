#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置加载模块
从 .env 文件读取日记路径和数据库路径
"""

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

def get_config():
    """获取配置"""
    env = load_env()
    
    diary_base_path = env.get('DIARY_BASE_PATH')
    database_path = env.get('DATABASE_PATH')
    lm_studio_url = env.get('LM_STUDIO_URL', 'http://127.0.0.1:1234/v1/chat/completions')
    
    if not diary_base_path:
        raise ValueError("DIARY_BASE_PATH 未在 .env 中配置")
    if not database_path:
        raise ValueError("DATABASE_PATH 未在 .env 中配置")
    
    diary_base_path = Path(diary_base_path)
    database_path = Path(database_path)
    
    if not diary_base_path.exists():
        raise FileNotFoundError(f"日记目录不存在: {diary_base_path}")
    
    return {
        'diary_base_path': diary_base_path,
        'database_path': database_path,
        'lm_studio_url': lm_studio_url
    }
