import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { StatisticsPage } from './StatisticsPage'

const statistics = {
  total_entries: 13,
  total_words: 760,
  average_words: 58,
  first_date: '2021-09-17',
  last_date: '2025-04-20',
  most_active_year: { year: 2024, entries: 4, words: 235 },
  longest_entry: { id: 10, date: '2024-09-17', entry_type: 'diary', word_count: 63 },
  most_repeated_date: { month: 9, day: 17, entries: 4 },
  years: [{ year: 2024, entries: 4, words: 235 }],
  entry_types: [{ entry_type: 'diary', entries: 7, words: 400 }],
  months: [{ month: 9, entries: 4, words: 230 }],
  weekdays: [{ weekday: 0, entries: 3 }],
}

afterEach(() => vi.restoreAllMocks())

describe('统计页', () => {
  it('展示后端返回的全库统计，并提供关联跳转', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(JSON.stringify(statistics)))),
    )
    const router = createMemoryRouter([{ path: '/statistics', element: <StatisticsPage /> }], {
      initialEntries: ['/statistics'],
    })
    render(<RouterProvider router={router} />)

    expect(await screen.findByText('13')).toBeInTheDocument()
    expect(screen.getByText('记录最多年份')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: '2024 年，4 篇日记' })).toHaveAttribute(
      'href',
      '/browse?year=2024',
    )
    expect(screen.getByRole('link', { name: /9 月 17 日 · 4 篇/ })).toHaveAttribute(
      'href',
      '/on-this-day?month=9&day=17',
    )
  })
})
