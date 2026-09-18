import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
function bodyFor() {
  return entriesPage
}
function stubFetch() {
  const calls: string[] = []
  const impl = (input: RequestInfo | URL) => {
    const url = String(input)
    calls.push(url)
    return Promise.resolve(
      new Response(JSON.stringify(bodyFor()), {
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
    expect(screen.getByRole('link', { name: '查看原文 →' })).toHaveAttribute('href', '/entries/1')
    expect(screen.getAllByText('日记')).toHaveLength(1)
    expect(screen.queryByText('12 字')).not.toBeInTheDocument()
  })

  it('URL 里的 per_page 优先，年份显示在文本输入框中', async () => {
    const calls = stubFetch()
    renderPage('/browse?year=2024&per_page=100')

    expect(await screen.findByText('旅行与朋友聚会')).toBeInTheDocument()
    expect(calls.some((url) => url.includes('per_page=100'))).toBe(true)
    const yearInput = document.querySelector('input[name="year"]') as HTMLInputElement
    expect(yearInput.type).toBe('text')
    expect(yearInput.value).toBe('2024')
    expect(calls.some((url) => url.includes('/api/years'))).toBe(false)
    expect(calls.some((url) => url.includes('/api/months'))).toBe(false)
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

  it('完整正文模式请求全文接口、显示正文且不显示分页', async () => {
    const fullEntries = {
      total: 1,
      items: [{ ...entriesPage.items[0], content: '这是完整日记正文。' }],
      year: 2024,
      month: 9,
      entry_type: null,
      query: null,
    }
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        calls.push(url)
        return Promise.resolve(
          new Response(
            JSON.stringify(url.includes('/api/entries/full') ? fullEntries : entriesPage),
          ),
        )
      }),
    )
    renderPage('/browse?year=2024&month=9&full=1')

    expect(await screen.findByText('这是完整日记正文。')).toBeInTheDocument()
    expect(calls.some((url) => url.includes('/api/entries/full?'))).toBe(true)
    expect(calls.some((url) => url.includes('/api/entries?') && !url.includes('/full'))).toBe(false)
    expect(screen.queryByText('第 1–50 篇 / 共 123 篇')).not.toBeInTheDocument()
    expect(screen.getByText('共 1 篇完整日记')).toBeInTheDocument()
  })

  it('切换完整正文开关后立即请求全文接口，无需提交搜索表单', async () => {
    const fullEntries = {
      total: 1,
      items: [{ ...entriesPage.items[0], content: '切换后立即显示的完整正文。' }],
      year: 2024,
      month: null,
      entry_type: null,
      query: null,
    }
    const calls: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        calls.push(url)
        return Promise.resolve(
          new Response(
            JSON.stringify(url.includes('/api/entries/full') ? fullEntries : entriesPage),
          ),
        )
      }),
    )
    const user = userEvent.setup()
    renderPage('/browse?year=2024&page=2')

    await screen.findByText('旅行与朋友聚会')
    await user.click(screen.getByRole('checkbox', { name: '显示完整正文' }))

    expect(await screen.findByText('切换后立即显示的完整正文。')).toBeInTheDocument()
    const fullCall = calls.find((url) => url.includes('/api/entries/full?'))
    expect(fullCall).toBeDefined()
    expect(fullCall).toContain('year=2024')
    expect(fullCall).not.toContain('page=2')
  })

  it('开关是独立控件：不继承筛选输入框的尺寸类名', async () => {
    stubFetch()
    renderPage('/browse?year=2024')

    await screen.findByText('旅行与朋友聚会')
    const toggle = screen.getByRole('checkbox', { name: '显示完整正文' })
    expect(toggle).toHaveClass('switch-input')
    expect(toggle.closest('label')).toHaveClass('switch')
    expect(toggle).not.toHaveAttribute('placeholder')
  })

  it('清除筛选按钮清空全部查询参数并回到未筛选列表', async () => {
    const calls = stubFetch()
    const user = userEvent.setup()
    renderPage('/browse?year=2024&month=9&q=%E6%97%85%E8%A1%8C&per_page=100&page=2')

    await screen.findByText('旅行与朋友聚会')
    const clear = screen.getByRole('button', { name: '清除筛选' })
    await user.click(clear)

    const clearedCall = calls.find((url) => url.includes('/api/entries?') && !url.includes('year='))
    expect(clearedCall).toBeDefined()
    const clearedParams = new URLSearchParams(clearedCall?.split('?')[1] ?? '')
    expect(clearedParams.get('per_page')).toBe('50')
    expect(clearedParams.get('month')).toBeNull()
    expect(clearedParams.get('q')).toBeNull()
    expect(clearedParams.get('page')).toBeNull()
    expect(clearedParams.get('full')).toBeNull()
    const yearInput = document.querySelector('input[name="year"]') as HTMLInputElement
    expect(yearInput.value).toBe('')
  })

  it('清除筛选按钮在完整正文模式下同时关闭开关', async () => {
    const fullEntries = {
      total: 1,
      items: [{ ...entriesPage.items[0], content: '完整正文内容。' }],
      year: 2024,
      month: null,
      entry_type: null,
      query: null,
    }
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input)
        return Promise.resolve(
          new Response(
            JSON.stringify(url.includes('/api/entries/full') ? fullEntries : entriesPage),
          ),
        )
      }),
    )
    const user = userEvent.setup()
    renderPage('/browse?year=2024&full=1')

    expect(await screen.findByText('完整正文内容。')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '清除筛选' }))

    expect(await screen.findByText('旅行与朋友聚会')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: '显示完整正文' })).not.toBeChecked()
  })
})
