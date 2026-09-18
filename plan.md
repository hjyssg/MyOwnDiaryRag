# 前端三项调整计划（类型筛选统一 / 日期页更名为「日期查找」 / 随机页日期可点进）

> 约定：后端 SQL 集中在根 `database.py`、`summary_database.py`；router 只管参数与 HTTP 状态，
> service 组合业务规则；前端页面不直接访问 SQLite，也不散落裸 `fetch`（一律走 `src/api/*`）。
> 组件复用优先：能抽成组件的筛选控件放 `src/components/`，页面只负责组装查询参数。

## 0. 现状与根因（动手前已核实）

| 现象 | 证据 |
| --- | --- |
| 摘要页的"类型"是自由文本输入，和浏览页完全不一致 | `src/pages/SummariesPage.tsx:47` 是 `<input name="entry_type" placeholder="类型" />`；`src/pages/BrowsePage.tsx:95-106` 是闭合 `<select>`（全部类型 / 普通日记 / 股票日记 / 回顾 / 总结 / 随手记）。用户必须在摘要页手打 `stock_diary` 这类内部值，打错就静默零结果 |
| 年 / 月筛选已经抽成共用组件，类型还没抽 | `src/components/YearMonthFilter.tsx` 被 `BrowsePage.tsx:90` 与 `SummariesPage.tsx:46` 复用；类型下拉目前只有 BrowsePage 内联的那一份 |
| "过去的今天"这个名字与页面能力不符 | 页面支持任意 `?month=&day=`（`OnThisDayPage.tsx:26-41`），后端 `/api/on-this-day?month=&day=`（`webapp-backend/routers/calendar.py:47-58`）也是"任意月日的历史记录"，并不是只能看今天。同一个名字还出现在：`AppLayout.tsx:19`（左侧导航）、`HomePage.tsx:42-43`（入口卡）、`webapp-backend/README.md:51` |
| 随机页的日期是死文本，不能跳转 | `RandomPage.tsx:26-28` 只渲染 `<time dateTime>{data.date}</time>`；而它的响应里已带 `month` / `day`（`api/types.ts:94-101`），和 on-this-day 的查询参数天然对齐 |

**命名结论（本次采用）**："过去的今天" → **日期查找**。
理由：这个页面本质是"按日期查找"——选一个(月, 日)，把它在各年份的记录一次查出来；
`日期查找` 直说动作，不含"今天"这种会误导的词，且是 4 个字，与既有侧栏标签
（浏览日记 / 随机回忆 / AI 摘要）同构，190px 宽的侧栏（`globals.css:72-83`）单行放得下。
备选：`同月同日`（描述的是结果形态：同月同日跨年份）、`月日回看`、`那年今日`（若选备选，只需换 B 任务里的文案）。

---

## 任务 A：摘要页的类型筛选改为与浏览页一致的共用组件

**目标**：两个页面的"类型"控件长得一样、取值一样、行为一样（含"清除筛选 / URL 回填"下的表现），
且类型选项只有一份定义。

### 改动清单
1. `src/components/entryTypes.ts`（纯常量模块，非组件文件，不触发 react-refresh 告警）
   - 新增 `export const entryTypeOptions: [string, string][]`，内容即现在 `BrowsePage.tsx:19-25` 的
     `ENTRY_TYPES`：`diary=普通日记`、`stock_diary=股票日记`、`retrospective=回顾`、`summary=总结`、`note=随手记`。
   - 保留 `entryTypeLabel` 不动（它给卡片上的 `.tag` 用短标签：日记 / 股票 / …，与下拉的长标签是两种用途）。
