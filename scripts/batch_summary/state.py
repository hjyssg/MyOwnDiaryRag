#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日志与公共小工具

断点续跑的主状态不在文件里，而在 SQLite 的 ``entry_summaries`` 表
（见 :mod:`summary_database`）：重跑时按「日期 + 类型 + 正文哈希 + 算法指纹」
判断能否复用，所以不再需要任何状态文件。

本模块只剩三件小事：

* :func:`setup_logging` —— 配置日志（**只输出到控制台**，不写日志文件）；
* :func:`now_iso` —— 统一的时间戳格式；
* :func:`has_summary` —— 判断一条记录里有没有可用摘要。

产物只有一个「中途预览.md」（见 :mod:`scripts.batch_summary.render`），
不再生成 summaries.json / progress.json / 运行状态.txt / 待复核清单 / 日志文件。
"""

import logging
from datetime import datetime
from typing import Dict

LOGGER_NAME = "scripts.batch_summary"


def now_iso() -> str:
    """当前时间（本地时区，精确到秒）"""
    return datetime.now().isoformat(timespec="seconds")


def has_summary(record: Dict) -> bool:
    """记录里是否有可用摘要"""
    return bool(str((record or {}).get("summary") or "").strip())


def setup_logging(quiet: bool = False, level=logging.INFO) -> None:
    """配置日志：只挂控制台 handler（重复调用先清掉旧 handler）

    ``quiet=True``（``--quiet``）时不挂 handler，只保留 WARNING 以上的
    ``logging.lastResort`` 输出；无论如何都不写日志文件。
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    if not quiet:
        console = logging.StreamHandler()
        console.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
        )
        logger.addHandler(console)
