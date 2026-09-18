import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SummariesPage } from './SummariesPage'

const summary = {
  total: 1,
  page: 1,
  per_page: 20,
  pages: 1,
  items: [
    {
      entry_key: 'v1:2024-09-17:note',
      entry_id: 1,
      entry_date: '2024-09-17',
      entry_type: 'note',
      word_count: 6,
      status: 'ok',
      summary: '被同事甩锅',
      emotion: '生气',
      emotion_status: 'ok',
      model: 'm',
      generated_at: '2026-01-01T00:00:00',
    },
  ],
}
const emotions = {
  items: [
    { emotion: '快乐', count: 0 },
    { emotion: '生气', count: 1 },
  ],
}
// 摘要页复用的年 / 月筛选组件会请求这两个统计接口
const years = [{ year: 2024, entries: 1, words: 6 }]
const months = [{ month: 9, entries: 1, words: 6 }]
function bodyFor(url: string) {
  if (url.includes('/api/summaries/emotions')) return emotions
  if (url.includes('/api/years')) return years
  if (url.includes('/api/months')) return months
  return summary
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
function renderPage(entry = '/') {
  const router = createMemoryRouter(
    [
      { path: '/', element: <SummariesPage /> },
      { path: '/entries/:id', element: <div>原文</div> },
    ],
    { initialEntries: [entry] },
  )
  return render(<RouterProvider router={router} />)
}
afterEach(() => vi.restoreAllMocks())
describe('摘要页情绪筛选', () => {
  it('下拉展示标签集并渲染情绪徽章', async () => {
    const calls = stubFetch()
    renderPage()
    expect(await screen.findByText('被同事甩锅')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '生气 (1)' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: '快乐' })).toBeInTheDocument()
    expect(screen.getByText('生气', { selector: 'span.badge.emotion' })).toBeInTheDocument()
    expect(calls.some((url) => url.includes('/api/summaries/emotions'))).toBe(true)
  })
  it('URL 中的 emotion 会带进查询参数与下拉默认值', async () => {
    const calls = stubFetch()
    renderPage('/?emotion=%E7%94%9F%E6%B0%94&status=all')
    expect(await screen.findByRole('option', { name: '生气 (1)' })).toBeInTheDocument()
    const select = document.querySelector('select[name="emotion"]') as HTMLSelectElement
    expect(select.value).toBe('生气')
    expect(calls.some((url) => url.includes('emotion='))).toBe(true)
  })
  it('类型下拉与浏览页同款（同一个 EntryTypeFilter），并按 URL 回填', async () => {
    const calls = stubFetch()
    renderPage('/?entry_type=note')
    expect(await screen.findByText('被同事甩锅')).toBeInTheDocument()

    const select = document.querySelector('select[name="entry_type"]') as HTMLSelectElement
    expect(select).not.toBeNull()
    expect(select.value).toBe('note')
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual([
      '全部类型',
      '普通日记',
      '股票日记',
      '回顾',
      '总结',
      '随手记',
    ])
    expect(calls.some((url) => url.includes('entry_type=note'))).toBe(true)
  })
})
