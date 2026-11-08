import { AlertTriangle, CircleSlash, Database, Loader2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { httpStatus, problemMessage } from '@/services/api'
import { Button } from './ui/primitives'

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 p-6 text-sm text-muted">
      <Loader2 className="animate-spin" size={16} /> {label}
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const status = httpStatus(error)
  return (
    <div role="alert" className="m-4 flex items-start gap-3 rounded-md border border-crit/40 bg-crit/10 p-4 text-sm">
      <AlertTriangle className="mt-0.5 shrink-0 text-crit" size={16} />
      <div className="flex-1">
        <p className="font-medium text-crit">{status === 403 ? 'Not permitted' : status === 404 ? 'Not found' : 'Could not load data'}</p>
        <p className="mt-1 text-text/90">{problemMessage(error)}</p>
      </div>
      {retry && status !== 403 && status !== 404 && <Button size="sm" onClick={retry}>Retry</Button>}
    </div>
  )
}

export function Empty({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 p-8 text-center text-sm text-muted">
      {icon ?? <Database size={20} />}
      <p className="font-medium text-text">{title}</p>
      {children && <div className="max-w-md">{children}</div>}
    </div>
  )
}

export function Unavailable({ reason }: { reason: string }) {
  return (
    <div className="flex items-center gap-2 p-4 text-sm text-muted">
      <CircleSlash size={14} /> <span>Unavailable — {reason}</span>
    </div>
  )
}

/** Uniform loading / error / empty handling for TanStack queries. */
export function DataState<T>({ query, empty, isEmpty, children }: {
  query: { isLoading: boolean; isError: boolean; error: unknown; data: T | undefined; refetch: () => unknown }
  empty?: ReactNode
  isEmpty?: (d: T) => boolean
  children: (d: T) => ReactNode
}) {
  if (query.isLoading) return <Loading />
  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  if (query.data === undefined) return <Unavailable reason="no data returned" />
  if (isEmpty?.(query.data)) return <>{empty ?? <Empty title="Nothing to show" />}</>
  return <>{children(query.data)}</>
}
