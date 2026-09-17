import type { FormEvent } from 'react'
import { Form, useSearchParams } from 'react-router-dom'
import { getOnThisDay } from '../api/entries'
import { EntryCard } from '../components/EntryCard'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const pad = (n: number) => String(n).padStart(2, '0')

/**
 * 月 / 日的"参考年份"固定为闰年 2024：本页只关心月 / 日（查各年同月日的日记），
 * 用闰年当参考年可以让 2 月 29 日也是合法日期，日期加减也不会出现"2026-02-29"这种当前年份不存在的值。
 */
const REFERENCE_YEAR = 2024

/** 参考年上的日期加减：2 月 28 日的"后一天"是 2 月 29 日，2 月 29 日的"后一天"落到 3 月 1 日 */
function shiftDate(month: number, day: number, delta: number) {
  const shifted = new Date(Date.UTC(REFERENCE_YEAR, month - 1, day + delta))
  return { month: shifted.getUTCMonth() + 1, day: shifted.getUTCDate() }
}

export function OnThisDayPage() {
  useDocumentTitle('过去的今天')
  const [p, setSearchParams] = useSearchParams()
  const now = new Date()
  const rawMonth = Number(p.get('month'))
  const month = rawMonth >= 1 && rawMonth <= 12 ? rawMonth : now.getMonth() + 1
  // 闰年参考年下"本月最后一天"，顺手把非法日（如 2 月 31 日）钳回今天
  const lastDay = new Date(REFERENCE_YEAR, month, 0).getDate()
  const rawDay = Number(p.get('day'))
  const day = rawDay >= 1 && rawDay <= lastDay ? rawDay : now.getDate()
  const dateValue = `${REFERENCE_YEAR}-${pad(month)}-${pad(day)}`
  const { data, error, loading } = useApi((s) => getOnThisDay(month, day, s), [month, day])
  const go = (target: { month: number; day: number }) =>
    setSearchParams({ month: String(target.month), day: String(target.day) })
  // 原生日期输入提交的是 YYYY-MM-DD；URL 仍沿用后端的 ?month=&day= 契约
  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const parts = String(new FormData(event.currentTarget).get('date') ?? '').split('-')
    if (parts.length !== 3) return
    go({ month: Number(parts[1]), day: Number(parts[2]) })
  }
  return (
    <>
      <h1>过去的今天</h1>
      <Form className="filters" onSubmit={onSubmit}>
        <input
          key={dateValue}
          name="date"
          type="date"
          aria-label="选择日期"
          defaultValue={dateValue}
        />
        <button>查看</button>
      </Form>
      <div className="quick">
        <button type="button" onClick={() => go({ month: now.getMonth() + 1, day: now.getDate() })}>
          今天
        </button>
        <button type="button" onClick={() => go(shiftDate(month, day, -1))}>
          ← 前一天
        </button>
        <button type="button" onClick={() => go(shiftDate(month, day, 1))}>
          后一天 →
        </button>
      </div>
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} />
      ) : !data?.total ? (
        <EmptyState message={`${month}月${day}日暂无日记`} />
      ) : (
        <>
          <p className="meta">
            {month} 月 {day} 日 · 共 {data.total} 篇
          </p>
          {data.groups.map((g) => (
            <section key={g.year}>
              <h2>{g.year} 年</h2>
              {g.items.map((e) => (
                <EntryCard key={e.id} entry={e} />
              ))}
            </section>
          ))}
        </>
      )}
    </>
  )
}