2. 新增 `src/components/EntryTypeFilter.tsx`
   ```tsx
   import { entryTypeOptions } from './entryTypes'
   /** 日记类型下拉：选项只有一份（entryTypes.ts），browse / summaries 共用。 */
   export function EntryTypeFilter({ value = '' }: { value?: string }) {
     return (
       <select name="entry_type" aria-label="日记类型" key={value} defaultValue={value}>
         <option value="">全部类型</option>
         {entryTypeOptions.map(([v, label]) => (
           <option key={v} value={v}>{label}</option>
         ))}
       </select>
     )
   }
   ```
   - 非受控 + `key={value}`：沿用 `BrowsePage.tsx:88-98` 已有模式，提交 / 清除筛选后按 URL 回填。
   - `key` 写在组件内部返回的 `<select>` 上（合法且有效：key 变化会强制重建该元素）。
3. `src/pages/BrowsePage.tsx`
   - 删除本地 `ENTRY_TYPES`（第 19-25 行）与内联 `<select name="entry_type">`（第 95-106 行）。
   - 改为 `<EntryTypeFilter value={p.get('entry_type') ?? ''} />`；`buildParams` 一行不改。
4. `src/pages/SummariesPage.tsx`
   - 第 47 行的 `<input name="entry_type" ...>` → `<EntryTypeFilter value={p.get('entry_type') ?? ''} />`。
   - 请求参数不变（`entry_type` 本来就透传给 `/api/summaries`，`routers/summaries.py:19` 支持）。

### 验收
- `/summaries` 的类型下拉与 `/browse` 完全同款（同一个组件、同一份选项、同一句"全部类型"）。
- 选"股票日记"提交后 URL 为 `?entry_type=stock_diary`，请求带 `entry_type=stock_diary`，下拉回填正确。
- `SummariesPage.test.tsx` 新增断言：`select[name="entry_type"]` 存在，且 `?entry_type=note` 时选中"随手记"。
- `BrowsePage.test.tsx:237-240` 关于"条件行 4 个 input/select"的断言仍然通过。

---

## 任务 B：把"过去的今天"改名为"日期查找"（页面 + 左侧导航）

**目标**：把**页面本身与左侧导航**的命名改为"日期查找"，不再暗示"只能看今天"；
**首页入口卡按用户要求保留"过去的今天"**，不做改动。同时**不改动 URL 契约**（`/on-this-day?month=&day=` 被
`StatisticsPage.tsx:62`、`RandomPage` 新入口、`OnThisDayPage.test.tsx`、后端 `routers/calendar.py` 依赖）。

### 改动清单（只动展示名，不动路由 / 组件名 / 接口名）
| 文件 | 现在 | 改成 |
| --- | --- | --- |
| `src/app/AppLayout.tsx:19` | `{ to: '/on-this-day', label: '过去的今天', ... }`（图标保持原样） | `label: '日期查找'` |
| `src/pages/OnThisDayPage.tsx:25` | `useDocumentTitle('过去的今天')` | `useDocumentTitle('日期查找')` |
| `src/pages/OnThisDayPage.tsx:53` | `<h1>过去的今天</h1>` | `<h1>日期查找</h1>` |
| `src/styles/globals.css:545` | 注释 `“过去的今天”按年份分组…` | 注释同步改名（仅注释） |
| `src/pages/OnThisDayPage.test.tsx:33` | `describe('过去的今天日期选择')` | `describe('日期查找日期选择')` |
| `webapp-backend/README.md:51` | `"过去的今天"用原生 type="date"…` | `"日期查找"用原生 type="date"…` |
| `webapp-backend/schemas.py:136,147,154`、`services/calendar.py:53` | docstring 文案 | 同步为"日期查找"（只动中文说明） |
| `database.py:362` | 分区注释 `# ---------------- 过去的今天 ----------------` | 注释同步改名 |
| `README.md:21,113`（仓库根） | 「过去的今天」（feature 列表 / 使用说明里的导航项） | 「日期查找」 |

**明确不动**：`src/pages/HomePage.tsx:38-44` 的首页入口卡（`<h2>过去的今天</h2>` + "查看同月同日的历史记录。"）
保持原样——首页作为"入口导语"用它，页面内标题不重复这个词（用户 2026-09 决定）。

