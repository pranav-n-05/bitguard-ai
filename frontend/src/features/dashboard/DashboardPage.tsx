import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertStatusBadge, BandBadge, CaseStatusBadge, DataLabel } from '@/components/badges'
import { BandChart, HistogramChart, VolumeChart } from '@/components/charts'
import { DataState, Empty, Unavailable } from '@/components/states'
import { Card, CardBody, CardHeader } from '@/components/ui/primitives'
import { PageHeader } from '@/layouts/AppLayout'
import { get } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { Alert, Band, CaseRow, Paginated } from '@/types/api'
import { formatDate, formatNumber, titleCase } from '@/utils/format'

interface Overview {
  data_labels: string[]
  time_range: { start: string; end: string } | null
  counts: Record<string, number>
  record_quality: Record<string, number>
  ingestion_jobs: Record<string, number>
  open_alerts_by_severity: Record<Band, number>
  last_analysis_run: { id: string; finished_at: string; stats: Record<string, number> } | null
  active_models: { id: string; name: string; version: string }[]
}

function Stat({ label, value, to }: { label: string; value: number | undefined; to?: string }) {
  const body = (
    <Card className="p-3">
      <div className="text-xs text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold num">{value === undefined ? '—' : formatNumber(value)}</div>
    </Card>
  )
  return to ? <Link to={to} className="block hover:opacity-90">{body}</Link> : body
}

