import { Form, Link, useSearchParams } from 'react-router-dom'
import { yearMonthParams } from '../api/filters'
import { getEmotionLabels, getSummaries } from '../api/summaries'
import { Pagination } from '../components/Pagination'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { YearMonthFilter } from '../components/YearMonthFilter'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const sumEmotionCounts = (items: { emotion: string }[]) =>
  items.reduce<Record<string, number>>((counts, item) => {
    if (item.emotion) counts[item.emotion] = (counts[item.emotion] ?? 0) + 1
    return counts
  }, {})

export function SummariesPage() {
  useDocumentTitle('日记摘要')
  const [p] = useSearchParams()
  const key = p.toString()
  const { year, month } = yearMonthParams(p)
  const params = {
    year,
    month,
    entry_type: p.get('entry_type') ?? undefined,
    emotion: p.get('emotion') ?? undefined,
    q: p.get('q') ?? undefined,
    status: p.get('status') ?? 'ok',
    page: p.get('page') ?? undefined,
  }
  const { data, error, loading } = useApi((s) => getSummaries(params, s), [key])
  const { data: emotions } = useApi((s) => getEmotionLabels(s), [])
  const currentEmotion = p.get('emotion') ?? ''
  const emotionItems = emotions?.items ?? []
  const emotionOptions =
    currentEmotion && !emotionItems.some((e) => e.emotion === currentEmotion)
      ? [{ emotion: currentEmotion, count: 0 }, ...emotionItems]
      : emotionItems
  const emotionCounts = sumEmotionCounts(data?.items ?? [])
  const emotionTotal = Object.values(emotionCounts).reduce((total, count) => total + count, 0)
  return (
    <div className="summaries-page">
      <header className="page-intro">
        <h1>AI 人生摘要</h1>
      </header>
      <Form className="filters">
        <YearMonthFilter year={p.get('year') ?? ''} month={p.get('month') ?? ''} />
        <input name="entry_type" defaultValue={p.get('entry_type') ?? ''} placeholder="类型" />
        {emotions && (
          <select name="emotion" defaultValue={currentEmotion}>
            <option value="">全部情绪</option>
            {emotionOptions.map((e) => (
              <option key={e.emotion} value={e.emotion}>
                {e.count ? `${e.emotion} (${e.count})` : e.emotion}
              </option>
            ))}
          </select>
        )}
        <input name="q" defaultValue={p.get('q') ?? ''} placeholder="搜索摘要" />
        <select name="status" defaultValue={p.get('status') ?? 'ok'}>
          <option value="ok">有效摘要</option>
          <option value="all">全部状态</option>
          <option value="empty">空摘要</option>
          <option value="failed">失败</option>
        </select>
        <button>筛选</button>
      </Form>
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} />
      ) : !data?.items.length ? (
        <EmptyState message="暂无摘要，请先运行 batch_summary --all。" />
      ) : (
        <>
          <section className="summary-overview">
            <div>
              <span className="overview-year">{year ?? '全部'}</span>
              <small>{data.total} 篇摘要</small>
            </div>
          </section>
          {emotionTotal > 0 && (
            <section className="emotion-distribution">
              <h2>情绪分布</h2>
              <div className="emotion-bar" aria-label="当前摘要的情绪分布">
                {Object.entries(emotionCounts).map(([emotion, count]) => (
                  <span key={emotion} style={{ flex: count }} title={`${emotion} ${count} 篇`} />
                ))}
              </div>
              <div className="emotion-key">
                {Object.entries(emotionCounts).map(([emotion, count]) => (
                  <span key={emotion}>
                    {emotion} {Math.round((count / emotionTotal) * 100)}%
                  </span>
                ))}
              </div>
            </section>
          )}
          <section className="summary-list" aria-label="日记摘要列表">
            <h2>摘要记录</h2>
            {data.items.map((item) => (
              <article className="summary-item" key={item.entry_key}>
                <time>{item.entry_date}</time>
                <div>
                  <div className="summary-item-meta">
                    <span className={`badge ${item.status}`}>{item.status}</span>
                    {item.emotion && <span className="badge emotion">{item.emotion}</span>}
                  </div>
                  <p>{item.summary || '暂无有效摘要'}</p>
                  <small>
                    {item.model} · {item.generated_at} ·{' '}
                    {item.entry_id && <Link to={`/entries/${item.entry_id}`}>查看原文</Link>}
                  </small>
                </div>
              </article>
            ))}
          </section>
          <Pagination page={data.page} pages={data.pages} />
        </>
      )}
    </div>
  )
}
