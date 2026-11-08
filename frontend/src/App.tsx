import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { Empty, Loading } from '@/components/states'
import { AppLayout } from '@/layouts/AppLayout'
import LoginPage from '@/pages/LoginPage'
import { useAuth } from '@/stores/auth'

const Dashboard = lazy(() => import('@/features/dashboard/DashboardPage'))
const Transactions = lazy(() => import('@/features/transactions/TransactionsPage'))
const TransactionDetail = lazy(() => import('@/features/transactions/TransactionDetailPage'))
const AddressPage = lazy(() => import('@/features/addresses/AddressPage'))
const AddressSearch = lazy(() => import('@/features/addresses/AddressPage').then((m) => ({ default: m.AddressSearchPage })))
const NetworkEntity = lazy(() => import('@/features/addresses/NetworkEntityPage'))
const Graph = lazy(() => import('@/features/graph/GraphPage'))
const Cluster = lazy(() => import('@/features/graph/GraphPage').then((m) => ({ default: m.ClusterPage })))
const Intelligence = lazy(() => import('@/features/intelligence/IntelligencePage'))
const Alerts = lazy(() => import('@/features/alerts/AlertsPage'))
const AlertDetail = lazy(() => import('@/features/alerts/AlertsPage').then((m) => ({ default: m.AlertDetailPage })))
const Investigations = lazy(() => import('@/features/investigations/InvestigationsPage'))
const InvestigationDetail = lazy(() => import('@/features/investigations/InvestigationsPage').then((m) => ({ default: m.InvestigationDetailPage })))
const Reports = lazy(() => import('@/features/reports/ReportsPage'))
const Ingestion = lazy(() => import('@/features/administration/IngestionPage'))
const Admin = lazy(() => import('@/features/administration/AdminPage'))

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <Loading label="Restoring session…" />
  if (!user) return <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />
  return <>{children}</>
}

function Perm({ p, children }: { p: string; children: ReactNode }) {
  const { can } = useAuth()
  return can(p) ? <>{children}</> : <Empty title="Not permitted">Your role does not include <code className="mono">{p}</code>.</Empty>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><AppLayout /></RequireAuth>}>
        <Route element={<ErrorBoundary><Suspense fallback={<Loading />}><RoutedOutlet /></Suspense></ErrorBoundary>}>
          <Route index element={<Perm p="intel.read"><Dashboard /></Perm>} />
          <Route path="transactions" element={<Perm p="intel.read"><Transactions /></Perm>} />
          <Route path="transactions/:txid" element={<Perm p="intel.read"><TransactionDetail /></Perm>} />
          <Route path="addresses" element={<Perm p="intel.read"><AddressSearch /></Perm>} />
          <Route path="addresses/:address" element={<Perm p="intel.read"><AddressPage /></Perm>} />
          <Route path="network/ip/:key" element={<Perm p="intel.read"><NetworkEntity kind="ip" /></Perm>} />
          <Route path="network/asn/:key" element={<Perm p="intel.read"><NetworkEntity kind="asn" /></Perm>} />
          <Route path="graph" element={<Perm p="intel.read"><Graph /></Perm>} />
          <Route path="graph/clusters/:id" element={<Perm p="intel.read"><Cluster /></Perm>} />
          <Route path="intelligence" element={<Perm p="model.read"><Intelligence /></Perm>} />
          <Route path="alerts" element={<Perm p="alert.read"><Alerts /></Perm>} />
          <Route path="alerts/:id" element={<Perm p="alert.read"><AlertDetail /></Perm>} />
          <Route path="investigations" element={<Perm p="case.read"><Investigations /></Perm>} />
          <Route path="investigations/:id" element={<Perm p="case.read"><InvestigationDetail /></Perm>} />
          <Route path="reports" element={<Perm p="case.read"><Reports /></Perm>} />
          <Route path="ingestion" element={<Perm p="dataset.read"><Ingestion /></Perm>} />
          <Route path="admin" element={<Admin />} />
          <Route path="*" element={<Empty title="Page not found" />} />
        </Route>
      </Route>
    </Routes>
  )
}

function RoutedOutlet() {
  const loc = useLocation()
  return <div key={loc.pathname}><Outlet /></div>
}
