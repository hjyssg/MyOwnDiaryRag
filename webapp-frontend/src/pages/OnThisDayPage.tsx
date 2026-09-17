import { Form, useSearchParams } from 'react-router-dom'
import { getOnThisDay } from '../api/entries'
import { EntryCard } from '../components/EntryCard'
import { EmptyState, ErrorState, LoadingState } from '../components/States'
import { useApi } from '../hooks/useApi'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

export function OnThisDayPage() {
  useDocumentTitle('过去的今天')
  const [p] = useSearchParams()
  const now = new Date()
  const month = Number(p.get('month') || now.getMonth() + 1),
    day = Number(p.get('day') || now.getDate())
  const { data, error, loading } = useApi((s) => getOnThisDay(month, day, s), [month, day])
  return (
    <>
      <h1>过去的今天</h1>
      <Form className="filters">
        <input name="month" type="number" min="1" max="12" defaultValue={month} />
        <input name="day" type="number" min="1" max="31" defaultValue={day} />
        <button>查看</button>
      </Form>
      {loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} />
      ) : !data?.total ? (
        <EmptyState message={`${month}月${day}日暂无日记`} />
      ) : (
        data.groups.map((g) => (
          <section key={g.year}>
            <h2>{g.year} 年</h2>
            {g.items.map((e) => (
              <EntryCard key={e.id} entry={e} />
            ))}
          </section>
        ))
      )}
    </>
  )
}
