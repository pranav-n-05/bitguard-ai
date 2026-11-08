import { Activity, Bell, Brain, FileText, FolderSearch, LayoutDashboard, ListTree, LogOut, Menu, Network, Search, Settings, Shield, X } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Button, Input } from '@/components/ui/primitives'
import { useAuth } from '@/stores/auth'
import { cn } from '@/utils/cn'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, perm: 'intel.read' },
  { to: '/transactions', label: 'Transactions', icon: ListTree, perm: 'intel.read' },
  { to: '/addresses', label: 'Addresses', icon: Search, perm: 'intel.read' },
  { to: '/graph', label: 'Graph Intelligence', icon: Network, perm: 'intel.read' },
  { to: '/intelligence', label: 'AI Intelligence', icon: Brain, perm: 'model.read' },
  { to: '/alerts', label: 'Alerts', icon: Bell, perm: 'alert.read' },
  { to: '/investigations', label: 'Investigations', icon: FolderSearch, perm: 'case.read' },
  { to: '/reports', label: 'Reports', icon: FileText, perm: 'case.read' },
  { to: '/ingestion', label: 'Data Ingestion', icon: Activity, perm: 'dataset.read' },
  { to: '/admin', label: 'Administration', icon: Settings, perm: '' },
]

export function AppLayout() {
  const { user, logout, can } = useAuth()
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')

  function search(e: FormEvent) {
    e.preventDefault()
    const v = q.trim()
    if (!v) return
    if (/^[0-9a-fA-F]{64}$/.test(v)) nav(`/transactions/${v.toLowerCase()}`)
    else if (/^(\d{1,3}\.){3}\d{1,3}$/.test(v) || v.includes(':')) nav(`/network/ip/${encodeURIComponent(v)}`)
    else if (/^(bc1|tb1|[13mn2])[a-zA-HJ-NP-Z0-9]{20,90}$/.test(v)) nav(`/addresses/${encodeURIComponent(v)}`)
    else nav(`/transactions?q=${encodeURIComponent(v)}`)
    setQ('')
  }

  const sidebar = (
    <nav aria-label="Main" className="flex h-full flex-col">
      <div className="flex items-center gap-2 px-4 py-4">
        <Shield className="text-accent" size={22} />
        <div>
          <div className="text-sm font-bold tracking-wide">BITGUARD AI</div>
          <div className="text-[10px] uppercase tracking-wider text-muted">Offline intelligence console</div>
        </div>
      </div>
      <ul className="flex-1 space-y-0.5 px-2">
        {NAV.filter((n) => !n.perm || can(n.perm)).map((n) => (
          <li key={n.to}>
            <NavLink
              to={n.to}
              end={n.to === '/'}
              onClick={() => setOpen(false)}
              className={({ isActive }) =>
                cn('flex items-center gap-2.5 rounded-md px-3 py-2 text-sm', isActive ? 'bg-card text-text' : 'text-muted hover:bg-card/60 hover:text-text')
              }
            >
              <n.icon size={16} /> {n.label}
            </NavLink>
          </li>
        ))}
      </ul>
      <div className="border-t border-line p-3 text-xs">
        <div className="truncate font-medium">{user?.full_name}</div>
        <div className="truncate text-muted">{user?.role_names.join(', ')}</div>
        <Button variant="ghost" size="sm" className="mt-2 w-full justify-start" onClick={() => void logout()}>
          <LogOut size={14} /> Sign out
        </Button>
      </div>
    </nav>
  )

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-bg-2 lg:block">{sidebar}</aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} />
          <aside className="absolute left-0 top-0 h-full w-64 border-r border-line bg-bg-2">{sidebar}</aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-line bg-bg-2/60 px-4 py-2.5">
          <Button variant="ghost" size="icon" className="lg:hidden" aria-label={open ? 'Close menu' : 'Open menu'} onClick={() => setOpen(!open)}>
            {open ? <X size={18} /> : <Menu size={18} />}
          </Button>
          <form onSubmit={search} className="max-w-xl flex-1" role="search">
            <Input aria-label="Search txid, address or IP" placeholder="Search txid, address or IP…" value={q} onChange={(e) => setQ(e.target.value)} />
          </form>
          <span className="hidden text-[11px] uppercase tracking-wider text-muted md:inline">Offline · bulk historical data · no live node</span>
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto p-4 lg:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
