import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RandomPage } from './RandomPage'

const day = {
  date: '2023-09-17',
  year: 2023,
  month: 9,
  day: 17,
  total: 1,
  items: [
    {
      id: 7,
      date: '2023-09-17',
      year: 2023,
      month: 9,
      day: 17,
      entry_type: 'diary',
      word_count: 6,
      preview: '旧年旅行记录…',
      content: '旧年旅行记录：这是完整的正文内容，不是 120 字预览。',
    },
  ],
}

function stubFetch() {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      calls.push(String(input))
      return Promise.resolve(
        new Response(JSON.stringify(day), {
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
      { path: '/entries/:id', element: <div>原文</div> },
    ],
    { initialEntries: ['/random'] },
  )
  return render(<RouterProvider router={router} />)
}
afterEach(() => vi.restoreAllMocks())

describe('随机一天', () => {
  it('直接展示全文而不是预览', async () => {
    const calls = stubFetch()
    renderPage()

    expect(
      await screen.findByText('旧年旅行记录：这是完整的正文内容，不是 120 字预览。'),
    ).toBeInTheDocument()
    expect(calls.filter((url) => url.includes('/api/random'))).toHaveLength(1)
  })
})
