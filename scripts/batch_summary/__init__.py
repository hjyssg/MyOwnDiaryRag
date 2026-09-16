"""日记批量总结：用本地 LM Studio 模型逐篇阅读 SQLite 中的日记，为每一篇写一段摘要。

不做任何"重要性判断"：每一篇日记都会得到一段摘要，没有被跳过的内容，
也没有事件抽取、日期猜测与跨天合并。

包内模块统一使用绝对导入（``scripts.batch_summary.xxx``），
因此这里确保项目根目录在 sys.path 中，使以下两种运行方式都可用：

    python scripts/batch_summary/main.py --all
    python -m scripts.batch_summary.main --all
"""

import sys
from pathlib import Path

_ROOT_DIR = Path(__file__).resolve().parents[2]
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

__all__ = ["config", "dal", "llm", "summary", "render", "state", "main"]
