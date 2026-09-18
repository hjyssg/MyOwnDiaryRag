import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getRandom } from '../api/entries'
import { ErrorState, LoadingState } from '../components/States'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { entryTypeLabel } from '../components/entryTypes'

export function RandomPage() {
  useDocumentTitle('随机一天')
  const [nonce, setNonce] = useState(0)
  const { data, error, loading } = useApi(getRandom, [nonce])
  return (
    <div className="random-page">
      <header className="page-intro">
        <h1>随机回忆</h1>
      </header>
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} />
      ) : (
        data && (
          <section className="random-memory">
            <span className="random-symbol" aria-hidden="true">
              ⌁
            </span>
            <h2>{data.date}</h2>
            <p>那一天，你写了 {data.total} 篇日记。</p>
            <button onClick={() => setNonce((n) => n + 1)}>再来一次 ↻</button>
            <div className="random-entries">
              {data.items.map((entry) => (
                <article key={entry.id}>
                  <header>
                    <span>{entryTypeLabel(entry.entry_type)}</span>
                    <small>{entry.word_count.toLocaleString()} 字</small>
                  </header>
                  <div className="content">{entry.content}</div>
                  <Link to={`/entries/${entry.id}`}>沉浸阅读 →</Link>
                </article>
              ))}
            </div>
          </section>
        )
      )}
    </div>
  )
}
