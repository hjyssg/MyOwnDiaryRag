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
  const entries = data.reduce((n, y) => n + y.entries, 0),
    words = data.reduce((n, y) => n + y.words, 0)
  return (
    <>
      <section className="hero">
        <h1>我的日记</h1>
        <p>
          {data.length} 个年份 · {entries} 篇 · {words.toLocaleString()} 字
        </p>
      </section>
      <div className="grid">
        {data.map((y) => (
          <Link className="year-card" key={y.year} to={`/browse?year=${y.year}`}>
            <strong>{y.year}</strong>
            <span>
              {y.entries} 篇 · {y.words.toLocaleString()} 字
            </span>
          </Link>
        ))}
      </div>
    </>
  )
}
