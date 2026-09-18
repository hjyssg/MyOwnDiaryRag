import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RandomPage } from './RandomPage'

const singleDay = {
  date: '2026-04-16',
  year: 2026,
  month: 4,
  day: 16,
  total: 1,
  items: [
    {
      id: 7,
      date: '2026-04-16',
      year: 2026,
      month: 4,
      day: 16,
      entry_type: 'diary',
      word_count: 6,
      preview: '旧年旅行记录…',
      content: '旧年旅行记录：这是完整的正文内容，不是 120 字预览。',
    },
  ],
}

const multiDay = {
  date: '2026-04-16',
  year: 2026,
  month: 4,
  day: 16,
  total: 2,
  items: [
    {
      id: 7,
      date: '2026-04-16',
      year: 2026,
      month: 4,
      day: 16,
      entry_type: 'diary',
      word_count: 6,
      preview: '第一篇预览…',
      content: '第一篇的完整正文。',
    },
    {
      id: 8,
      date: '2026-04-16',
      year: 2026,
      month: 4,
      day: 16,
      entry_type: 'diary',
      word_count: 6,
      preview: '第二篇预览…',
      content: '第二篇的完整正文。',
    },
  ],
}

function stubFetch(payload: typeof singleDay | typeof multiDay) {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      calls.push(String(input))
      return Promise.resolve(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    }),
  )
  return calls
}
function renderPage() {
  const router = createMemoryRouter(
    [
      { path: '/random', element: <RandomPage /> },
      { path: '/on-this-day', element: <div>日期查找</div> },
      { path: '/entries/:id', element: <div>原文</div> },
    ],
    { initialEntries: ['/random'] },
  )
  return render(<RouterProvider router={router} />)
}
afterEach(() => vi.restoreAllMocks())

describe('随机一天', () => {
  it('只有一篇时直接展示全文，不再放进限高的滚动框', async () => {
    const calls = stubFetch(singleDay)
    renderPage()

    const content = await screen.findByText('旧年旅行记录：这是完整的正文内容，不是 120 字预览。')
    expect(content).toBeInTheDocument()
    expect(content.closest('.random-entries')).toHaveClass('single')
    expect(calls.filter((url) => url.includes('/api/random'))).toHaveLength(1)
  })

  it('顶部只有一行紧凑 meta：日期 + 篇数 + 再来一次', async () => {
    stubFetch(singleDay)
    renderPage()

    const meta = await screen.findByText('那一天，你写了 1 篇日记。')
    expect(meta.closest('.random-bar')).not.toBeNull()
    expect(screen.getByText('2026-04-16').closest('.random-bar')).not.toBeNull()
    expect(screen.getByRole('button', { name: '再来一次 ↻' })).toBeInTheDocument()
  })

  it('多篇时仍走列表形态（不带 single）', async () => {
    stubFetch(multiDay)
    renderPage()

    const content = await screen.findByText('第一篇的完整正文。')
    expect(content.closest('.random-entries')).not.toHaveClass('single')
    expect(screen.getByText('第二篇的完整正文。')).toBeInTheDocument()
  })

  it('点日期进入「日期查找」页，并带上该日期的月 / 日参数', async () => {
    stubFetch(singleDay)
    renderPage()

    const link = await screen.findByRole('link', { name: '2026-04-16' })
    expect(link).toHaveAttribute('href', '/on-this-day?month=4&day=16')
  })
})
