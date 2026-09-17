# 日记 Web 前端优化计划（browse 分页 / 筛选交互 / 日期输入 / 随机全文）

> 约定：后端 SQL 集中在根 `database.py`、`summary_database.py`；router 只管参数与 HTTP 状态，
> service 组合业务规则；前端页面不直接访问 SQLite，也不散落裸 `fetch`（一律走 `src/api/*`）。

## 0. 现状与根因（动手前已核实）

| 现象 | 证据 |
| --- | --- |
| `browse?year=2024` 只显示 20 篇 | 后端默认 `per_page=20`（`webapp-backend/routers/entries.py:22`、`database.py:117`），前端 `BrowsePage.tsx` 从不传 `per_page` |
| 筛选栏"年 input / 月 select"不一致、不顺手 | `BrowsePage.tsx:19-30`；`SummariesPage.tsx:25-26` 又是两个裸 input，三处风格各不相同 |
| 提交筛选会丢掉 `page`（期望行为），也会丢 `per_page` | react-router 7.18.4 的 GET `<Form>` 提交时 `search` 由表单字段整体替换（`getFormSubmissionInfo` 中 `parsedPath.search = "?" + searchParams`） |
| 年 / 月统计接口前端从未使用 | `getMonths()` 定义于 `src/api/entries.ts:13` 但全仓 0 调用；`getYears()` 仅 HomePage 使用 |
| "随机一天"拿不到全文 | `database.entries_for_date()` 已 SELECT 并保留 `content`（`database.py:227,237`），但 `services/calendar.py:59` 用无 `content` 字段的 `OnThisDayItem` 序列化，被 Pydantic 丢弃 |
| 不引入 UI 库的前提 | 依赖只有 `react / react-dom / react-router-dom`，样式为手写 `src/styles/globals.css` |

**UI 组件选型结论（本次不引库）**：实测 `react-day-picker@10.0.1`、`react-datepicker@9.1.0`、
`antd@6.6.4`、`@rc-component/picker@1.14.0`（原 rc-picker，**无自带 CSS**，脱离 antd 独立使用会没样式）、
`@mui/x-date-pickers@9.14.0`。本次采用**原生 input + 键盘输入**方案（零依赖、零体积）；
后续若需要"专业 datepicker"，再按上表升级（首选 `react-day-picker@10`，自带 `zhCN` 与样式）。

---

## 任务 A：`browse?year=` 单页至少 35 篇

**目标**：进入某年列表时默认一页 ≥35 篇，且分页 / 再次筛选后页大小稳定。

### 改动（已完成）
1. `src/pages/BrowsePage.tsx`
   - 常量：`PAGE_SIZES = [35, 50, 100]`、`DEFAULT_PER_PAGE = 50`。
   - 请求参数注入：`per_page: p.get('per_page') ?? DEFAULT_PER_PAGE`（URL 有则优先）。
   - 表单新增"每页"`<select name="per_page">`（闭合枚举，用 select 合适），保证提交后写进 URL，
     `Pagination` 从 `location.search` 复制参数，翻页时页大小保持。
   - 顶部文案改为区间：`第 1–50 篇 / 共 522 篇`。
2. 后端**不改**：保留 `/api/entries` 默认 20、上限 100（避免破坏 `tests/test_web_api.py:132`
   的 `per_page: 20` 契约断言与 `/api/search` 兼容行为）。

### 验收
- `/browse?year=2025` 首屏请求带 `per_page=50`，一页出满 50 条（真实库 2025 年共 522 篇，已实测）。
- 切"100 篇/页"再翻页，URL 与请求都保持 `per_page=100`；点"筛选"后 `page` 归 1、`per_page` 保留。

---

## 任务 B：筛选栏统一为"原生 input + 直接打字"（年 / 月）

**目标**：年、月都是原生 input，可直接键盘输入；同时用原生 `datalist` 提示"有哪些年份 / 月份"。

### 改动（已完成）
1. `src/api/filters.ts`（纯函数，避免组件文件混合导出触发 react-refresh 告警）：
   `MIN_YEAR` / `MAX_YEAR` / `normalizeYear` / `normalizeMonth` / `yearMonthParams`。
