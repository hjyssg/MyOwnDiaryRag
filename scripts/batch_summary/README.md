# 日记批量总结（batch_summary）

> 🏠 返回 [项目主 README](../../README.md) ｜ 兄弟模块：[Web 浏览系统](../../webapp/README.md)

用**本地 LM Studio 模型**逐篇阅读 SQLite 里的日记，为**每一篇**写一段摘要，
生成按年份排列的 `日记总结.md`。全程在本机运行，数据库**只读**，原始日记不修改、不删除。

设计取向：**不让本地模型做判断**。旧版（年度日记回顾）要求模型判断"哪些内容重要"，
本地小模型判断力不够时会大量返回"无重要事件"，把整段日常直接丢掉；现在改成
"每一篇都写摘要"，模型只负责把原文概述成一段话，哪些内容值得回看由你自己看的时候决定。
因此这里没有事件抽取、重要性打分、标题长度限制，也没有跨天合并与相似度去重。

## 目录

- [1. 准备 LM Studio](#1-准备-lm-studio)
- [2. 配置（项目根目录 `.env`，追加即可）](#2-配置项目根目录-env追加即可)
- [3. 运行](#3-运行)
- [4. 产物](#4-产物)
- [5. 断点续跑与失败处理](#5-断点续跑与失败处理)
- [6. 模型输出如何被清洗（Python 负责，不依赖模型）](#6-模型输出如何被清洗python-负责不依赖模型)
- [7. 调 Prompt / 调参数](#7-调-prompt--调参数)
- [8. 性能与范围](#8-性能与范围)
- [9. 测试](#9-测试)

```
scripts/batch_summary/
├── main.py        入口（命令解析 + 流程串联）
├── config.py      配置（复用根 config.py 读 .env，并补充 LLM 与心跳配置）
├── dal.py         数据访问适配（复用根 database.py 的只读 Database，零 SQL）
├── llm.py         LM Studio 调用（本地地址强校验、超时、重试、限速）
├── summary.py     Prompt 装载 + 模型输出清洗（把回复整理成"一行摘要"）
├── render.py      Markdown 生成（按年目录 + 中途预览 + 待复核清单）
├── state.py       断点续跑状态（原子写入）+ 日志
├── progress.py    实时进度：心跳状态块 + progress.json + 运行状态.txt
├── status.py      进度看板（只读；主程序自己也会打印同样的状态块）
├── prompts/diary_summary_prompt.txt   LLM Prompt 独立配置
└── output/
    ├── summary_state.json  断点状态（跨运行共享，重跑续跑靠它）
    └── 250916104031/       每次运行一个 YYMMDDHHMMSS 子目录（历史互不覆盖）
```

## 1. 准备 LM Studio

1. 在 LM Studio 中加载对话模型（例如 Qwen3.5-9B）并启动本地服务（默认 `http://127.0.0.1:1234`）。
2. **先确认真实模型名，不要猜**：

```bash
python scripts/batch_summary/main.py --models
```

输出里会列出 `/v1/models` 与原生 `/api/v0/models` 可见的模型及类型，
并给出建议写入 `.env` 的 `LLM_MODEL=...`。若只看到 `embeddings` 类型模型，说明对话模型还没加载。

## 2. 配置（项目根目录 `.env`，追加即可）

```bash
LLM_BASE_URL=http://127.0.0.1:1234/v1
LLM_MODEL=                      # 留空 = 自动选择第一个非 embedding 模型
LLM_TIMEOUT=180                 # 单篇请求超时（秒）
LLM_MAX_TOKENS=4096             # 摘要比"事件标题"长，预算要留够
LLM_TEMPERATURE=0.2
LLM_JSON_MODE=0                 # 摘要是纯文本，默认关闭
LLM_REASONING_EFFORT=none       # none=关闭思考（推理模型推荐）；留空=不发送该参数
ALLOW_REMOTE_LLM=0              # 保持 0：非本机地址会被直接拒绝
SUMMARY_HEARTBEAT_SECONDS=30    # 运行期间每隔多少秒打印一次状态块（也可用 --heartbeat 覆盖）
SUMMARY_PREVIEW_SECONDS=60      # 运行期间每隔多少秒刷新一次「中途预览.md」（0 = 关闭）
```

旧版（年度日记回顾）用的 `REVIEW_HEARTBEAT_SECONDS` / `REVIEW_PREVIEW_SECONDS` 仍然兼容：
新键没配置时读旧键，老的 `.env` 不用改也能跑。

安全约束（代码级强制）：`LLM_BASE_URL` 的 host 不是 `127.0.0.1 / localhost / ::1` 时直接报错退出，
日记内容不会被发送到任何外部服务。数据库以只读方式打开（SQLite `mode=ro`），
原始日记文件不修改、不删除；产物只写到本模块的 `output/` 目录（已被 `.gitignore` 忽略）。

### 推理模型（Qwen3.5 等）必须注意

`qwen3.5-9b` 这类模型**先输出思考、再输出正文**：思考会先把 `max_tokens` 预算吃光，
`message.content` 因此为空（`finish_reason=length`），现象是"模型返回内容为空"。

实测（3823 字日记，LM Studio + qwen3.5-9b，旧版单条标题的任务）：

| 请求 | 耗时 | 输出 tokens | 结果 |
|------|------|------------|------|
| `reasoning_effort=none`（关思考） | 2.4s | 60（思考 0） | ✅ 正常返回 |
| 默认（开思考） | 65.5s | 4096（全是思考） | ❌ content 为空 |

因此默认配置写成 `LLM_REASONING_EFFORT=none`；留空则请求里完全不带该参数（兼容非推理模型）。
注意：`/no_think` 前缀与 `chat_template_kwargs.enable_thinking=false` 在本机 LM Studio 版本下
**实测无效**，只有 `reasoning_effort` 生效。**LM Studio 端无需任何设置**，这是请求级参数。

`LLM_MAX_TOKENS` 只是**上限**、不是预留：关思考时实测输出 60~400 tokens，4096 已有充足余量。
**但如果要开思考，就必须成对调整**：思考会先把预算吃满，此时 `max_tokens` 要 8192+ **且**
`LLM_TIMEOUT` 要同步提到 600+，否则会从"快速报错"变成"每篇超时"。

## 3. 运行

```bash
# 抽样试跑（10 篇，跨年份抽样；只打印，不写状态/输出文件）
python scripts/batch_summary/main.py --test --samples 10

# 全量生成（可随时 Ctrl+C，重跑自动续跑）
python scripts/batch_summary/main.py --all

# 分年跑（适合先验证某一年的效果；注意必须带 --all）
python scripts/batch_summary/main.py --all --years 2015-2019
python scripts/batch_summary/main.py --all --year 2015

# 纳入炒股日记（默认排除 stock_diary，共 620 条日常流水）
python scripts/batch_summary/main.py --all --include-stock

# 只用已有摘要重新生成 Markdown（完全不调用模型）
python scripts/batch_summary/main.py --rebuild-md

# 看当前进度（可另开一个终端；主程序自己也会打印同样的状态）
python scripts/batch_summary/status.py
python scripts/batch_summary/status.py --list          # 列出历史运行目录

# 忽略断点状态，全部重新总结
python scripts/batch_summary/main.py --all --force

# 心跳间隔改成 60 秒；关闭中途预览；关闭心跳
python scripts/batch_summary/main.py --all --heartbeat 60
python scripts/batch_summary/main.py --all --no-preview
python scripts/batch_summary/main.py --all --no-heartbeat
```

也可以在项目根目录用模块方式运行：`python -m scripts.batch_summary.main --all`

## 4. 产物

| 位置 | 文件 | 说明 |
|------|------|------|
| 运行目录 | `日记总结.md` | **最终产物**：按年份排列的逐篇摘要 |
| 运行目录 | `中途预览.md` | 运行期间"截至当前"的摘要目录（可随时打开） |
| 运行目录 | `summaries.json` | 结构化中间结果：每篇一条摘要记录 |
| 运行目录 | `progress.json` | 实时进度快照（`status.py` 读它） |
| 运行目录 | `运行状态.txt` | 最新状态块（零命令查看） |
| 运行目录 | `待复核_未产出摘要.{md,json}` | 没有产出摘要的日记原文（失败/空答案） |
| 运行目录 | `batch_summary.log` | 处理日志 |
| `output/`（跨运行共享） | `summary_state.json` | 断点续跑状态：每篇的内容哈希、状态、摘要（每 20 篇落盘） |

Markdown 格式：

```markdown
# 日记总结

> 每篇日记一段摘要；日期取自日记本身的日期（MMDD）。同一天有多篇日记时各占一行。

## 2015年

- 0120 整理旧照片，翻到很多年前的旅行合影……
- 0303 周末去郊外走了两天，天气很好……
- 0101 新年回顾：去年的计划完成了大半……
```

日期标签直接取数据库里的日期（`MMDD`），**不问模型**：模型输出里没有日期与标题字段，
所以不存在日期猜测、区间合并之类的问题；同一天有多篇（例如整月合集拆出的两条）时各占一行。

`status` 口径：`ok` = 产出摘要；`empty` = 空正文或模型给出空答案；`failed` = 调用失败。
三个数字与 `summary_state.json` 里的 `stats` 完全一致。

**中途看结果：`中途预览.md`（全量跑几小时后才出最终文件，不用干等）**

最终 `日记总结.md` 只在**整轮所有条目处理完之后**写一次；为了让几小时的全量跑也能中途查看，
主程序运行期间会持续刷新一份 `<运行目录>\中途预览.md`：

```markdown
# 日记总结（中途预览）

> 截至 11:44:36 ｜ 已处理 128 / 3969 篇（3.2%） ｜ 正在处理 2015-06-18 multi_day 245字
> 这是运行中的快照（每 60 秒自动更新）；完整结果以同目录的 日记总结.md 为准。

## 2015年

- 0120 整理旧照片，翻到很多年前的旅行合影……
- 0303 周末去郊外走了两天，天气很好……
```

* **正文与最终产物逐行一致**（同一套渲染函数），中途看到的年份分组、日期标签、摘要文字
  与跑完后完全相同，可以放心先读；
* 只读内存里已有的结果，**不调用模型、不写 `progress.json`、不新建运行目录**，
  因此不会干扰 `status.py` 对"最近一次运行"的判断；
* 默认每 60 秒刷新一次；可 `--preview-every 120` 调慢/调快（下限 5 秒），
  `--preview-every 0` 或 `--no-preview` 关闭，`.env` 里用 `SUMMARY_PREVIEW_SECONDS` 设置；
* 刷新时机是"到点 + 摘要条数有变化"（条数没变时只更新头部进度，不重复排版）；
* 收尾时强制写一次：跑完显示"任务已完成"，Ctrl+C 中断显示"任务已中断（重跑同命令即可续跑）"；
* 写这个文件失败只记 debug 日志，**绝不会让任务失败**。

`status.py` 自动选择**最近一次运行**；输出与主程序状态块**格式完全一致**（复用同一函数）：

```text
[10:24:00] 2025 年日记批量总结任务运行中
[10:24:00] 已处理：128 / 329 篇（38.9%） ｜ 覆盖 127 / 328 天
[10:24:00] 当前阶段：调用模型（等待本地模型返回）
[10:24:00] 正在处理：2025-05-21 multi_day 310字（已等待 3s）
[10:24:00] 最近日志：2025-05-20 → 120字摘要 ｜ 有摘要 75 ｜ 空摘要 53 ｜ 失败 0 ｜ 跳过 0
[10:24:00] 结果：有摘要 75 ｜ 空摘要 53 ｜ 失败 0 ｜ 跳过(断点) 0
[10:24:00] 速度：9.2 秒/篇（393 条/h） ｜ 已用 19m32s ｜ 预计剩余约 30m42s（预计 10:54:42 完成）
[10:24:00] 进度：[###########...................] 38.9%
[10:24:00] 提示：快照 3s 前更新（任务应该还在跑）
----------------------------------------------------------
运行目录  : F:\...\scripts\batch_summary\output\260916104031
状态文件  : F:\...\260916104031\运行状态.txt  ← 直接用编辑器打开也能看
断点状态  : F:\...\output\summary_state.json  ← 跨运行共享
```

若快照超过 2 分钟没更新，会明确提示"任务可能已中断或空闲；重跑同一命令即可续跑"。

## 5. 断点续跑与失败处理

* 每处理 20 篇自动落一次状态（原子写入 `summary_state.json.tmp` → `os.replace`），Ctrl+C 不丢进度。
* 重跑时：内容哈希未变且已有结果的条目**直接跳过，不再调用模型**。
* 内容改过（哈希变化）、上次失败、Prompt 指纹变化 → 会自动重跑该篇。
* 单篇失败（超时/连接错误/空响应）自动重试 3 次（指数退避），仍失败则记录并继续下一篇；
  **连续失败 5 次**才停止整轮任务。
* 空正文（`content` 为空）不会调用模型，直接记为 `empty`。
* 中断后想先看已有结果：`--rebuild-md`（不调模型），或直接打开运行目录里的 `中途预览.md`。
* 状态文件带版本号（`version: 2`）；旧版（年度回顾，`version: 1`）的状态文件会被忽略并从零开始，
  因为两种任务的结果结构完全不同。

## 6. 模型输出如何被清洗（Python 负责，不依赖模型）

模型只被要求"输出一段摘要"，其余全部由 Python 处理：

* 取出 ``` 代码块里的内容（模型偶尔会把摘要包起来）；
* 去掉 `摘要：` / `Summary:` 之类前缀、列表符号（`- `、`1. `）与标题符号（`## `）；
* 去掉包裹引号，把换行与连续空白压成单个空格（产物是"一篇一行"）；
* **去掉开头重复的日期/时间铺垫**：行首已经有 `MMDD` 标签，模型爱写的
  "2020 年 2 月 8 日下午，""这一天，""2 月 8 日，"会被删掉；
* **句首的"作者/笔者"改回"我"**（模型爱用第三人称）：行首或标点之后的才改，
  "这本书的作者"这类被修饰的写法不动 —— 所以 Prompt 里也明确禁止用"作者"称呼自己；
* **丢掉末尾那句对日记本身的评述**（如"整篇日记主要记录了…""内容简洁且完整反映了原文"
  "未涉及其他额外的人物"），最多连续丢 3 句，且丢完必须还剩内容；
* 明显的空答案（`无` / `暂无` / `none` / 纯标点等）视为**没有摘要**，记为 `empty` 并进入待复核清单；
* 超过 `MAX_SUMMARY_CHARS`（默认 60 字；Prompt 要求 20~40 字、最多 50 字）时优先在句读处截断；
  若 60 字内只有很短的第一句，则保留那一整句，避免出现"半句 + 省略号"。

> 上限与清洗只是**兜底**：把长摘要压短的主力是 Prompt（字数要求 + 4 条 few-shot 示例）。
> Python 只能删头尾、截断，改写不了语义，所以如果模型整体跑偏，先调 Prompt 再看这里。

## 7. 调 Prompt / 调参数

* Prompt：直接编辑 `prompts/diary_summary_prompt.txt`（用 `{DATE}`、`{ENTRY_TYPE}`、`{CONTENT}` 占位符）。
  Prompt 改动后指纹变化，重跑时会重新处理（旧结果仍留在状态文件里，便于对比）。
* 长度与截断等常量集中在 `config.py`：`MAX_SUMMARY_CHARS`（摘要上限）、
  `CONTENT_HEAD_CHARS` / `CONTENT_TAIL_CHARS`（超长日记送进 Prompt 的字符数）、
  `MAX_RETRIES` / `REQUEST_INTERVAL_SECONDS` / `MAX_CONSECUTIVE_FAILURES` / `STATE_SAVE_EVERY`。
* LLM 参数（超时、token 预算、温度、思考开关）在项目根目录 `.env`，见上面第 2 节。

## 8. 性能与范围

* 单篇独立请求，不把全部日记塞进上下文；正文超过 `CONTENT_HEAD_CHARS + CONTENT_TAIL_CHARS`
  （默认 4000 + 1000 字）时保留头尾、中间省略。
* 默认处理范围排除 `stock_diary`（620 条日常炒股流水），实际约 3969 篇；需要时用 `--include-stock` 纳入。
* 旧版（只输出 60 个 token 的"事件标题"）实测关思考约 2.4 秒/篇；**摘要长得多**
  （约 150~300 输出 token），单篇耗时会相应增加，总时长请以 `--test` 实测为准：
  先 `--test --samples 10` 看单篇耗时，再决定全量跑还是按年 `--years` 分批跑。
* 若把 `LLM_REASONING_EFFORT` 留空（开思考），实测同一篇要 65 秒以上且预算常被思考吃光，
  全量会变成数十小时 —— 建议保持 `none`。
* 换模型或改 Prompt 之后想拿到新口径的结果，用 `--force` 重跑（否则已有摘要会被跳过）。

## 9. 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```

覆盖：摘要清洗与截断、按年渲染与日期标签、断点状态（含旧版状态忽略）、失败隔离与续跑、
运行期心跳/状态块、中途预览、状态看板。全部用例都不需要真实 LLM。

---

相关文档：[项目主 README](../../README.md) ｜ [Web 浏览系统](../../webapp/README.md)


