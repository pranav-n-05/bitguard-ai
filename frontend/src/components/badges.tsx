import { Link } from 'react-router-dom'
import type { AlertStatus, Band, CaseStatus } from '@/types/api'
import { titleCase } from '@/utils/format'
import { Badge } from './ui/primitives'

const BAND_TONE = { low: 'ok', moderate: 'info', elevated: 'warn', high: 'crit' } as const

export function BandBadge({ band }: { band: Band | null | undefined }) {
  if (!band) return <Badge>unscored</Badge>
  return <Badge tone={BAND_TONE[band]}>{band}</Badge>
}

/** A risk score is always clickable to its evidence and explanation. */
export function RiskScore({ score, band, entityType, entityKey }: { score: number | null | undefined; band?: Band | null; entityType: 'transaction' | 'address'; entityKey: string }) {
  if (score === null || score === undefined) return <span className="text-xs text-muted">unscored</span>
  const to = entityType === 'transaction' ? `/transactions/${entityKey}?tab=risk` : `/addresses/${encodeURIComponent(entityKey)}?tab=risk`
  return (
    <Link to={to} className="inline-flex items-center gap-1.5 hover:underline" title="Open risk explanation and evidence">
      <span className="mono font-semibold num">{score}</span>
      {band && <BandBadge band={band} />}
    </Link>
  )
}

const STATUS_TONE: Record<AlertStatus, 'info' | 'warn' | 'accent' | 'crit' | 'ok' | 'neutral'> = {
  new: 'info', acknowledged: 'accent', under_investigation: 'warn', escalated: 'crit', resolved: 'ok', false_positive: 'neutral',
}
export function AlertStatusBadge({ status }: { status: AlertStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{titleCase(status)}</Badge>
}
const CASE_TONE: Record<CaseStatus, 'info' | 'warn' | 'neutral' | 'ok'> = { open: 'info', in_progress: 'warn', on_hold: 'neutral', closed: 'ok' }
export function CaseStatusBadge({ status }: { status: CaseStatus }) {
  return <Badge tone={CASE_TONE[status]}>{titleCase(status)}</Badge>
}

export function DataLabel({ label }: { label: string }) {
  const tone = label === 'synthetic' ? 'accent' : label === 'unavailable' ? 'neutral' : 'info'
  return <Badge tone={tone} title={label === 'synthetic' ? 'Synthetic data modelled on Bitcoin fields — not real activity' : undefined}>{label}</Badge>
}
