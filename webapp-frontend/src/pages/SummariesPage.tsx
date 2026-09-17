import { Form, Link, useSearchParams } from 'react-router-dom'
import { getEmotionLabels, getSummaries } from '../api/summaries'
import { Pagination } from '../components/Pagination'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function SummariesPage() {
  useDocumentTitle('日记摘要')
  const [p] = useSearchParams()
  const key = p.toString()
  const params = Object.fromEntries(p)
  const { data, error, loading } = useApi((s) => getSummaries(params, s), [key])
  const { data: emotions } = useApi((s) => getEmotionLabels(s), [])
  const currentEmotion = p.get('emotion') ?? ''
  const emotionItems = emotions?.items ?? []
  const emotionOptions =
    currentEmotion && !emotionItems.some((e) => e.emotion === currentEmotion)
      ? [{ emotion: currentEmotion, count: 0 }, ...emotionItems]
      : emotionItems
  return (
    <>
      <h1>日记摘要</h1>
      <Form className="filters">
        <input name="year" defaultValue={p.get('year') ?? ''} placeholder="年份" />
        <input name="month" defaultValue={p.get('month') ?? ''} placeholder="月份" />
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
          {data.items.map((item) => (
            <article className="card" key={item.entry_key}>
              <div>
                <strong>{item.entry_date}</strong>
                <span className={`badge ${item.status}`}>{item.status}</span>
                {item.emotion && <span className="badge emotion">{item.emotion}</span>}
              </div>
              <p>{item.summary || '暂无有效摘要'}</p>
              <small>
                {item.model} · {item.generated_at} ·{' '}
                {item.entry_id && <Link to={`/entries/${item.entry_id}`}>查看原文</Link>}
              </small>
            </article>
          ))}
          <Pagination page={data.page} pages={data.pages} />
        </>
      )}
    </>
  )
}
