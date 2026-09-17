import { Form, Link, useLocation, useSearchParams } from 'react-router-dom'
import { getEntries } from '../api/entries'
import { yearMonthParams } from '../api/filters'
import { EntryCard } from '../components/EntryCard'
import { Pagination } from '../components/Pagination'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { YearMonthFilter } from '../components/YearMonthFilter'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

/** 每页条数：默认 50，保证点进某个年份就能一屏看到 35 篇以上 */
const PAGE_SIZES = [35, 50, 100]
const DEFAULT_PER_PAGE = 50

/** 日记类型 → 中文标签（取值与 create_diary_db.sql 一致） */
const ENTRY_TYPES: [string, string][] = [
  ['diary', '普通日记'],
  ['stock_diary', '股票日记'],
  ['retrospective', '回顾'],
  ['summary', '总结'],
  ['note', '随手记'],
]

/** 组装查询参数：年 / 月做范围归一化，非法值不传给后端（避免 422） */
function buildParams(p: URLSearchParams) {
  const { year, month } = yearMonthParams(p)
  return {
    year,
    month,
    entry_type: p.get('entry_type') ?? undefined,
    q: p.get('q') ?? undefined,
    page: p.get('page') ?? undefined,
    per_page: p.get('per_page') ?? DEFAULT_PER_PAGE,
  }
}

export function BrowsePage() {
  useDocumentTitle('浏览日记')
  const [p] = useSearchParams()
  const location = useLocation()
  const key = p.toString()
  const { data, error, loading } = useApi((s) => getEntries(buildParams(p), s), [key])
  const rangeStart = data ? (data.page - 1) * data.per_page + 1 : 1
  const rangeEnd = data ? Math.min(data.page * data.per_page, data.total) : 0
  return (
    <>
      <h1>浏览日记</h1>
      <Form className="filters">
        <YearMonthFilter year={p.get('year') ?? ''} month={p.get('month') ?? ''} />
        <select name="entry_type" defaultValue={p.get('entry_type') ?? ''}>
          <option value="">全部类型</option>
          {ENTRY_TYPES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <input name="q" defaultValue={p.get('q') ?? ''} placeholder="搜索正文" />
        <select name="per_page" defaultValue={p.get('per_page') ?? DEFAULT_PER_PAGE}>
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n} 篇/页
            </option>
          ))}
        </select>
        <button>筛选</button>
        <Link className="clear" to={location.pathname}>
          清除筛选
        </Link>
        <small className="hint">留空表示不筛选；年 / 月可直接输入数字，也可点输入框选候选。</small>
      </Form>
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} />
      ) : !data?.items.length ? (
        <EmptyState />
      ) : (
        <>
          <p className="meta">
            第 {rangeStart}–{rangeEnd} 篇 / 共 {data.total} 篇
          </p>
          {data.items.map((e) => (
            <EntryCard key={e.id} entry={e} />
          ))}
          <Pagination page={data.page} pages={data.pages} />
        </>
      )}
    </>
  )
}
