import { Link, useNavigate, useParams } from 'react-router-dom'
import { getEntry } from '../api/entries'
import { getEntrySummary } from '../api/summaries'
import { ErrorState, LoadingState } from '../components/States'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useNavigationShortcuts } from '../hooks/useNavigationShortcuts'
import { entryTypeLabel } from '../components/entryTypes'

const labels: Record<string, string> = {
  missing: '暂无摘要',
  stale: '原文或算法已变化，摘要待更新',
  empty: '本次未生成有效摘要',
  failed: '生成失败，将在下次运行时重试',
}
export function EntryPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  useDocumentTitle('阅读日记')
  const entry = useApi((s) => getEntry(id, s), [id])
  const summary = useApi((s) => getEntrySummary(id, s), [id])
  const previous = entry.data?.previous_entry
  const next = entry.data?.next_entry
  useNavigationShortcuts({
    previous: previous ? () => navigate(`/entries/${previous.id}`) : undefined,
    next: next ? () => navigate(`/entries/${next.id}`) : undefined,
  })
  if (entry.loading) return <LoadingState />
  if (entry.error || !entry.data) return <ErrorState message={entry.error || '日记不存在'} />
  const date = new Date(`${entry.data.date}T12:00:00`)
  return (
    <article className="entry-page">
      <Link className="back-link" to="/browse">
        ← 返回列表
      </Link>
      <header className="entry-header">
        <div className="entry-date-block">
          <span>{date.getFullYear()}</span>
          <time dateTime={entry.data.date}>
            {date.getMonth() + 1} / {date.getDate()}
          </time>
          <small>{date.toLocaleDateString('zh-CN', { weekday: 'short' })}</small>
        </div>
        <div className="entry-kind">
          <span className={`tag tag-${entry.data.entry_type}`}>
            {entryTypeLabel(entry.data.entry_type)}
          </span>
          <small>{entry.data.word_count.toLocaleString()} 字</small>
        </div>
      </header>
      <section className="summary-card" aria-label="AI 摘要">
        <h2>
          <span aria-hidden="true">◌</span> AI 摘要
        </h2>
        {summary.loading ? (
          <LoadingState />
        ) : summary.error ? (
          <ErrorState message={summary.error} />
        ) : summary.data?.status === 'ok' ? (
          <>
            <p>{summary.data.summary}</p>
            <small>
              {summary.data.model} · {summary.data.generated_at}
            </small>
          </>
        ) : (
          <p>{labels[summary.data?.status ?? 'missing']}</p>
        )}
      </section>
      <div className="content">{entry.data.content}</div>
      <nav className="entry-footer-nav" aria-label="阅读导航">
        {previous ? (
          <Link to={`/entries/${previous.id}`}>
            ← 上一篇
            <small>{previous.date}</small>
          </Link>
        ) : (
          <span />
        )}
        {next ? (
          <Link to={`/entries/${next.id}`}>
            下一篇 →<small>{next.date}</small>
          </Link>
        ) : (
          <span />
        )}
      </nav>
      <p className="shortcut-hint">快捷键：← 上一篇，→ 下一篇</p>
    </article>
  )
}
