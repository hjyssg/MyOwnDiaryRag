import { Form, Link, useLocation, useSearchParams } from 'react-router-dom'
import { getEntries, getFullEntries } from '../api/entries'
import { yearMonthParams } from '../api/filters'
import type { EntryPreview, FullEntry } from '../api/types'
import { EntryCard } from '../components/EntryCard'
import { entryTypeLabel } from '../components/entryTypes'
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

function groupByMonth<T extends EntryPreview>(items: T[]) {
  return items.reduce<{ label: string; items: T[] }[]>((result, item) => {
    const label = `${item.year}年 ${item.month}月`
    const group = result.find((candidate) => candidate.label === label)
    if (group) group.items.push(item)
    else result.push({ label, items: [item] })
    return result
  }, [])
}

export function BrowsePage() {
  useDocumentTitle('浏览日记')
  const [p, setSearchParams] = useSearchParams()
  const location = useLocation()
  const key = p.toString()
  const fullMode = p.get('full') === '1'
  const params = buildParams(p)
  const preview = useApi(
    (s) => (fullMode ? Promise.resolve(undefined) : getEntries(params, s)),
    [key, fullMode],
  )
  const full = useApi(
    (s) => (fullMode ? getFullEntries(params, s) : Promise.resolve(undefined)),
    [key, fullMode],
  )
  const rangeStart = preview.data ? (preview.data.page - 1) * preview.data.per_page + 1 : 1
  const rangeEnd = preview.data
    ? Math.min(preview.data.page * preview.data.per_page, preview.data.total)
    : 0
  const previewGroups = preview.data ? groupByMonth(preview.data.items) : []
  const fullGroups = full.data ? groupByMonth<FullEntry>(full.data.items) : []
  const data = fullMode ? full.data : preview.data
  const error = fullMode ? full.error : preview.error
  const loading = fullMode ? full.loading : preview.loading
  const toggleFullMode = (checked: boolean) => {
    const next = new URLSearchParams(p)
    if (checked) next.set('full', '1')
    else next.delete('full')
    next.delete('page')
    setSearchParams(next)
  }
  return (
    <div className="browse-page">
      <header className="page-intro">
        <h1>浏览日记</h1>
      </header>
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
        <input
          name="q"
          defaultValue={p.get('q') ?? ''}
          placeholder="搜索日记内容…"
          aria-label="搜索正文"
        />
        {!fullMode && (
          <select name="per_page" defaultValue={p.get('per_page') ?? DEFAULT_PER_PAGE}>
            {PAGE_SIZES.map((n) => (
              <option key={n} value={n}>
                {n} 篇/页
              </option>
            ))}
          </select>
        )}
        <label className="full-toggle">
          <input
            type="checkbox"
            name="full"
            value="1"
            checked={fullMode}
            onChange={(event) => toggleFullMode(event.target.checked)}
          />
          显示完整正文
        </label>
        <button>搜索</button>
        <Link className="clear" to={location.pathname}>
          清除筛选
        </Link>
        <small className="hint">留空表示不筛选；年份填写 4 位数字，月份填写 1–12。</small>
      </Form>
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} />
      ) : !data?.items.length ? (
        <EmptyState />
      ) : (
        <>
          <p className="list-meta">
            {fullMode
              ? `共 ${data.total} 篇完整日记`
              : `第 ${rangeStart}–${rangeEnd} 篇 / 共 ${data.total} 篇`}
          </p>
          {fullMode
            ? fullGroups.map((group) => (
                <section className="timeline-month" key={group.label}>
                  <h2>{group.label}</h2>
                  {group.items.map((entry) => (
                    <article className="full-entry" key={entry.id}>
                      <header>
                        <time dateTime={entry.date}>{entry.date}</time>
                        <span className={`tag tag-${entry.entry_type}`}>
                          {entryTypeLabel(entry.entry_type)}
                        </span>
                      </header>
                      <div className="content">{entry.content}</div>
                      <Link to={`/entries/${entry.id}`}>查看原文 →</Link>
                    </article>
                  ))}
                </section>
              ))
            : previewGroups.map((group) => (
                <section className="timeline-month" key={group.label}>
                  <h2>{group.label}</h2>
                  {group.items.map((entry) => (
                    <EntryCard key={entry.id} entry={entry} />
                  ))}
                </section>
              ))}
          {!fullMode && preview.data && (
            <Pagination page={preview.data.page} pages={preview.data.pages} />
          )}
        </>
      )}
    </div>
  )
}
