import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BrowsePage } from './BrowsePage'

const entriesPage = {
  total: 123,
  page: 1,
  per_page: 50,
  pages: 3,
  items: [
    {
      id: 1,
      date: '2024-09-17',
      year: 2024,
      month: 9,
      day: 17,
      entry_type: 'diary',
      word_count: 12,
      preview: '旅行与朋友聚会',
    },
  ],
  year: 2024,
  month: null,
  entry_type: null,
  query: null,
}
const years = [{ year: 2024, entries: 123, words: 900 }]
const months = [{ month: 9, entries: 12, words: 90 }]

function bodyFor(url: string) {
  if (url.includes('/api/years')) return years
  if (url.includes('/api/months')) return months
  return entriesPage
}
function stubFetch() {
  const calls: string[] = []
  const impl = (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    return Promise.resolve(
      new Response(JSON.stringify(bodyFor(url)), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  }
  vi.stubGlobal('fetch', vi.fn(impl))
  return calls
}
function renderPage(entry = '/browse') {
  const router = createMemoryRouter(
    [
      { path: '/browse', element: <BrowsePage /> },
      { path: '/entries/:id', element: <div>原文</div> },
    ],
    { initialEntries: [entry] },
  )
  return render(<RouterProvider router={router} />)
}
afterEach(() => vi.restoreAllMocks())

describe('浏览页分页与筛选', () => {
  it('默认每页 50 篇并显示条目区间', async () => {
    const calls = stubFetch()
    renderPage('/browse?year=2024')

    expect(await screen.findByText('旅行与朋友聚会')).toBeInTheDocument()
    expect(calls.some((url) => url.includes('/api/entries?') && url.includes('per_page=50'))).toBe(
      true,
    )
    expect(screen.getByText('第 1–50 篇 / 共 123 篇')).toBeInTheDocument()
  })

  it('URL 里的 per_page 优先，年份候选来自 /api/years', async () => {
    const calls = stubFetch()
    renderPage('/browse?year=2024&per_page=100')

    expect(await screen.findByText('旅行与朋友聚会')).toBeInTheDocument()
    expect(calls.some((url) => url.includes('per_page=100'))).toBe(true)
    const yearInput = document.querySelector('input[name="year"]') as HTMLInputElement
    expect(yearInput.value).toBe('2024')
    const options = [...document.querySelectorAll('#filter-years option')].map((o) =>
      o.getAttribute('value'),
    )
    expect(options).toEqual(['2024'])
  })

  it('非法的年 / 月不会传给后端', async () => {
    const calls = stubFetch()
    renderPage('/browse?year=20&month=99')

    expect(await screen.findByText('旅行与朋友聚会')).toBeInTheDocument()
    const entriesCall = calls.find((url) => url.includes('/api/entries'))
    expect(entriesCall).toBeDefined()
    expect(entriesCall).not.toContain('year=')
    expect(entriesCall).not.toContain('month=')
  })
})
