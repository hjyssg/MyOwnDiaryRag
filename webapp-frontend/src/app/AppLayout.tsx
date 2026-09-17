import { NavLink, Outlet } from 'react-router-dom'

export function AppLayout() {
  return (
    <>
      <header className="topbar">
        <NavLink className="brand" to="/">
          📔 我的日记
        </NavLink>
        <nav>
          <NavLink to="/browse">浏览</NavLink>
          <NavLink to="/on-this-day">过去的今天</NavLink>
          <NavLink to="/random">随机一天</NavLink>
          <NavLink to="/summaries">摘要</NavLink>
        </nav>
      </header>
      <main className="container">
        <Outlet />
      </main>
      <footer>
        纯本地只读 · 数据不出本机 · <a href="/docs">API 文档</a>
      </footer>
    </>
  )
}
