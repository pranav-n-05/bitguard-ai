import { useQuery } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { RiskScore } from '@/components/badges'
import { Pagination } from '@/components/Pagination'
import { DataState, Empty, Unavailable } from '@/components/states'
import { Badge, Button, Card, CardBody, CardHeader, CopyText, Input, KV, Table, Tabs, Td, Th } from '@/components/ui/primitives'
import { GraphPanel } from '@/features/graph/GraphPanel'
import { AddToCase } from '@/features/investigations/AddToCase'
import { RiskPanel } from '@/features/transactions/RiskPanel'
import { PageHeader } from '@/layouts/AppLayout'
import { get } from '@/services/api'
import type { AddressInfo, Paginated, Tx } from '@/types/api'
import { formatDate, formatNumber, satToBtc, shortHash, titleCase } from '@/utils/format'

type Tab = 'activity' | 'graph' | 'risk' | 'related' | 'history'

export function AddressSearchPage() {
  const nav = useNavigate()
  const [v, setV] = useState('')
  function go(e: FormEvent) {
    e.preventDefault()
    if (v.trim()) nav(`/addresses/${encodeURIComponent(v.trim())}`)
  }
  return (
    <>
      <PageHeader title="Address investigation" subtitle="Look up an address present in the ingested data." />
      <Card className="max-w-xl p-4">
        <form onSubmit={go} className="flex gap-2">
          <Input aria-label="Bitcoin address" placeholder="bc1q… / 1… / 3…" value={v} onChange={(e) => setV(e.target.value)} />
          <Button type="submit" variant="primary">Open</Button>
        </form>
      </Card>
    </>
  )
}