2. `src/components/YearMonthFilter.tsx`（BrowsePage、SummariesPage 复用）：
   - 年：`<input name="year" type="number" inputMode="numeric" min="2000" max="2100" list="filter-years">`
     + `<datalist id="filter-years">`，候选项来自 `getYears()`：`<option value="2025" label="522 篇">`。
   - 月：`<input name="month" type="number" inputMode="numeric" min="1" max="12" list="filter-months">`
     + `<datalist id="filter-months">`：输入了合法年份 → 候选项来自 `getMonths(year)`（`label` 为条数）；
     未输入 / 非法年份 → 退回 1–12 通用候选（后端允许"只给 month 不给 year"）。
   - 归一化兜底（避免 422）：`year` 必须是 4 位且 2000–2100、`month` 必须在 1–12，否则视为"不筛选"，
     不传给后端；年份输入满 4 位数字时才触发 `getMonths` 请求。
3. `src/pages/BrowsePage.tsx`：用 `YearMonthFilter` 替换 `year` input + `month` select；
   `entry_type` 保留 select 并补中文标签（普通日记 / 股票日记 / 回顾 / 总结 / 随手记）；
   新增"清除筛选"链接与一行提示。
4. `src/pages/SummariesPage.tsx`：同样用 `YearMonthFilter` 替换两个裸 input，并用 `yearMonthParams`
   组装查询参数（`/api/summaries` 已支持 `year`/`month`，`routers/summaries.py:18-19`）。
5. `src/styles/globals.css`：补 `.filters .hint` / `.filters .clear` / `.filters input[type='date']`，
   沿用现有 `@media (max-width:680px)` 竖排规则。

### 验收
- `/browse?year=2025&month=9` 与手输 `2025` / `9` 后提交结果一致；输入 `13` 月按空处理，不报错误页。
- 年份输入框能弹出候选年份（含条数）；月份候选随年份变化（已用真实库 `/api/months?year=2025` 验证）。

---

## 任务 C：`on-this-day` 用原生日期输入 + 打字 + 快捷按钮

**目标**：不再手填两个 number input；用原生 `<input type="date">`（可键盘打字，也带浏览器原生日历弹层），
并补"今天 / 前一天 / 后一天"快捷。

### 改动（已完成）
1. `src/pages/OnThisDayPage.tsx`
   - 表单：`<input name="date" type="date" key={dateValue} defaultValue={dateValue}>`（值只取月 / 日；
     年份固定用闰年参考年 2024，这样 2 月 29 日也是合法日期，也不会出现"2026-02-29"这种不存在的值；
     用 `key` 让快捷按钮改变 URL 后输入框回填新值）。
   - URL **契约不变**：仍是 `?month=9&day=17`（后端 `/api/on-this-day` 与 `tests/test_web_api.py:181-194` 不动）。
   - 快捷按钮：`今天`、`← 前一天`、`后一天 →`（在参考年 2024 上做日期运算：
     2 月 28 日 → 2 月 29 日 → 3 月 1 日，跨月 / 跨年都正确）。
   - 月 / 日做范围钳制（非法 URL 参数回退到今天），避免给 `type="date"` 喂非法值、也避免 422。
   - 文案：`2 月 28 日 · 共 N 篇`，下面仍按年份分组。
2. 备选（若不能接受浏览器日期格式差异）：改回月 / 日两个 `type="number"` + 打字 + 同样的快捷按钮 ——
   只需改 `OnThisDayPage` 表单那一小块。

### 验收
- 选 `2024-02-28` → 请求 `?month=2&day=28`；"后一天"→ `?month=2&day=29` → 再"后一天"→ `?month=3&day=1`。
- 真实库 `2 月 29 日` 有 2 篇日记，可正常浏览（`/api/on-this-day?month=2&day=29` 返回 200）。
- 无日记的日期显示 `2月28日暂无日记`。

---

## 任务 D（新增）：`RandomPage` 显示全文

**目标**：随机一天直接展示该日各篇日记的**完整正文**，而不是 120 字预览。

### 改动（已完成）
后端：
1. `webapp-backend/schemas.py`：新增 `RandomDayItem(EntryPreview)`（含 `content: str`），
   并把 `RandomDayResponse.items` 改为 `List[RandomDayItem]`。
