import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

function MarkIcon() {
  return <span className="brand-mark" aria-hidden="true" />
}

function NavIcon({ children }: { children: ReactNode }) {
  return (
    <span className="nav-icon" aria-hidden="true">
      {children}
    </span>
  )
}

const navigation = [
  { to: '/', label: '首页', icon: '⌂', end: true },
  { to: '/browse', label: '浏览日记', icon: '▧' },
  { to: '/on-this-day', label: '日期查找', icon: '◴' },
  { to: '/random', label: '随机回忆', icon: '⌁' },
  { to: '/summaries', label: 'AI 摘要', icon: '◌' },
  { to: '/statistics', label: '统计', icon: '▤' },
]

export function AppLayout() {
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink className="brand" to="/" aria-label="MyDiary 首页">
          <MarkIcon />
          <span>MyDiary</span>
        </NavLink>
        <nav className="sidebar-nav" aria-label="主导航">
          {navigation.map(({ to, label, icon, end }) => (
            <NavLink key={to} to={to} end={end}>
              <NavIcon>{icon}</NavIcon>
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="page-main">
        <div className="page-frame">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
