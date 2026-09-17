import { useState } from 'react'
import { getMonths, getYears } from '../api/entries'
import { MAX_YEAR, MIN_YEAR, normalizeYear } from '../api/filters'
import { useApi } from '../hooks/useApi'

interface MonthOption {
  month: number
  label: string
}

/**
 * 年 / 月筛选：两个原生 input，直接打字输入即可，
 * 同时用原生 datalist 列出"有哪些年份 / 月份"（年份来自 /api/years，月份来自 /api/months）。
 */
export function YearMonthFilter({ year = '', month = '' }: { year?: string; month?: string }) {
  const [yearInput, setYearInput] = useState(year)
  const [monthInput, setMonthInput] = useState(month)
  const { data: years } = useApi(getYears, [])
  const selectedYear = normalizeYear(yearInput)
  const { data: months } = useApi(
    (s) => (selectedYear === undefined ? Promise.resolve([]) : getMonths(selectedYear, s)),
    [selectedYear],
  )
  const monthOptions: MonthOption[] = months?.length
    ? months.map((m) => ({ month: m.month, label: `${m.entries} 篇` }))
    : Array.from({ length: 12 }, (_, i) => ({ month: i + 1, label: `${i + 1} 月` }))
  return (
    <>
      <input
        name="year"
        type="number"
        inputMode="numeric"
        min={MIN_YEAR}
        max={MAX_YEAR}
        list="filter-years"
        placeholder="年份（可留空）"
        aria-label="年份"
        value={yearInput}
        onChange={(e) => setYearInput(e.target.value)}
      />
      <datalist id="filter-years">
        {(years ?? []).map((y) => (
          <option key={y.year} value={y.year} label={`${y.entries} 篇`} />
        ))}
      </datalist>
      <input
        name="month"
        type="number"
        inputMode="numeric"
        min={1}
        max={12}
        list="filter-months"
        placeholder="月份 1-12（可留空）"
        aria-label="月份"
        value={monthInput}
        onChange={(e) => setMonthInput(e.target.value)}
      />
      <datalist id="filter-months">
        {monthOptions.map((m) => (
          <option key={m.month} value={m.month} label={m.label} />
        ))}
      </datalist>
    </>
  )
}
