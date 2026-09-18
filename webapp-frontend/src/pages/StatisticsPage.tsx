import { Link } from 'react-router-dom'
import { getStatistics } from '../api/entries'
import { entryTypeLabel } from '../components/entryTypes'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

export function StatisticsPage() {
  useDocumentTitle('统计')
  const { data, error, loading } = useApi(getStatistics, [])
  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />
  if (!data?.total_entries) return <EmptyState message="暂无可统计的日记。" />
  const maxYearEntries = Math.max(...data.years.map((item) => item.entries), 1)
  const maxMonthEntries = Math.max(...data.months.map((item) => item.entries), 1)
  const maxWeekdayEntries = Math.max(...data.weekdays.map((item) => item.entries), 1)
  return (
    <div className="statistics-page">
      <header className="page-intro">
        <h1>统计</h1>
        <p>基于全部日记记录计算。</p>
      </header>
      <section className="stat-kpis" aria-label="总览">
        <div>
          <strong>{data.total_entries.toLocaleString()}</strong>
          <span>篇日记</span>
        </div>
        <div>
          <strong>{data.total_words.toLocaleString()}</strong>
          <span>总字数</span>
        </div>
        <div>
          <strong>{data.average_words.toLocaleString()}</strong>
          <span>平均每篇字数</span>
        </div>
        <div>
          <strong>{data.first_date ?? '—'}</strong>
          <span>最早记录</span>
        </div>
      </section>
      <section className="stat-facts" aria-label="记录亮点">
        {data.most_active_year && (
          <Link to={`/browse?year=${data.most_active_year.year}`}>
            <span>记录最多年份</span>
            <strong>
              {data.most_active_year.year} 年 · {data.most_active_year.entries} 篇
            </strong>
          </Link>
        )}
        {data.longest_entry && (
          <Link to={`/entries/${data.longest_entry.id}`}>
            <span>最长单篇</span>
            <strong>
              {data.longest_entry.date} · {data.longest_entry.word_count.toLocaleString()} 字
            </strong>
          </Link>
        )}
        {data.most_repeated_date && (
          <Link
            to={`/on-this-day?month=${data.most_repeated_date.month}&day=${data.most_repeated_date.day}`}
          >
            <span>最常记录日期</span>
            <strong>
              {data.most_repeated_date.month} 月 {data.most_repeated_date.day} 日 ·{' '}
              {data.most_repeated_date.entries} 篇
            </strong>
          </Link>
        )}
      </section>
      <div className="statistics-grid">
        <section className="stat-panel">
          <h2>按年份</h2>
          <div className="year-chart-scroll">
            <div className="year-chart" aria-label="按年份的日记篇数">
              {data.years.map((item) => (
                <Link
                  key={item.year}
                  to={`/browse?year=${item.year}`}
                  aria-label={`${item.year} 年，${item.entries} 篇日记`}
                >
                  <strong>{item.entries}</strong>
                  <i style={{ height: `${Math.max((item.entries / maxYearEntries) * 100, 4)}%` }} />
                  <span>{item.year}</span>
                </Link>
              ))}
            </div>
          </div>
        </section>
        <section className="stat-panel">
          <h2>日记类型</h2>
          <div className="type-list">
            {data.entry_types.map((item) => (
              <Link key={item.entry_type} to={`/browse?entry_type=${item.entry_type}`}>
                <span>{entryTypeLabel(item.entry_type)}</span>
                <strong>{item.entries}</strong>
                <small>{item.words.toLocaleString()} 字</small>
              </Link>
            ))}
          </div>
        </section>
        <section className="stat-panel">
          <h2>按月份</h2>
          <div className="bar-list compact">
            {data.months.map((item) => (
              <Link key={item.month} to={`/browse?month=${item.month}`}>
                <span>{item.month} 月</span>
                <i>
                  <b style={{ width: `${(item.entries / maxMonthEntries) * 100}%` }} />
                </i>
                <small>{item.entries} 篇</small>
              </Link>
            ))}
          </div>
        </section>
        <section className="stat-panel">
          <h2>按星期</h2>
          <div className="bar-list compact">
            {data.weekdays.map((item) => (
              <div key={item.weekday}>
                <span>{weekdays[item.weekday]}</span>
                <i>
                  <b style={{ width: `${(item.entries / maxWeekdayEntries) * 100}%` }} />
                </i>
                <small>{item.entries} 篇</small>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  )
}
