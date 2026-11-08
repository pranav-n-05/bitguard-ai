import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertStatusBadge, BandBadge } from '@/components/badges'
import { DataState, Unavailable } from '@/components/states'
import { Badge, Card, CardBody, CardHeader, Table, Td, Th } from '@/components/ui/primitives'
import { get } from '@/services/api'
import type { RiskDetail } from '@/types/api'
import { formatDate, formatNumber, pct, titleCase } from '@/utils/format'

export function RiskPanel({ entityType, entityKey }: { entityType: 'transaction' | 'address'; entityKey: string }) {
  const url = entityType === 'transaction' ? `/transactions/${entityKey}/risk` : `/addresses/${encodeURIComponent(entityKey)}/risk`
  const q = useQuery({ queryKey: ['risk', entityType, entityKey], queryFn: () => get<RiskDetail>(url) })
  return (
    <DataState query={q} isEmpty={(r) => !r.available} empty={<Unavailable reason={q.data?.reason ?? 'not assessed'} />}>
      {(r) => (
        <div className="space-y-4">
          <Card>
            <CardHeader title={<span className="flex items-center gap-2">Risk {r.score}/100 <BandBadge band={r.band} /></span>}
              subtitle={`Rule ${r.rule_version} · assessed ${formatDate(r.assessed_at)} · uncertainty ${pct(r.uncertainty, 0)}`} />
            <CardBody className="space-y-3 text-sm">
              <p>{r.explanation}</p>
              <p><span className="text-muted">Recommended action: </span>{r.recommended_action}</p>
              <p className="rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn">{r.limitations}</p>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Score components" subtitle="Each component normalised 0–1 and weighted; unavailable components are excluded, not counted as zero." />
            <Table>
              <thead><tr><Th>Component</Th><Th>Value</Th><Th>Weight</Th><Th>Contribution</Th><Th>Rationale</Th></tr></thead>
              <tbody>
                {r.components.map((c) => (
                  <tr key={c.component}>
                    <Td>{titleCase(c.component)}</Td>
                    <Td className="mono">{c.available ? c.normalised.toFixed(3) : <Badge>unavailable</Badge>}</Td>
                    <Td className="mono">{c.weight.toFixed(2)}</Td>
                    <Td className="mono">{c.available ? c.contribution.toFixed(1) : '—'}</Td>
                    <Td className="text-xs text-muted">{c.rationale}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </Card>
          {r.anomaly && (
            <Card>
              <CardHeader title={`Model explanation (${r.anomaly.explanation_method})`} subtitle={r.anomaly.note} />
              <CardBody>
                <p className="mb-2 text-sm">Outlier rank <span className="mono">{r.anomaly.anomaly_score.toFixed(4)}</span>{r.anomaly.is_outlier && <Badge tone="warn" className="ml-2">model outlier</Badge>}</p>
                <Table>
                  <thead><tr><Th>Feature</Th><Th>Value</Th><Th>Direction</Th><Th>Contribution</Th></tr></thead>
                  <tbody>
                    {r.anomaly.top_features.map((f) => (
                      <tr key={f.feature}><Td className="mono text-xs">{f.feature}</Td><Td className="mono">{f.missing ? 'missing' : formatNumber(f.value, 4)}</Td><Td>{f.direction}</Td><Td className="mono">{f.contribution.toFixed(3)}</Td></tr>
                    ))}
                  </tbody>
                </Table>
              </CardBody>
            </Card>
          )}
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Assessment history" subtitle="Previous assessments are preserved" />
              <ul className="divide-y divide-line text-sm">
                {r.history.map((h) => (
                  <li key={h.assessment_id} className="px-4 py-2">
                    <div className="flex items-center gap-2"><span className="mono">{h.score}</span><BandBadge band={h.band} />{h.is_current && <Badge tone="info">current</Badge>}<span className="ml-auto mono text-xs text-muted">{formatDate(h.assessed_at)}</span></div>
                    {h.change_reason && <div className="mt-1 text-xs text-muted">{h.change_reason}</div>}
                  </li>
                ))}
              </ul>
            </Card>
            <Card>
              <CardHeader title="Related alerts" />
              {r.alerts.length === 0 ? <Unavailable reason="no alerts reference this entity" /> : (
                <ul className="divide-y divide-line text-sm">
                  {r.alerts.map((a) => (
                    <li key={a.id}><Link to={`/alerts/${a.id}`} className="flex items-center gap-2 px-4 py-2 hover:bg-bg-2"><BandBadge band={a.severity} />{titleCase(a.category)}<span className="ml-auto"><AlertStatusBadge status={a.status} /></span></Link></li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}
    </DataState>
  )
}
