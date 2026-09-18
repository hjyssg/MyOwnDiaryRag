import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { OnThisDayPage } from './OnThisDayPage'

const empty = { month: 2, day: 28, total: 0, groups: [] }

function stubFetch() {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      calls.push(String(input))
      return Promise.resolve(
        new Response(JSON.stringify(empty), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
    }),
  )
  return calls
}
function renderPage(entry = '/on-this-day?month=2&day=28') {
  const router = createMemoryRouter([{ path: '/on-this-day', element: <OnThisDayPage /> }], {
    initialEntries: [entry],
  })
  return render(<RouterProvider router={router} />)
}
afterEach(() => vi.restoreAllMocks())

describe('过去的今天日期选择', () => {
  it('原生日期输入按 URL 的月 / 日回填', async () => {
    const calls = stubFetch()
    renderPage()

    const input = document.querySelector('input[name="date"]') as HTMLInputElement
    expect(input.value.endsWith('-02-28')).toBe(true)
    expect(await screen.findByText('2月28日暂无日记')).toBeInTheDocument()
    expect(calls.some((url) => url.includes('month=2&day=28'))).toBe(true)
  })

  it('"后一天"按参考闰年推进：2 月 28 日 → 2 月 29 日 → 3 月 1 日', async () => {
    const calls = stubFetch()
    renderPage()
    await screen.findByText('2月28日暂无日记')

    await userEvent.click(screen.getByRole('button', { name: '后一天 →' }))

    await waitFor(() => expect(calls.some((url) => url.includes('month=2&day=29'))).toBe(true))
    await screen.findByText('2月29日暂无日记')

    await userEvent.click(screen.getByRole('button', { name: '后一天 →' }))

    await waitFor(() => expect(calls.some((url) => url.includes('month=3&day=1'))).toBe(true))
  })

  it('非法的月 / 日回退到今天，不会给后端发脏参数', async () => {
    const calls = stubFetch()
    renderPage('/on-this-day?month=13&day=40')
    const today = new Date()
    const mmdd = `${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`

    await screen.findByText(`${today.getMonth() + 1}月${today.getDate()}日暂无日记`)

    const input = document.querySelector('input[name="date"]') as HTMLInputElement
    expect(input.value.endsWith(mmdd)).toBe(true)
    const apiCall = calls.find((url) => url.includes('/api/on-this-day'))
    expect(apiCall).toContain(`month=${today.getMonth() + 1}`)
    expect(apiCall).toContain(`day=${today.getDate()}`)
  })

  it('方向键和鼠标侧键切换日期，日期输入框聚焦时不触发', async () => {
    const calls = stubFetch()
    renderPage()
    await screen.findByText('2月28日暂无日记')

    fireEvent.keyDown(window, { key: 'ArrowRight' })
    await waitFor(() => expect(calls.some((url) => url.includes('month=2&day=29'))).toBe(true))
    fireEvent.mouseDown(window, { button: 3 })
    await waitFor(() =>
      expect(calls.filter((url) => url.includes('month=2&day=28')).length).toBeGreaterThan(1),
    )

    const input = document.querySelector('input[name="date"]') as HTMLInputElement
    input.focus()
    const count = calls.length
    fireEvent.keyDown(input, { key: 'ArrowRight' })
    expect(calls).toHaveLength(count)
  })
})
