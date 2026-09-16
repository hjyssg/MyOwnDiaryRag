#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日记批量总结 进度看板（只读，不修改任何文件）

注意：主程序（``main.py --all``）运行时**自己**就会持续打印同样的状态块，
所以本工具只在"想单独看一眼 / 想让画面滚动刷新 / 想回看某次运行"时才需要。

用法（Windows CMD / PowerShell 均可）::

    python scripts/batch_summary/status.py               # 看最近一次运行
    python scripts/batch_summary/status.py --watch 5     # 每 5 秒刷新（Ctrl+C 退出）
    python scripts/batch_summary/status.py --list        # 列出历史运行

数据来源（都是主程序写的，只读）：

* ``<运行目录>/progress.json``       实时进度快照（每处理一篇更新一次）
* ``<运行目录>/运行状态.txt``         最新状态块（直接用编辑器打开也能看）
* ``<输出根目录>/summary_state.json``  断点状态（跨运行共享）

状态块渲染复用 :func:`scripts.batch_summary.progress.format_blocks`，
与主程序心跳格式完全一致（一处改，两处同步）。
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.batch_summary import config as bs_config  # noqa: E402
from scripts.batch_summary import progress as progress_mod  # noqa: E402

STALE_SECONDS = 120        # 快照超过这么久没更新 -> 视为可能已中断/空闲

# 兼容旧引用（实现已统一到 progress.py）
human_duration = progress_mod.human_duration
progress_bar = progress_mod.progress_bar


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def snapshot_age_seconds(payload) -> float:
    stamp = (payload or {}).get("updated_at")
    if not stamp:
        return 1e9
    try:
        return (datetime.now() - datetime.fromisoformat(stamp)).total_seconds()
    except ValueError:
        return 1e9


def find_run_dir(base_dir: Path) -> Path:
    """最近一次运行的目录

    优先 ``output/`` 下的时间戳子目录（新→旧，且已有 ``progress.json`` 的），
    都没有时退回 ``output/`` 本身（``--flat-output`` 或旧版本直接写在根目录的情况）。
    """
    runs = bs_config.list_run_dirs(base_dir)
    for candidate in runs:
        if (candidate / "progress.json").exists():
            return candidate
    return runs[0] if runs else base_dir


def render_report(run_dir: Path, *, base_dir: Optional[Path] = None) -> str:
    """生成看板文本（纯函数，便于测试；格式与主程序心跳完全一致）"""
    run_dir = Path(run_dir)
    base_dir = Path(base_dir) if base_dir else run_dir
    payload = load_json(run_dir / "progress.json")
    lines = []

    if payload is None:
        lines.append("[提示] 还没有 progress.json：这个运行目录里没有可读的进度快照。")
        lines.append("       请先运行（新版才会写进度快照；断点续跑不会重跑已处理条目）：")
        lines.append("         python scripts/batch_summary/main.py --all --year 2025")
        state = load_json(base_dir / bs_config.STATE_FILE_NAME)
        if state:
            results = list((state.get("results") or {}).values())
            with_summary = sum(1 for r in results if str(r.get("summary") or "").strip())
            lines.append("")
            lines.append(
                f"（断点状态里已有 {len(results)} 篇：有摘要 {with_summary} / 空摘要 "
                f"{len(results) - with_summary}）"
            )
        return "\n".join(lines)

    age = snapshot_age_seconds(payload)
    snapshot = dict(payload)
    if str(payload.get("phase")) == "done":
        snapshot["hint"] = f"任务已完成（快照 {human_duration(age)} 前更新）"
    elif age > STALE_SECONDS:
        snapshot["notice"] = (
            f"快照已有 {human_duration(age)} 未更新，任务可能已中断或空闲；"
            "重跑同一命令即可续跑"
        )
    else:
        snapshot["hint"] = f"快照 {human_duration(age)} 前更新（任务应该还在跑）"

    lines.append(progress_mod.format_blocks(snapshot))
    lines.append("-" * 58)
    lines.append(f"运行目录  : {run_dir}")
    status_file = run_dir / bs_config.STATUS_FILE_NAME
    if status_file.exists():
        lines.append(f"状态文件  : {status_file}  ← 直接用编辑器打开也能看")
    lines.append(f"断点状态  : {base_dir / bs_config.STATE_FILE_NAME}  ← 跨运行共享")
    for candidate in (run_dir, base_dir):
        if (candidate / "中途预览.md").exists():
            lines.append(f"中途产物  : {candidate / '中途预览.md'} ← 已生成的部分目录")
    if (run_dir / bs_config.PENDING_MD_NAME).exists():
        lines.append(f"           {bs_config.PENDING_MD_NAME} ← 未产出摘要的日记原文清单")
    return "\n".join(lines)


def format_run_list(base_dir: Path) -> str:
    """列出历史运行目录（新→旧）及各自最后状态"""
    runs = bs_config.list_run_dirs(base_dir)
    if not runs:
        return f"[提示] {base_dir} 下还没有带时间戳的运行目录（每次 --all 会新建一个）。"
    lines = [f"历史运行目录（新→旧）: {base_dir}", ""]
    for run in runs:
        payload = load_json(run / "progress.json")
        if not payload:
            note = "（还没有 progress.json）"
        else:
            note = (
                f"{payload.get('phase_label') or payload.get('phase') or '?'} | "
                f"{payload.get('index', 0)}/{payload.get('total', 0)} 篇 | "
                f"有摘要 {payload.get('ok', 0)} 空摘要 {payload.get('empty', 0)} "
                f"失败 {payload.get('failed', 0)} | 更新于 {payload.get('updated_at', '')}"
            )
        lines.append(f"  {run.name}  {note}")
    lines.append("")
    lines.append("查看某次运行: python scripts/batch_summary/status.py --run <目录名>")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python scripts/batch_summary/status.py",
        description="日记批量总结 进度看板（只读，不修改任何文件）",
    )
    parser.add_argument(
        "--output-dir",
        help="输出根目录（默认 scripts/batch_summary/output）；会自动选择其中最近一次运行",
    )
    parser.add_argument("--run", help="指定某次运行的目录名或路径，如 --run 250916101830")
    parser.add_argument("--list", action="store_true", help="列出历史运行目录后退出")
    parser.add_argument(
        "--watch", type=float, metavar="SECONDS",
        help="循环刷新，如 --watch 5（Ctrl+C 退出）；默认自动跟随最新一次运行",
    )
    return parser


def clear_screen():
    """Windows CMD 用 cls，其它平台用 ANSI 转义，避免 CMD 里出现乱码"""
    if os.name == "nt":
        os.system("cls")
    else:
        print("\033[H\033[J", end="")


def resolve_run_dir(args, base_dir: Path) -> Path:
    """--run 指定目录；否则取最近一次运行"""
    if not args.run:
        return find_run_dir(base_dir)
    target = Path(args.run).expanduser()
    if not target.is_absolute():
        target = base_dir / target
    return target.resolve()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    base_dir = (
        Path(args.output_dir).expanduser().resolve() if args.output_dir else bs_config.OUTPUT_DIR
    )

    if args.list:
        print(format_run_list(base_dir))
        return 0

    run_dir = resolve_run_dir(args, base_dir)

    if not args.watch:
        print(render_report(run_dir, base_dir=base_dir))
        return 0

    interval = max(float(args.watch), 0.5)
    try:
        while True:
            if not args.run:                      # 新任务启动后自动跟到最新一次运行
                run_dir = find_run_dir(base_dir)
            clear_screen()
            print(render_report(run_dir, base_dir=base_dir), flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
