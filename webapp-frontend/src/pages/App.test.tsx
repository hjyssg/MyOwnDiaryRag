import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router-dom'
import { AppLayout } from '../app/AppLayout'
import { NotFoundPage } from './NotFoundPage'

describe('应用路由', () => {
  it('显示导航和 404', async () => {
    const router = createMemoryRouter(
      [{ element: <AppLayout />, children: [{ path: '*', element: <NotFoundPage /> }] }],
      { initialEntries: ['/missing'] },
    )
    render(<RouterProvider router={router} />)
    expect(await screen.findByRole('heading', { name: '404' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'AI 摘要' })).toBeInTheDocument()
  })
})
