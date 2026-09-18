import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from './AppLayout'
import { HomePage } from '../pages/HomePage'
import { BrowsePage } from '../pages/BrowsePage'
import { EntryPage } from '../pages/EntryPage'
import { OnThisDayPage } from '../pages/OnThisDayPage'
import { RandomPage } from '../pages/RandomPage'
import { SummariesPage } from '../pages/SummariesPage'
import { StatisticsPage } from '../pages/StatisticsPage'
import { NotFoundPage } from '../pages/NotFoundPage'

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    children: [
      { path: '/', element: <HomePage /> },
      { path: '/browse', element: <BrowsePage /> },
      { path: '/entries/:id', element: <EntryPage /> },
      { path: '/on-this-day', element: <OnThisDayPage /> },
      { path: '/random', element: <RandomPage /> },
      { path: '/summaries', element: <SummariesPage /> },
      { path: '/statistics', element: <StatisticsPage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
