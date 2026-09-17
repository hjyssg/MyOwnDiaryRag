import { useState } from 'react'
import { Link } from 'react-router-dom'
import { getRandom } from '../api/entries'
import { ErrorState, LoadingState } from '../components/States'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function RandomPage() {
  useDocumentTitle('随机一天')
  const [nonce, setNonce] = useState(0)
  const { data, error, loading } = useApi(getRandom, [nonce])
  return (
    <>
      <h1>随机一天</h1>
      <button onClick={() => setNonce((n) => n + 1)}>再随机一天</button>
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} />
      ) : (
        data && (
          <>
            <h2>
              {data.date}
              <span className="meta">共 {data.total} 篇</span>
            </h2>
            {data.items.map((e) => (
              <article className="card" key={e.id}>
                <div>
                  <span className="card-title">{e.date}</span>
                  <span className="meta">
                    {e.entry_type} · {e.word_count} 字
                  </span>
                </div>
                <div className="content">{e.content}</div>
                <small>
                  <Link to={`/entries/${e.id}`}>查看摘要</Link>
                </small>
              </article>
            ))}
          </>
        )
      )}
    </>
  )
}
