import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AlertStatusBadge, BandBadge, RiskScore } from '@/components/badges'
import { Pagination, SortTh } from '@/components/Pagination'
import { DataState, Empty } from '@/components/states'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, KV, Select, Table, Td, Textarea, Th } from '@/components/ui/primitives'
import { AddToCase } from '@/features/investigations/AddToCase'
import { useSearchState } from '@/hooks/useSearchState'
import { PageHeader } from '@/layouts/AppLayout'
import { get, patch, post, problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { Alert, AlertDetail, AlertStatus, Paginated } from '@/types/api'
import { formatDate, shortHash, titleCase } from '@/utils/format'

const LIMIT = 50
const ACTION_LABEL: Record<AlertStatus, string> = {
  new: 'Reopen', acknowledged: 'Acknowledge', under_investigation: 'Start investigation', escalated: 'Escalate',
  resolved: 'Resolve', false_positive: 'Mark false positive',
}
const CATEGORIES = ['high_anomaly_score', 'high_fan_out', 'high_fan_in', 'repeated_transaction_splitting', 'unusual_consolidation', 'suspicious_graph_pattern',
  'potential_layering_pattern', 'circular_transaction_pattern', 'rapid_transaction_movement', 'unusual_transaction_amount', 'unusual_transaction_frequency',
  'unusual_wallet_behaviour', 'new_unusual_transaction_cluster', 'network_blockchain_correlation_anomaly']

export default function AlertsPage() {
  const { get: g, set } = useSearchState()
  const { user } = useAuth()
  const status = g('status') ?? 'open'
  const params = {
    status: status === 'open' ? ['new', 'acknowledged', 'under_investigation', 'escalated'] : status === 'all' ? undefined : [status],
    severity: g('severity') ? [g('severity')] : undefined, category: g('category') ?? undefined, q: g('q') ?? undefined,
    assigned_to: g('mine') ? user?.id : undefined, sort: g('sort') ?? '-risk_score', limit: LIMIT, offset: Number(g('offset') ?? 0),
  }
  const q = useQuery({ queryKey: ['alerts', params], queryFn: () => get<Paginated<Alert>>('/alerts', params), placeholderData: (p) => p })
  return (
    <>
      <PageHeader title="Alert queue" subtitle="Generated only from actual detection results. Every alert is an investigative lead, not a conclusion." />
      <Card className="mb-4 p-3">
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Field label="Status">
            <Select value={status} onChange={(e) => set({ status: e.target.value })}>
              <option value="open">Open (all active)</option><option value="all">All</option>
              {['new', 'acknowledged', 'under_investigation', 'escalated', 'resolved', 'false_positive'].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </Select>
          </Field>
          <Field label="Severity">
            <Select value={g('severity') ?? ''} onChange={(e) => set({ severity: e.target.value })}>
              <option value="">Any</option>{['high', 'elevated', 'moderate', 'low'].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
            </Select>
          </Field>
          <Field label="Category">
            <Select value={g('category') ?? ''} onChange={(e) => set({ category: e.target.value })}>
              <option value="">Any</option>{CATEGORIES.map((c) => <option key={c} value={c}>{titleCase(c)}</option>)}
            </Select>
          </Field>
          <Field label="Search"><Input defaultValue={g('q') ?? ''} placeholder="txid / address / IP" onKeyDown={(e) => { if (e.key === 'Enter') set({ q: (e.target as HTMLInputElement).value }) }} /></Field>
          <Field label="Assignment">
            <Select value={g('mine') ? 'mine' : ''} onChange={(e) => set({ mine: e.target.value || null })}><option value="">Everyone</option><option value="mine">Assigned to me</option></Select>
          </Field>
        </div>
      </Card>
      <Card>
        <DataState query={q} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No alerts match these filters" />}>
          {(d) => (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>Severity</Th><Th>Alert</Th><SortTh label="Category" field="category" sort={params.sort} onSort={(s) => set({ sort: s })} />
                    <SortTh label="Risk" field="risk_score" sort={params.sort} onSort={(s) => set({ sort: s })} /><Th>Confidence</Th>
                    <SortTh label="Status" field="status" sort={params.sort} onSort={(s) => set({ sort: s })} />
                    <SortTh label="Created" field="created_at" sort={params.sort} onSort={(s) => set({ sort: s })} />
                  </tr>
                </thead>
                <tbody>{d.items.map((a) => (
                  <tr key={a.id} className="hover:bg-bg-2">
                    <Td><BandBadge band={a.severity} /></Td>
                    <Td className="max-w-md"><Link to={`/alerts/${a.id}`} className="block truncate text-accent-2 hover:underline">{a.title}</Link></Td>
                    <Td className="text-xs">{titleCase(a.category)}</Td>
                    <Td>{a.txid ? <RiskScore score={a.risk_score} entityType="transaction" entityKey={a.txid} /> : <span className="mono">{a.risk_score ?? '—'}</span>}</Td>
                    <Td><Badge>{a.confidence}</Badge></Td>
                    <Td><AlertStatusBadge status={a.status} /></Td>
                    <Td className="mono text-xs">{formatDate(a.created_at)}</Td>
                  </tr>
                ))}</tbody>
              </Table>
              <Pagination total={d.total} limit={LIMIT} offset={params.offset} onChange={(o) => set({ offset: o }, false)} />
            </>
          )}
        </DataState>
      </Card>
    </>
  )
}

export function AlertDetailPage() {
  const { id = '' } = useParams()
  const { can, user } = useAuth()
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const q = useQuery({ queryKey: ['alert', id], queryFn: () => get<AlertDetail>(`/alerts/${id}`) })
  const assignable = useQuery({ queryKey: ['assignable'], queryFn: () => get<{ id: string; full_name: string; email: string }[]>('/admin/users/assignable') })
  const done = { onSuccess: () => { setNote(''); setErr(null); void qc.invalidateQueries({ queryKey: ['alert', id] }); void qc.invalidateQueries({ queryKey: ['alerts'] }) }, onError: (e: unknown) => setErr(problemMessage(e)) }
  const move = useMutation({ mutationFn: (to: AlertStatus) => (to === 'resolved' || to === 'false_positive'
    ? post(`/alerts/${id}/resolve`, { note, false_positive: to === 'false_positive' })
    : to === 'acknowledged' ? post(`/alerts/${id}/acknowledge`) : patch(`/alerts/${id}`, { status: to, note: note || undefined })), ...done })
  const addNote = useMutation({ mutationFn: () => patch(`/alerts/${id}`, { note }), ...done })
  const assign = useMutation({ mutationFn: (uid: string) => patch(`/alerts/${id}`, uid ? { assigned_to: uid } : { unassign: true }), ...done })

  return (
    <DataState query={q}>
      {(a) => (
        <>
          <PageHeader title={a.title} subtitle={`${titleCase(a.category)} · ${a.detection_method} · created ${formatDate(a.created_at)}${a.occurrence_count > 1 ? ` · seen ${a.occurrence_count}×` : ''}`}
            actions={<><BandBadge band={a.severity} /><AlertStatusBadge status={a.status} /><AddToCase alertIds={[a.id]} txids={a.txid ? [a.txid] : []} evidence={{ evidence_type: 'alert', reference: a.id }} /></>} />
          <div className="grid gap-4 xl:grid-cols-3">
            <div className="space-y-4 xl:col-span-2">
              <Card>
                <CardHeader title="What happened & why it was flagged" />
                <CardBody className="space-y-3 text-sm">
                  <p>{a.explanation}</p>
                  <KV cols={3} items={[
                    ['Entity', `${a.entity_type}: ${shortHash(a.entity_key, 12)}`],
                    ['Risk score', a.txid ? <RiskScore key="r" score={a.risk_score} entityType="transaction" entityKey={a.txid} /> : (a.risk_score ?? '—')],
                    ['Confidence', a.confidence], ['Model version', a.model_version_id ? shortHash(a.model_version_id, 8) : 'n/a'],
                  ]} />
                  <p className="rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn"><b>What remains uncertain:</b> {a.uncertainty_notes}</p>
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Triggered rules" />
                <CardBody><pre className="mono overflow-x-auto whitespace-pre-wrap text-xs text-muted">{JSON.stringify(a.triggered_rules, null, 1)}</pre></CardBody>
              </Card>
              <Card>
                <CardHeader title="Evidence" subtitle="Associated transaction, addresses and network observations" />
                <CardBody className="space-y-2 text-sm">
                  {a.txid && <p>Transaction: <Link className="mono text-accent-2 hover:underline" to={`/transactions/${a.txid}`}>{a.txid}</Link></p>}
                  {a.entity_type === 'ip' && <p>Source IP: <Link className="mono text-accent-2 hover:underline" to={`/network/ip/${encodeURIComponent(a.entity_key)}`}>{a.entity_key}</Link></p>}
                  <p className="text-muted">Addresses ({a.addresses.length}):</p>
                  <div className="flex flex-wrap gap-2">{a.addresses.slice(0, 40).map((x) => <Link key={x} className="mono text-xs text-accent-2 hover:underline" to={`/addresses/${encodeURIComponent(x)}`}>{shortHash(x, 8)}</Link>)}</div>
                  <p className="text-muted">Network observations: {a.network_observation_ids.length || 'none'}</p>
                  <pre className="mono overflow-x-auto text-xs text-muted">{JSON.stringify(a.evidence_refs, null, 1).slice(0, 1500)}</pre>
                </CardBody>
              </Card>
            </div>
            <div className="space-y-4">
              <Card>
                <CardHeader title="Workflow" />
                <CardBody className="space-y-3">
                  {can('alert.acknowledge') && (
                    <Field label="Assigned analyst">
                      <Select value={a.assigned_to ?? ''} onChange={(e) => assign.mutate(e.target.value)} disabled={assign.isPending}>
                        <option value="">Unassigned</option>
                        {assignable.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name}{u.id === user?.id ? ' (me)' : ''}</option>)}
                      </Select>
                    </Field>
                  )}
                  <Field label="Note / resolution reason"><Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Required to resolve or mark false positive" /></Field>
                  <div className="flex flex-wrap gap-2">
                    {a.allowed_transitions.map((t) => (
                      <Button key={t} size="sm" variant={t === 'false_positive' ? 'secondary' : t === 'escalated' ? 'danger' : 'primary'} disabled={move.isPending}
                        onClick={() => move.mutate(t)}>{ACTION_LABEL[t]}</Button>
                    ))}
                    <Button size="sm" variant="ghost" disabled={!note.trim() || addNote.isPending} onClick={() => addNote.mutate()}>Add note</Button>
                  </div>
                  {err && <p role="alert" className="text-xs text-crit">{err}</p>}
                  {a.resolution_note && <p className="text-xs"><span className="text-muted">Resolution: </span>{a.resolution_note}</p>}
                </CardBody>
              </Card>
              <Card>
                <CardHeader title={`Notes (${a.notes.length})`} />
                {a.notes.length === 0 ? <Empty title="No notes yet" /> : (
                  <ul className="divide-y divide-line text-sm">{a.notes.map((n) => <li key={n.id} className="px-4 py-2"><div className="mono text-xs text-muted">{formatDate(n.created_at)}</div><p className="whitespace-pre-wrap">{n.body}</p></li>)}</ul>
                )}
              </Card>
              <Card>
                <CardHeader title="Related alerts" />
                {a.related_alerts.length === 0 ? <Empty title="None" /> : (
                  <ul className="divide-y divide-line text-sm">{a.related_alerts.map((r) => <li key={r.id}><Link to={`/alerts/${r.id}`} className="flex items-center gap-2 px-4 py-2 hover:bg-bg-2"><BandBadge band={r.severity} />{titleCase(r.category)}<span className="ml-auto"><AlertStatusBadge status={r.status} /></span></Link></li>)}</ul>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
    </DataState>
  )
}
