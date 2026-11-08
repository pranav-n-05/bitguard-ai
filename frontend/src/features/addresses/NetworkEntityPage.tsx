import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { RiskScore } from '@/components/badges'
import { DataState, Unavailable } from '@/components/states'
import { Badge, Card, CardHeader, KV, Table, Td, Th } from '@/components/ui/primitives'
import { PageHeader } from '@/layouts/AppLayout'
import { get } from '@/services/api'
import type { Band } from '@/types/api'
import { formatDate, formatNumber, shortHash, titleCase } from '@/utils/format'

interface NetEntity {
  key: string; features: Record<string, number | string | null> | null; notice: string
  indicators: { id: number; indicator_type: string; strength: number; confidence: number; metrics: Record<string, unknown>; window_start: string; window_end: string; limitations: string }[]
  recent_observations: { id: number; txid: string; observed_at: string; src_ip: string; dst_ip: string; dst_port: number; asn: number | null; country: string | null; tx_risk: { score: number; band: Band } | null }[]
}

export default function NetworkEntityPage({ kind }: { kind: 'ip' | 'asn' }) {
  const { key = '' } = useParams()
  const url = kind === 'ip' ? `/network/ips/${encodeURIComponent(key)}` : `/network/asns/${key}`
  const q = useQuery({ queryKey: ['net', kind, key], queryFn: () => get<NetEntity>(url) })
  return (
    <DataState query={q}>
      {(e) => (
        <>
          <PageHeader title={kind === 'ip' ? `IP ${e.key}` : `AS${e.key}`} subtitle="Network-layer entity" />
          <p className="mb-3 rounded border border-accent-2/30 bg-accent-2/5 p-2 text-xs text-accent-2">{e.notice}</p>
          <Card className="mb-4 p-4">
            {e.features ? <KV cols={3} items={Object.entries(e.features).map(([k, v]) => [titleCase(k), typeof v === 'number' ? formatNumber(v, 2) : (v ?? '—')])} /> : <Unavailable reason="features not computed" />}
          </Card>
          <Card className="mb-4">
            <CardHeader title="Correlation indicators" />
            {e.indicators.length === 0 ? <Unavailable reason="no indicators for this entity" /> : (
              <ul className="divide-y divide-line text-sm">{e.indicators.map((i) => (
                <li key={i.id} className="space-y-1 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2"><Badge tone="warn">{titleCase(i.indicator_type)}</Badge><span className="text-xs text-muted">strength {i.strength.toFixed(2)} · confidence {i.confidence.toFixed(2)} · {formatDate(i.window_start)} → {formatDate(i.window_end)}</span></div>
                  <div className="mono text-xs text-muted">{JSON.stringify(i.metrics)}</div>
                  <p className="text-xs text-muted">{i.limitations}</p>
                </li>
              ))}</ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Recent observations" />
            <Table>
              <thead><tr><Th>Observed</Th><Th>txid</Th><Th>Source</Th><Th>Destination</Th><Th>Tx risk</Th></tr></thead>
              <tbody>{e.recent_observations.map((o) => (
                <tr key={o.id}>
                  <Td className="mono text-xs">{formatDate(o.observed_at)}</Td>
                  <Td><Link className="mono text-accent-2 hover:underline" to={`/transactions/${o.txid}`}>{shortHash(o.txid)}</Link></Td>
                  <Td className="mono">{o.src_ip}</Td><Td className="mono">{o.dst_ip}:{o.dst_port}</Td>
                  <Td><RiskScore score={o.tx_risk?.score} band={o.tx_risk?.band} entityType="transaction" entityKey={o.txid} /></Td>
                </tr>
              ))}</tbody>
            </Table>
          </Card>
        </>
      )}
    </DataState>
  )
}