export default function DashboardPage() {
  const { can } = useAuth()
  const ov = useQuery({ queryKey: ['overview'], queryFn: () => get<Overview>('/analytics/overview') })
  const vol = useQuery({ queryKey: ['volume'], queryFn: () => get<{ series: { t: string; tx_count: number }[] }>('/analytics/transaction-volume') })
  const risk = useQuery({ queryKey: ['riskdist'], queryFn: () => get<{ available: boolean; bands: Record<string, number>; note: string; assessed: number }>('/analytics/risk-distribution') })
  const anom = useQuery({ queryKey: ['anomalies'], queryFn: () => get<{ available: boolean; reason?: string; histogram: { bin_start: number; count: number }[]; note?: string }>('/analytics/anomalies') })
  const alerts = useQuery({
    queryKey: ['alerts', 'open-top'], enabled: can('alert.read'),
    queryFn: () => get<Paginated<Alert>>('/alerts', { status: ['new', 'acknowledged', 'under_investigation', 'escalated'], limit: 8, sort: '-risk_score' }),
  })
  const cases = useQuery({
    queryKey: ['cases', 'priority'], enabled: can('case.read'),
    queryFn: () => get<Paginated<CaseRow>>('/investigations', { status: ['open', 'in_progress'], priority: ['high', 'elevated'], limit: 6 }),
  })
  const activity = useQuery({
    queryKey: ['audit', 'recent'], enabled: can('audit.read'),
    queryFn: () => get<Paginated<{ seq: number; occurred_at: string; action: string; actor_email: string | null; entity_type: string }>>('/admin/audit-logs', { limit: 8 }),
  })

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={ov.data?.time_range ? `Data window ${formatDate(ov.data.time_range.start)} → ${formatDate(ov.data.time_range.end)}` : 'No data ingested yet'}
        actions={ov.data?.data_labels.map((l) => <DataLabel key={l} label={l} />)}
      />
      <DataState query={ov}>
        {(o) => (
          <div className="space-y-4">
            {o.counts.transactions === 0 && (
              <Card><Empty title="No transactions ingested">Upload a dataset on the <Link className="text-accent-2 underline" to="/ingestion">Data Ingestion</Link> page to begin.</Empty></Card>
            )}
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
              <Stat label="Transactions" value={o.counts.transactions} to="/transactions" />
              <Stat label="Addresses" value={o.counts.addresses} to="/addresses" />
              <Stat label="Network observations" value={o.counts.network_observations} />
              <Stat label="Graph detections" value={o.counts.graph_detections} to="/graph" />
              <Stat label="Correlation indicators" value={o.counts.correlation_indicators} />
              <Stat label="Open alerts" value={Object.values(o.open_alerts_by_severity).reduce((a, b) => a + b, 0)} to="/alerts" />
              <Stat label="Open cases" value={o.counts.open_cases} to="/investigations" />
            </div>
            <div className="grid gap-4 xl:grid-cols-3">
              <Card className="xl:col-span-2">
                <CardHeader title="Transaction volume" subtitle="Daily first-seen transactions (historical bulk data)" />
                <CardBody>
                  <DataState query={vol} isEmpty={(v) => v.series.length === 0} empty={<Unavailable reason="no transactions" />}>
                    {(v) => <VolumeChart data={v.series} />}
                  </DataState>
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Ingestion health" subtitle={o.last_analysis_run ? `Last analysis ${formatDate(o.last_analysis_run.finished_at)}` : 'No analysis run yet'} />
                <CardBody className="space-y-3 text-sm">
                  <div>
                    <div className="mb-1 text-xs text-muted">Record quality</div>
                    {Object.entries(o.record_quality).map(([k, v]) => (
                      <div key={k} className="flex justify-between"><span>{titleCase(k)}</span><span className="num">{formatNumber(v)}</span></div>
                    ))}
                  </div>
                  <div>
                    <div className="mb-1 text-xs text-muted">Jobs</div>
                    {Object.entries(o.ingestion_jobs).filter(([, v]) => v > 0).map(([k, v]) => (
                      <div key={k} className="flex justify-between"><span>{titleCase(k)}</span><span className="num">{v}</span></div>
                    ))}
                    {Object.values(o.ingestion_jobs).every((v) => v === 0) && <span className="text-muted">No jobs</span>}
                  </div>
                  <div className="text-xs text-muted">Active models: {o.active_models.length ? o.active_models.map((m) => `${m.name}@${m.version}`).join(', ') : 'none'}</div>
                </CardBody>
              </Card>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader title="Risk distribution" subtitle="Transactions by prioritisation band (not probabilities)" />
                <CardBody>
                  <DataState query={risk} isEmpty={(r) => !r.available} empty={<Unavailable reason="no risk assessments yet" />}>
                    {(r) => <BandChart bands={r.bands} />}
                  </DataState>
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Anomaly score distribution" subtitle="Active transaction model; raw outlier score (higher = more anomalous)" />
                <CardBody>
                  <DataState query={anom} isEmpty={(a) => !a.available} empty={<Unavailable reason={anom.data?.reason ?? 'no active model'} />}>
                    {(a) => <HistogramChart data={a.histogram.map((h) => ({ bin: h.bin_start.toFixed(3), count: h.count }))} xKey="bin" label="Anomaly score histogram" />}
                  </DataState>
                </CardBody>
              </Card>
            </div>
            <div className="grid gap-4 xl:grid-cols-3">
              {can('alert.read') && (
                <Card className="xl:col-span-2">
                  <CardHeader title="Highest-risk open alerts" actions={<Link className="text-xs text-accent-2" to="/alerts">View queue</Link>} />
                  <DataState query={alerts} isEmpty={(a) => a.items.length === 0} empty={<Empty title="No open alerts" />}>
                    {(a) => (
                      <ul className="divide-y divide-line">
                        {a.items.map((al) => (
                          <li key={al.id}>
                            <Link to={`/alerts/${al.id}`} className="flex items-center gap-3 px-4 py-2.5 hover:bg-bg-2">
                              <BandBadge band={al.severity} />
                              <span className="min-w-0 flex-1 truncate">{al.title}</span>
                              <span className="hidden text-xs text-muted md:inline">{titleCase(al.category)}</span>
                              <span className="mono w-8 text-right">{al.risk_score ?? '—'}</span>
                              <AlertStatusBadge status={al.status} />
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </DataState>
                </Card>
              )}
              {can('case.read') && (
                <Card>
                  <CardHeader title="High-priority cases" actions={<Link className="text-xs text-accent-2" to="/investigations">All cases</Link>} />
                  <DataState query={cases} isEmpty={(c) => c.items.length === 0} empty={<Empty title="No high-priority open cases" />}>
                    {(c) => (
                      <ul className="divide-y divide-line">
                        {c.items.map((cs) => (
                          <li key={cs.id}>
                            <Link to={`/investigations/${cs.id}`} className="block px-4 py-2.5 hover:bg-bg-2">
                              <div className="flex items-center justify-between gap-2"><span className="mono text-xs text-muted">{cs.case_number}</span><CaseStatusBadge status={cs.status} /></div>
                              <div className="truncate">{cs.title}</div>
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </DataState>
                </Card>
              )}
            </div>
            {can('audit.read') && (
              <Card>
                <CardHeader title="Recent activity" subtitle="Append-only audit log" />
                <DataState query={activity} isEmpty={(a) => a.items.length === 0}>
                  {(a) => (
                    <ul className="divide-y divide-line text-sm">
                      {a.items.map((e) => (
                        <li key={e.seq} className="flex gap-3 px-4 py-2">
                          <span className="mono w-44 shrink-0 text-xs text-muted">{formatDate(e.occurred_at)}</span>
                          <span className="mono text-accent-2">{e.action}</span>
                          <span className="truncate text-muted">{e.actor_email ?? 'system'}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </DataState>
              </Card>
            )}
          </div>
        )}
      </DataState>
    </>
  )
}
