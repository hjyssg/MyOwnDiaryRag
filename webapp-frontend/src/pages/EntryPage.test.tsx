import { act, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { EntryPage } from './EntryPage'

const entry = {
  id: 2,
  date: '2024-09-17',
  year: 2024,
  month: 9,
  day: 17,
  entry_type: 'diary',
  word_count: 14,
  preview: '重复内容检查。',
  content: '重复内容检查。\n第二段正文。',
  previous_entry: { id: 1, date: '2024-09-16', entry_type: 'note' },
  next_entry: { id: 3, date: '2024-09-18', entry_type: 'diary' },
}
const summary = {
  entry_key: 'v1:2024-09-17:diary',
  entry_id: 2,
  entry_date: '2024-09-17',
  entry_type: 'diary',
  word_count: 14,
  status: 'ok',
  summary: '测试摘要。',
  emotion: '',
  emotion_status: 'missing',
  model: 'demo',
  generated_at: '2024-09-17T00:00:00Z',
}

afterEach(() => vi.restoreAllMocks())

describe('日记详情页', () => {
  it('全文只显示一次，并按时间顺序提供相邻日记链接', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: RequestInfo | URL) =>
        Promise.resolve(
          new Response(JSON.stringify(String(input).includes('/summary') ? summary : entry)),
        ),
      ),
    )
    const router = createMemoryRouter([{ path: '/entries/:id', element: <EntryPage /> }], {
      initialEntries: ['/entries/2'],
    })
    render(<RouterProvider router={router} />)

    expect(await screen.findByText('测试摘要。')).toBeInTheDocument()
    const content = document.querySelector('.entry-page > .content')
    expect(content).toHaveTextContent('重复内容检查。 第二段正文。')
    expect(screen.getByRole('link', { name: /上一篇/ })).toHaveAttribute('href', '/entries/1')
    expect(screen.getByRole('link', { name: /下一篇/ })).toHaveAttribute('href', '/entries/3')
    await act(async () => fireEvent.keyDown(window, { key: 'ArrowRight' }))
    expect(router.state.location.pathname).toBe('/entries/3')
    await act(async () => fireEvent.mouseDown(window, { button: 3 }))
    expect(router.state.location.pathname).toBe('/entries/1')
  })
})
