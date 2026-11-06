import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router'
import { useLogout, useMe } from '../auth/auth'
import { roleLabel } from '../auth/permissions'
import Tree from './Tree'

// App shell: 56px top bar, tree panel (280px; drawer on phones), main view.
export default function Layout() {
  const [drawer, setDrawer] = useState(false)
  const me = useMe().data
  const logout = useLogout()
  const navigate = useNavigate()
  return (
    <div className={`app${drawer ? ' drawer-open' : ''}`}>
      <header className="topbar">
        <button type="button" className="ghost icon menu-btn" aria-label="Toggle navigation tree" aria-expanded={drawer} onClick={() => setDrawer(!drawer)}>
          ☰
        </button>
        <NavLink to="/" end className="brand">DCIM</NavLink>
        <NavLink to="/search" className="search-link" aria-label="Search devices by host name or serial">🔍</NavLink>
        <nav className="topnav" aria-label="Main">
          <NavLink to="/devices">Devices</NavLink>
          <NavLink to="/profiles">Profiles</NavLink>
          <NavLink to="/reports">Reports</NavLink>
          <NavLink to="/import">Import</NavLink>
        </nav>
        {me && (
          <div className="usermenu">
            <Link to="/account/password" className="user" title="Change password">
              {me.display_name || me.email} <span className="role-chip">{roleLabel(me.role)}</span>
            </Link>
            <button type="button" className="ghost" onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login') })}>
              Log out
            </button>
          </div>
        )}
      </header>
      <aside className="sidebar" onClick={(e) => (e.target as HTMLElement).closest('a') && setDrawer(false)}>
        {drawer && (
        <nav className="drawer-nav" aria-label="Main (phone)">
          <NavLink to="/search">Search</NavLink>
          <NavLink to="/devices">Devices</NavLink>
          <NavLink to="/profiles">Profiles</NavLink>
          <NavLink to="/reports">Reports</NavLink>
          <NavLink to="/import">Import</NavLink>
          {me && <Link to="/account/password">Change password</Link>}
          {me && (
            <button type="button" className="ghost" onClick={() => logout.mutate(undefined, { onSettled: () => navigate('/login') })}>
              Log out
            </button>
          )}
        </nav>
        )}
        <Tree />
      </aside>
      <main className="content">
        <Outlet />
      </main>
    </div>
  )
}
