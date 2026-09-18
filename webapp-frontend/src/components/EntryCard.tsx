import { Link } from 'react-router-dom'
import type { EntryPreview, OnThisDayItem } from '../api/types'
import { entryTypeLabel } from './entryTypes'

export function EntryCard({ entry }: { entry: EntryPreview | OnThisDayItem }) {
  return (
    <article className="timeline-entry">
      <div className="timeline-date">
        <time dateTime={entry.date}>
          {'day' in entry ? entry.day : Number(entry.date.slice(-2))}
        </time>
        <small>
          {new Date(`${entry.date}T12:00:00`).toLocaleDateString('zh-CN', { weekday: 'short' })}
        </small>
        <span className={`tag tag-${entry.entry_type}`}>{entryTypeLabel(entry.entry_type)}</span>
      </div>
      <div className="timeline-line" aria-hidden="true" />
      <div className="entry-copy">
        <p>{entry.preview}</p>
        <Link to={`/entries/${entry.id}`} className="entry-read-link">
          查看原文 →
        </Link>
      </div>
    </article>
  )
}