export default function AddressPage() {
  const { address = '' } = useParams()
  const [sp, setSp] = useSearchParams()
  const tab = (sp.get('tab') as Tab) ?? 'activity'
  const offset = Number(sp.get('offset') ?? 0)
  const q = useQuery({ queryKey: ['address', address], queryFn: () => get<AddressInfo>(`/addresses/${encodeURIComponent(address)}`) })
  const stats = useQuery({ queryKey: ['address-stats', address], queryFn: () => get<{ received_sat: number; spent_sat: number; balance_estimate_sat: number; balance_note: string; received_outputs: number; spent_inputs: number }>(`/addresses/${encodeURIComponent(address)}/statistics`) })
  const txs = useQuery({ queryKey: ['address-txs', address, offset], enabled: tab === 'activity', queryFn: () => get<Paginated<Tx>>(`/addresses/${encodeURIComponent(address)}/transactions`, { limit: 25, offset }) })

  return (
    <DataState query={q}>
      {(a) => (
        <>
          <PageHeader title="Address" subtitle={`${a.address_type} · ${a.network}`} actions={<AddToCase addresses={[a.address]} evidence={{ evidence_type: 'address', reference: a.address }} />} />
          <p className="mb-3 rounded border border-accent-2/30 bg-accent-2/5 p-2 text-xs text-accent-2">{a.notice}</p>
          <Card className="mb-4 p-4">
            <div className="mb-3"><CopyText value={a.address} /></div>
            <KV cols={3} items={[
              ['First seen', formatDate(a.first_seen_at)], ['Last seen', formatDate(a.last_seen_at)],
              ['Risk', <RiskScore key="r" score={a.risk?.score} band={a.risk?.band} entityType="address" entityKey={a.address} />],
              ['Received', stats.data ? satToBtc(stats.data.received_sat) : '—'], ['Spent', stats.data ? satToBtc(stats.data.spent_sat) : '—'],
              ['Balance estimate', stats.data ? <span key="b" title={stats.data.balance_note}>{satToBtc(stats.data.balance_estimate_sat)} *</span> : '—'],
            ]} />
            {stats.data && <p className="mt-2 text-xs text-muted">* {stats.data.balance_note}</p>}
          </Card>
          <Tabs<Tab> value={tab} onChange={(v) => setSp({ tab: v })} tabs={[
            { id: 'activity', label: 'Activity' }, { id: 'graph', label: 'Graph' }, { id: 'risk', label: 'Risk indicators' },
            { id: 'related', label: `Related (${a.clusters.length} clusters)` }, { id: 'history', label: 'Investigations' },
          ]} />
          <div className="mt-4">
            {tab === 'activity' && (
              <Card>
                <DataState query={txs} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No transactions" />}>
                  {(d) => (
                    <>
                      <Table>
                        <thead><tr><Th>txid</Th><Th>First seen</Th><Th>Value</Th><Th>In/Out</Th><Th>Risk</Th></tr></thead>
                        <tbody>
                          {d.items.map((t) => (
                            <tr key={t.txid}>
                              <Td><Link className="mono text-accent-2 hover:underline" to={`/transactions/${t.txid}`}>{shortHash(t.txid)}</Link></Td>
                              <Td className="mono text-xs">{formatDate(t.first_seen_at)}</Td>
                              <Td className="mono">{satToBtc(t.total_output_sat)}</Td>
                              <Td>{t.input_count}/{t.output_count}</Td>
                              <Td><RiskScore score={t.risk?.score} band={t.risk?.band} entityType="transaction" entityKey={t.txid} /></Td>
                            </tr>
                          ))}
                        </tbody>
                      </Table>
                      <Pagination total={d.total} limit={25} offset={offset} onChange={(o) => setSp({ tab, offset: String(o) })} />
                    </>
                  )}
                </DataState>
              </Card>
            )}
            {tab === 'graph' && <Card><CardBody><GraphPanel url={`/addresses/${encodeURIComponent(a.address)}/graph`} /></CardBody></Card>}
            {tab === 'risk' && (
              <div className="space-y-4">
                <RiskPanel entityType="address" entityKey={a.address} />
                <Card>
                  <CardHeader title="Network co-occurrence indicators" />
                  {a.correlations.length === 0 ? <Unavailable reason="no indicators" /> : (
                    <ul className="divide-y divide-line text-sm">{a.correlations.map((c) => (
                      <li key={c.id} className="px-4 py-2"><Badge tone="info">{titleCase(c.type)}</Badge> <span className="text-xs text-muted">confidence {c.confidence.toFixed(2)} · {JSON.stringify(c.metrics)}</span><p className="text-xs text-muted">{c.limitations}</p></li>
                    ))}</ul>
                  )}
                </Card>
                <Card>
                  <CardHeader title="Address features" />
                  {!a.features ? <Unavailable reason="not computed" /> : (
                    <Table><tbody>{Object.entries(a.features).filter(([k]) => k !== 'cluster_ids').map(([k, v]) => (
                      <tr key={k}><Td className="mono text-xs">{k}</Td><Td className="mono">{v === null ? <Badge>unavailable</Badge> : typeof v === 'number' ? formatNumber(v, 4) : String(v)}</Td></tr>
                    ))}</tbody></Table>
                  )}
                </Card>
              </div>
            )}
            {tab === 'related' && (
              <Card>
                <CardHeader title="Probabilistic clusters" subtitle="Clusters are investigative aids, never confirmed real-world entities." />
                {a.clusters.length === 0 ? <Unavailable reason="address is not in any cluster" /> : (
                  <Table>
                    <thead><tr><Th>Method</Th><Th>Size</Th><Th>Cluster conf.</Th><Th>Link conf.</Th><Th>Review</Th><Th /></tr></thead>
                    <tbody>{a.clusters.map((c) => (
                      <tr key={c.cluster_id}>
                        <Td>{titleCase(c.method)}</Td><Td className="num">{c.size}</Td><Td className="mono">{c.cluster_confidence.toFixed(2)}</Td>
                        <Td className="mono">{c.link_confidence.toFixed(2)}</Td><Td><Badge>{titleCase(c.review_status)}</Badge></Td>
                        <Td><Link className="text-accent-2 hover:underline" to={`/graph/clusters/${c.cluster_id}`}>Open</Link></Td>
                      </tr>
                    ))}</tbody>
                  </Table>
                )}
              </Card>
            )}
            {tab === 'history' && (
              <Card>
                <CardHeader title="Investigation history" />
                {a.investigations.length === 0 ? <Unavailable reason="not linked to any investigation" /> : (
                  <ul className="divide-y divide-line text-sm">{a.investigations.map((i) => <li key={i} className="px-4 py-2"><Link className="text-accent-2 hover:underline" to={`/investigations/${i}`}>{i}</Link></li>)}</ul>
                )}
                <CardBody className="text-xs text-muted">Structural detections involving this address: {a.graph_detections.length ? a.graph_detections.map((d) => titleCase(d.pattern)).join(', ') : 'none'} · {formatNumber(a.graph_detections.length)} total</CardBody>
              </Card>
            )}
          </div>
        </>
      )}
    </DataState>
  )
}
