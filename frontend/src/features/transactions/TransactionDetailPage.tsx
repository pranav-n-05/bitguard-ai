import { useQuery } from '@tanstack/react-query'
import { useParams, useSearchParams } from 'react-router-dom'
import { DataLabel, RiskScore } from '@/components/badges'
import { AddToCase } from '@/features/investigations/AddToCase'
import { GraphPanel } from '@/features/graph/GraphPanel'
import { DataState, Unavailable } from '@/components/states'
import { Badge, Card, CardBody, CardHeader, CopyText, KV, Table, Tabs, Td, Th } from '@/components/ui/primitives'
import { PageHeader } from '@/layouts/AppLayout'
import { get } from '@/services/api'
import type { TxDetail } from '@/types/api'
import { formatDate, formatNumber, formatSat, satToBtc, shortHash, titleCase } from '@/utils/format'
import { IoList } from './TransactionsPage'
import { RiskPanel } from './RiskPanel'
import { Link } from 'react-router-dom'

type Tab = 'overview' | 'graph' | 'risk' | 'features' | 'network'

export default function TransactionDetailPage() {
  const { txid = '' } = useParams()
  const [sp, setSp] = useSearchParams()
  const tab = (sp.get('tab') as Tab) ?? 'overview'
  const q = useQuery({ queryKey: ['tx', txid], queryFn: () => get<TxDetail>(`/transactions/${txid}`) })

  return (
    <DataState query={q}>
      {(t) => (
        <>
          <PageHeader title="Transaction" subtitle={formatDate(t.first_seen_at)}
            actions={<>{t.data_labels.map((l) => <DataLabel key={l} label={l} />)}<AddToCase txids={[t.txid]} evidence={{ evidence_type: 'transaction', reference: t.txid }} /></>} />
          <Card className="mb-4 p-4">
            <div className="mb-3"><CopyText value={t.txid} /></div>
            <KV cols={3} items={[
              ['Total input', satToBtc(t.total_input_sat)], ['Total output', satToBtc(t.total_output_sat)], ['Fee', `${formatSat(t.fee_sat)}${t.vsize ? ` · ${(t.fee_sat / t.vsize).toFixed(2)} sat/vB` : ''}`],
              ['Inputs / outputs', `${t.input_count} / ${t.output_count}`], ['Block', t.block_height ?? '—'],
              ['Risk', <RiskScore key="r" score={t.risk?.score} band={t.risk?.band} entityType="transaction" entityKey={t.txid} />],
            ]} />
          </Card>
          <Tabs<Tab> value={tab} onChange={(v) => setSp({ tab: v })} tabs={[
            { id: 'overview', label: 'Inputs & outputs' }, { id: 'graph', label: 'Graph' }, { id: 'risk', label: 'Risk & explanation' },
            { id: 'features', label: 'Features' }, { id: 'network', label: `Network (${t.observations.length})` },
          ]} />
          <div className="mt-4">
            {tab === 'overview' && (
              <div className="space-y-4">
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card><CardBody><IoList title={`Inputs (${t.inputs.length})`} rows={t.inputs} /></CardBody></Card>
                  <Card><CardBody><IoList title={`Outputs (${t.outputs.length})`} rows={t.outputs} /></CardBody></Card>
                </div>
                <Card>
                  <CardHeader title="Structural detections (heuristic)" />
                  {t.graph_detections.length === 0 ? <Unavailable reason="no structural pattern detected" /> : (
                    <ul className="divide-y divide-line text-sm">
                      {t.graph_detections.map((d) => (
                        <li key={d.id} className="space-y-1 px-4 py-3">
                          <div className="flex items-center gap-2"><Badge tone="warn">{titleCase(d.pattern)}</Badge><span className="text-xs text-muted">confidence {d.confidence.toFixed(2)}</span></div>
                          <p>{d.explanation}</p>
                          <p className="text-xs text-muted">{d.limitations}</p>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
                <Card>
                  <CardHeader title="Provenance" subtitle="Raw observed facts trace back to an immutable staged source record" />
                  <CardBody>
                    <KV items={[
                      ['Dataset', `${t.provenance.dataset_name} (${t.provenance.provenance})`], ['Source file', t.provenance.file_name],
                      ['File SHA-256', <CopyText key="f" value={t.provenance.file_sha256} display={shortHash(t.provenance.file_sha256, 12)} />],
                      ['Record #', t.provenance.record_index], ['Record hash', <CopyText key="h" value={t.provenance.record_hash} display={shortHash(t.provenance.record_hash, 12)} />],
                      ['Content hash', <CopyText key="c" value={t.content_hash} display={shortHash(t.content_hash, 12)} />],
                    ]} />
                  </CardBody>
                </Card>
              </div>
            )}
            {tab === 'graph' && <Card><CardBody><GraphPanel url={`/transactions/${t.txid}/graph`} defaultHops={2} /></CardBody></Card>}
            {tab === 'risk' && <RiskPanel entityType="transaction" entityKey={t.txid} />}
            {tab === 'features' && (
              <Card>
                <CardHeader title="Derived features" subtitle={`Schema ${t.feature_schema_version ?? '—'}; computed only from data available at first sighting (+60 s observation window)`} />
                {!t.features ? <Unavailable reason="features not computed yet" /> : (
                  <Table><tbody>
                    {Object.entries(t.features).map(([k, v]) => <tr key={k}><Td className="mono text-xs">{k}</Td><Td className="mono">{v === null ? <Badge>unavailable</Badge> : formatNumber(v, 4)}</Td></tr>)}
                  </tbody></Table>
                )}
              </Card>
            )}
            {tab === 'network' && (
              <Card>
                <CardHeader title="Network observations" subtitle="Co-occurrence/timing only — an IP relaying or announcing a transaction does not identify who controls any address." />
                {t.observations.length === 0 ? <Unavailable reason="no network observations recorded" /> : (
                  <Table>
                    <thead><tr><Th>Observed</Th><Th>Source</Th><Th>Destination</Th><Th>ASN</Th><Th>Country</Th></tr></thead>
                    <tbody>
                      {t.observations.map((o) => (
                        <tr key={o.id}>
                          <Td className="mono text-xs">{formatDate(o.observed_at)}</Td>
                          <Td><Link className="mono text-accent-2 hover:underline" to={`/network/ip/${encodeURIComponent(o.src_ip)}`}>{o.src_ip}:{o.src_port}</Link></Td>
                          <Td className="mono">{o.dst_ip}:{o.dst_port}</Td>
                          <Td>{o.asn !== null ? <Link className="text-accent-2 hover:underline" to={`/network/asn/${o.asn}`}>AS{o.asn}</Link> : <Badge>unavailable</Badge>}</Td>
                          <Td>{o.geo_country ?? <Badge>unavailable</Badge>}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
              </Card>
            )}
          </div>
        </>
      )}
    </DataState>
  )
}