2. `webapp-backend/services/calendar.py`：`get_random_day` 中 `OnThisDayItem.model_validate(entry)`
   → `RandomDayItem.model_validate(entry)`。
3. `database.py` **不需要改**：`entries_for_date()` 已同时返回 `content` 与 `preview`。
4. `tests/test_web_api.py`：`test_random_response_is_not_cacheable` 增补断言
   `item["content"]` 等于该篇正文。

前端：
1. `src/api/types.ts`：新增 `RandomDayItem extends EntryPreview { content: string }`；
   `RandomDayResponse.items: RandomDayItem[]`。
2. `src/pages/RandomPage.tsx`：每篇渲染 `日期 + entry_type/字数 + <div className="content">{content}</div>`
   （复用 `EntryPage.tsx:44` 的 `.content` 样式），保留"再随机一天"与"查看摘要"入口。
3. `src/pages/RandomPage.test.tsx`：断言全文渲染、`/api/random` 只请求一次。

### 验收
- `/random` 能看到整篇正文；"再随机一天"换一天；空库仍 404 → `ErrorState`。

---

## 交付物清单

**新增**
- `webapp-frontend/src/api/filters.ts`、`webapp-frontend/src/components/YearMonthFilter.tsx`
- `webapp-frontend/src/pages/BrowsePage.test.tsx`、`OnThisDayPage.test.tsx`、`RandomPage.test.tsx`
- `plan.md`（本文件）

**修改**
- `webapp-frontend/src/pages/BrowsePage.tsx`（per_page / 区间文案 / 复用筛选组件）
- `webapp-frontend/src/pages/OnThisDayPage.tsx`（原生日期输入 + 快捷按钮）
- `webapp-frontend/src/pages/SummariesPage.tsx`、`SummariesPage.test.tsx`（复用筛选组件）
- `webapp-frontend/src/pages/RandomPage.tsx`、`src/api/types.ts`（随机全文）
- `webapp-frontend/src/styles/globals.css`（筛选栏 / 日期输入 / 快捷按钮样式）
- `webapp-backend/schemas.py`、`webapp-backend/services/calendar.py`（随机全文）
- `tests/test_web_api.py`（随机接口全文断言）、`webapp-backend/README.md`（说明同步）

## 验证命令

```bash
# 后端
python -m unittest discover -s tests -p "test_*.py" -v

# 前端
cd webapp-frontend
npm run lint
npm run typecheck
npm test -- --run
npx prettier --check src/
npm run build

# 手动
python webapp-backend/app.py            # 终端 1
cd webapp-frontend && npm run dev       # 终端 2
# /browse?year=2025   → 一页 50 篇、年 / 月可打字、可清除筛选
# /on-this-day        → 日期输入 + 今天 / 前后一天
# /random             → 显示全文
```

## 实际验证结果（本次）

- 后端 `python -m unittest discover -s tests`：**158 tests OK**。
- 前端 `npm run lint`：0 error / 0 warning；`npm run typecheck`：通过。
- 前端 `npx vitest run`：6 文件 / **12 tests passed**；`npx prettier --check src/`：全部符合。
- `npm run build`：成功（326 kB / gzip 103 kB）。
- 真实库 E2E（`diary_database.db`）：`/api/entries?year=2025&per_page=50` → total 522、一页 50 条；
  `/api/random` → 带 `content` 全文；`/api/on-this-day?month=2&day=29` → 200（2 篇）；
  `/api/on-this-day?month=13` → 422；`/api/months?year=2025` → 12 个月的条数齐全。

## 风险与未做项（明确记录）

- 不引入任何 UI 库；`<input type="date">` 的显示格式随浏览器 / 系统 locale 变化
  （Chrome/Windows 为"年/月/日"，Safari 与 Chrome 不完全一致），且参考年固定显示 2024
  （因为本页只查月 / 日，闰年参考年才能表达 2 月 29 日）。若后续要"专业 datepicker"，
  按第 0 节对比表升级（推荐 `react-day-picker@10`，自带 `zhCN` 与样式）。
- `/api/entries` 默认 `per_page` 仍为 20（仅浏览页前端传 50）；摘要页页大小不在本次范围。
- `on-this-day` 仍只显示 120 字预览（正文点进详情页），本次不改成全文。

