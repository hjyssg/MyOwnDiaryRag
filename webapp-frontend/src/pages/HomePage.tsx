import { Link } from 'react-router-dom'
import { getYears } from '../api/entries'
import { ErrorState, LoadingState, EmptyState } from '../components/States'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function HomePage() {
  useDocumentTitle('首页')
  const { data, error, loading } = useApi(getYears, [])
  if (loading) return <LoadingState />
  if (error) return <ErrorState message={error} />
  if (!data?.length) return <EmptyState message="暂无日记，请先运行导入脚本。" />
  const entries = data.reduce((n, y) => n + y.entries, 0)
  const words = data.reduce((n, y) => n + y.words, 0)
  return (
    <div className="home-page">
      <section className="home-hero">
        <div>
          <h1>我的日记</h1>
          <dl className="home-stats">
            <div>
              <dt>{data.length}</dt>
              <dd>个年份</dd>
            </div>
            <div>
              <dt>{entries.toLocaleString()}</dt>
              <dd>篇日记</dd>
            </div>
            <div>
              <dt>{words.toLocaleString()}</dt>
              <dd>字数</dd>
            </div>
          </dl>
        </div>
      </section>
      <div className="home-rule" />
      <section className="home-actions" aria-label="日记入口">
        <Link to="/on-this-day" className="archive-action">
          <span className="action-symbol" aria-hidden="true">
            ▣
          </span>
          <h2>过去的今天</h2>
          <p>查看同月同日的历史记录。</p>
          <strong>去看看 →</strong>
        </Link>
        <Link to="/random" className="archive-action">
          <span className="action-symbol" aria-hidden="true">
            ⌁
          </span>
          <h2>随机回忆</h2>
          <p>随机打开一个有记录的日期。</p>
          <strong>开始回忆 →</strong>
        </Link>
      </section>
      <section className="year-browser">
        <h2>按年份浏览</h2>
        <div>
          {data.map((year) => (
            <Link key={year.year} to={`/browse?year=${year.year}`}>
              {year.year}
            </Link>
          ))}
        </div>
      </section>
    </div>
  )
}