### 验收
- **三处**文案一致：左侧导航标签、页面 `<h1>`、浏览器标签页标题（`日期查找 · 我的日记`）。
- 首页入口卡仍是"过去的今天"（不做任何改动），点进去落地页标题为"日期查找"。
- `StatisticsPage.test.tsx:42` 断言的 `href=/on-this-day?month=9&day=17` 不受影响（路由不变）。
- 全仓 `grep -rn "过去的今天"` 工作区只剩 `HomePage.tsx:42` 一处（外加本计划文档里的"旧名 → 新名"对照说明，
  以及 `reference/plan.md` 这份最初设计稿——作为历史资料保持原样不改）。

---

## 任务 C：随机回忆页点日期进入"日期查找"对应日期

**目标**：`/random` 顶部那条 `2026-04-16` 变成链接，点进去就是 `/on-this-day?month=4&day=16`，
加载该月日在**各年份**的记录（不是只有 2026 年这一天）。

### 改动清单
1. `src/pages/RandomPage.tsx:26-28`
   ```tsx
   <h2>
     <Link to={`/on-this-day?month=${data.month}&day=${data.day}`} title="看这一天的历史记录">
       <time dateTime={data.date}>{data.date}</time>
     </Link>
   </h2>
   ```
   - 链接文字就是日期本身（可访问名 = `2026-04-16`），沿用 `.random-bar h2` 的字号，不新开按钮位。
2. `src/styles/globals.css`：`.random-bar h2 a` 继承 `color: inherit`、`text-decoration: none`，
   `:hover` 时加下划线 + `color: var(--accent)`，让"可点"有反馈（紧随 `.random-bar h2` 规则，第 574-579 行后）。
3. `src/pages/RandomPage.test.tsx`：新增用例，断言
   `getByRole('link', { name: '2026-04-16' })` 的 `href === '/on-this-day?month=4&day=16'`。
4. 兼容性：`RandomPage.test.tsx` 里 `renderPage()` 的 memory router 增加
   `{ path: '/on-this-day', element: <div>日期查找</div> }`，便于后续补"点击后跳转"的行为断言。

### 验收
- `/random` 显示日期可点，`href` 为 `/on-this-day?month=<月>&day=<日>`；点进去页面 `<h1>` 为"日期查找"，
  日期框回填该月日，列表按年份分组。
- 多篇 / 单篇两种形态都不受影响（`random-entries` 与 `single` 的既有断言保持通过）。

---

## 验证方式（改完后逐条跑）

```bash
cd webapp-frontend
npm run typecheck          # tsc -b
npm run lint
npm run format:check
npx vitest run src/pages/BrowsePage.test.tsx src/pages/SummariesPage.test.tsx \
  src/pages/RandomPage.test.tsx src/pages/OnThisDayPage.test.tsx src/pages/StatisticsPage.test.tsx
npm test -- --run          # 全量回归
```

- 手动验证（`npm run dev` + 后端 `/api/*`）：
  1. `/browse` 与 `/summaries` 的类型下拉逐项对比（选项文字、顺序、空选项）。
  2. `/summaries?entry_type=note` 能筛出随记类摘要。
  3. 左侧点了"日期查找"→ 标签页标题正确；`/random` 点日期 → URL 变成对应月日，标题为"日期查找"。

## 明确不做（本次范围外）
- 不改路由 `/on-this-day`，不改 `OnThisDayPage` / `getOnThisDay` / `OnThisDayResponse` 等**代码标识符**
  （改 URL 会牵动前端测试与后端路由文档，收益低）；若确需改 URL 再单开一次任务。
- 不在随机页给正文条目加"查看原文"入口（当前页面刻意只做"读一天全文"）。
- 不引入任何 UI 库，样式继续手写 `src/styles/globals.css`。