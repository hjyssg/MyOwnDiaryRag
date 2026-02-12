#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脚本入口（兼容迁移）：转发到项目根 build_summaries.py"""

import runpy
from pathlib import Path


def main():
    root_script = Path(__file__).resolve().parent.parent / "build_summaries.py"
    runpy.run_path(str(root_script), run_name="__main__")


if __name__ == "__main__":
    main()
