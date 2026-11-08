import { Button } from './ui/primitives'
import { formatNumber } from '@/utils/format'

export function Pagination({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  const page = Math.floor(offset / limit) + 1
  const pages = Math.max(1, Math.ceil(total / limit))
  return (
    <div className="flex items-center justify-between gap-2 border-t border-line px-3 py-2 text-xs text-muted">
      <span>
        {total === 0 ? 'No results' : `${formatNumber(offset + 1)}–${formatNumber(Math.min(offset + limit, total))} of ${formatNumber(total)}`}
      </span>
      <div className="flex items-center gap-1">
        <Button size="sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))} aria-label="Previous page">Prev</Button>
        <span className="px-2">Page {page} / {pages}</span>
        <Button size="sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)} aria-label="Next page">Next</Button>
      </div>
    </div>
  )
}

export function SortTh({ label, field, sort, onSort, className }: { label: string; field: string; sort: string | null; onSort: (s: string) => void; className?: string }) {
  const active = sort?.replace('-', '') === field
  const desc = sort?.startsWith('-')
  return (
    <th className={`border-b border-line px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-muted ${className ?? ''}`} aria-sort={active ? (desc ? 'descending' : 'ascending') : 'none'}>
      <button className="inline-flex items-center gap-1 hover:text-text" onClick={() => onSort(active && desc ? field : `-${field}`)}>
        {label} {active ? (desc ? '↓' : '↑') : ''}
      </button>
    </th>
  )
}
