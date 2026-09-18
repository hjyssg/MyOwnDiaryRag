export interface EntryPreview {
  id: number
  date: string
  year: number
  month: number
  day: number
  entry_type: string
  word_count: number
  preview: string
}
export interface EntryDetail extends EntryPreview {
  content: string
  file_source?: string | null
  previous_entry: AdjacentEntry | null
  next_entry: AdjacentEntry | null
}
export interface FullEntry extends EntryPreview {
  content: string
  file_source?: string | null
}
export interface FullEntryListResponse {
  total: number
  items: FullEntry[]
  year: number | null
  month: number | null
  entry_type: string | null
  query: string | null
}
export interface AdjacentEntry {
  id: number
  date: string
  entry_type: string
}
export interface Page<T> {
  total: number
  page: number
  per_page: number
  pages: number
  items: T[]
}
export interface YearStat {
  year: number
  entries: number
  words: number
}
export interface MonthStat {
  month: number
  entries: number
  words: number
}
export interface TypeStat {
  entry_type: string
  entries: number
  words: number
}
export interface WeekdayStat {
  weekday: number
  entries: number
}
export interface StatisticsResponse {
  total_entries: number
  total_words: number
  average_words: number
  first_date: string | null
  last_date: string | null
  most_active_year: YearStat | null
  longest_entry: { id: number; date: string; entry_type: string; word_count: number } | null
  most_repeated_date: { month: number; day: number; entries: number } | null
  years: YearStat[]
  entry_types: TypeStat[]
  months: MonthStat[]
  weekdays: WeekdayStat[]
}
export interface OnThisDayItem {
  id: number
  date: string
  year: number
  entry_type: string
  word_count: number
  preview: string
}
export interface OnThisDayResponse {
  month: number
  day: number
  total: number
  groups: { year: number; items: OnThisDayItem[] }[]
}
export interface RandomDayItem extends EntryPreview {
  content: string
}
export interface RandomDayResponse {
  date: string
  year: number
  month: number
  day: number
  total: number
  items: RandomDayItem[]
}
export interface SummaryItem {
  entry_key: string | null
  entry_id: number | null
  entry_date: string | null
  entry_type: string | null
  word_count: number | null
  status: 'ok' | 'empty' | 'failed' | 'missing' | 'stale'
  summary: string
  emotion: string
  emotion_status: 'ok' | 'empty' | 'failed' | 'missing' | 'stale' | null
  model: string | null
  generated_at: string | null
}
export interface EmotionCount {
  emotion: string
  count: number
}
export interface EmotionListResponse {
  items: EmotionCount[]
}
