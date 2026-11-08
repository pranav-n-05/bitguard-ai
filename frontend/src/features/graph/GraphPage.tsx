import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { DataState, Empty } from '@/components/states'
import { Pagination } from '@/components/Pagination'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, Table, Tabs, Td, Th, Textarea } from '@/components/ui/primitives'
import { PageHeader } from '@/layouts/AppLayout'
import { get, patch, problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { CyElements, Detection, Paginated } from '@/types/api'
import { formatDate, shortHash, titleCase } from '@/utils/format'
import { CyGraph, Legend, nodeRoute } from './CyGraph'
import { GraphPanel } from './GraphPanel'
import { useNavigate } from 'react-router-dom'

type Tab = 'explore' | 'path' | 'detections' | 'clusters'
interface Cluster { id: string; method: string; confidence: number; size: number; evidence: Record<string, unknown>; limitations: string; review_status: string; created_at: string }

export default function GraphPage() {
  const [tab, setTab] = useState<Tab>('explore')
  return (
    <>
      <PageHeader title="Graph intelligence" subtitle="Bipartite Address → Transaction → Address graph with network, cluster and case context." />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: 'explore', label: 'Explore' }, { id: 'path', label: 'Path analysis' }, { id: 'detections', label: 'Pattern detections' }, { id: 'clusters', label: 'Clusters' }]} />
      <div className="mt-4">
        {tab === 'explore' && <Explore />}
        {tab === 'path' && <PathAnalysis />}
        {tab === 'detections' && <Detections />}
        {tab === 'clusters' && <Clusters />}
      </div>
    </>
  )
}

function Explore() {
  const [center, setCenter] = useState<string | null>(null)
  const [v, setV] = useState('')
  const url = center ? (/^[0-9a-f]{64}$/i.test(center) ? `/transactions/${center.toLowerCase()}/graph` : `/addresses/${encodeURIComponent(center)}/graph`) : null
  return (
    <Card>
      <CardBody className="space-y-3">
        <form className="flex max-w-2xl gap-2" onSubmit={(e) => { e.preventDefault(); setCenter(v.trim() || null) }}>
          <Input aria-label="Center entity" placeholder="txid or address to centre the graph on" value={v} onChange={(e) => setV(e.target.value)} />
          <Button type="submit" variant="primary">Expand</Button>
        </form>
        {url ? <GraphPanel key={url} url={url} height={600} /> : <Empty title="Choose a transaction or address">Click a node to inspect it; use “Open” to jump to its investigation view.</Empty>}
      </CardBody>
    </Card>
  )
}

function PathAnalysis() {
  const nav = useNavigate()
  const [form, setForm] = useState({ source: '', target: '', max_hops: 4 })
  const [run, setRun] = useState<typeof form | null>(null)
  const q = useQuery({ queryKey: ['path', run], enabled: !!run, queryFn: () => get<CyElements & { found: boolean; hops?: number; path: string[]; searched_nodes?: number; truncated?: boolean }>('/graph/path', run!) })
  function submit(e: FormEvent) { e.preventDefault(); setRun({ ...form }) }
  return (
    <Card>
      <CardBody className="space-y-3">
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-[1fr_1fr_100px_auto] md:items-end">
          <Field label="Source address"><Input required value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value.trim() })} /></Field>
          <Field label="Target address"><Input required value={form.target} onChange={(e) => setForm({ ...form, target: e.target.value.trim() })} /></Field>
          <Field label="Max hops"><Select value={form.max_hops} onChange={(e) => setForm({ ...form, max_hops: Number(e.target.value) })}>{[1, 2, 3, 4, 5, 6, 7, 8].map((h) => <option key={h}>{h}</option>)}</Select></Field>
          <Button type="submit" variant="primary">Find path</Button>
        </form>
        {run && (
          <DataState query={q}>
            {(p) => p.found ? (
              <>
                <p className="text-sm">Path found through <b>{p.hops}</b> transaction(s). Direction is ignored for reachability; see edges for flow direction.</p>
                <CyGraph elements={p} height={420} onSelect={(d) => { const r = nodeRoute(d); if (r) nav(r) }} />
                <Legend />
              </>
            ) : <Empty title="No path within the hop/node budget">Searched {p.searched_nodes} nodes{p.truncated ? ' (truncated)' : ''}. Increase max hops or check the addresses.</Empty>}
          </DataState>
        )}
      </CardBody>
    </Card>
  )
}

function Detections() {
  const [pattern, setPattern] = useState('')
  const [offset, setOffset] = useState(0)
  const q = useQuery({ queryKey: ['detections', pattern, offset], queryFn: () => get<Paginated<Detection & { window_start: string | null }>>('/graph/detections', { pattern: pattern || undefined, limit: 25, offset }) })
  return (
    <Card>
      <CardHeader title="Structural pattern detections" subtitle="Heuristic graph findings; each lists its own limitations"
        actions={<Select aria-label="Pattern filter" value={pattern} onChange={(e) => { setPattern(e.target.value); setOffset(0) }} className="w-48">
          <option value="">All patterns</option>{['high_fan_out', 'high_fan_in', 'peel_chain', 'rapid_layering', 'circular_flow'].map((p) => <option key={p} value={p}>{titleCase(p)}</option>)}
        </Select>} />
      <DataState query={q} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No detections" />}>
        {(d) => (
          <>
            <ul className="divide-y divide-line text-sm">
              {d.items.map((x) => (
                <li key={x.id} className="space-y-1 px-4 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="warn">{titleCase(x.pattern)}</Badge><span className="text-xs text-muted">confidence {x.confidence.toFixed(2)} · {formatDate(x.window_start)}</span>
                    {x.anchor_txid && <Link className="mono ml-auto text-xs text-accent-2 hover:underline" to={`/transactions/${x.anchor_txid}?tab=graph`}>{shortHash(x.anchor_txid)}</Link>}
                  </div>
                  <p>{x.explanation}</p>
                  <p className="text-xs text-muted">{x.limitations}</p>
                </li>
              ))}
            </ul>
            <Pagination total={d.total} limit={25} offset={offset} onChange={setOffset} />
          </>
        )}
      </DataState>
    </Card>
  )
}

function Clusters() {
  const [method, setMethod] = useState('common_input')
  const [offset, setOffset] = useState(0)
  const q = useQuery({ queryKey: ['clusters', method, offset], queryFn: () => get<Paginated<Cluster>>('/graph/clusters', { method, limit: 25, offset, min_size: 2 }) })
  return (
    <Card>
      <CardHeader title="Address clusters" subtitle="Probabilistic investigative aids — never confirmed real-world entities"
        actions={<Select aria-label="Method" value={method} onChange={(e) => { setMethod(e.target.value); setOffset(0) }} className="w-48">
          <option value="common_input">Common input</option><option value="change_output">Change output</option><option value="behavioural">Behavioural</option>
        </Select>} />
      <DataState query={q} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No clusters for this method" />}>
        {(d) => (
          <>
            <Table>
              <thead><tr><Th>Cluster</Th><Th>Size</Th><Th>Confidence</Th><Th>Review</Th><Th>Created</Th></tr></thead>
              <tbody>{d.items.map((c) => (
                <tr key={c.id}>
                  <Td><Link className="mono text-accent-2 hover:underline" to={`/graph/clusters/${c.id}`}>{shortHash(c.id, 8)}</Link></Td>
                  <Td className="num">{c.size}</Td><Td className="mono">{c.confidence.toFixed(2)}</Td><Td><Badge>{titleCase(c.review_status)}</Badge></Td>
                  <Td className="mono text-xs">{formatDate(c.created_at)}</Td>
                </tr>
              ))}</tbody>
            </Table>
            <Pagination total={d.total} limit={25} offset={offset} onChange={setOffset} />
          </>
        )}
      </DataState>
    </Card>
  )
}

export function ClusterPage() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const qc = useQueryClient()
  const [note, setNote] = useState('')
  const q = useQuery({ queryKey: ['cluster', id], queryFn: () => get<Cluster & { members: { address: string; link_confidence: number; evidence_txids: string[] }[] }>(`/graph/clusters/${id}`) })
  const review = useMutation({
    mutationFn: (status: string) => patch(`/graph/clusters/${id}`, { review_status: status, note: note || undefined }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['cluster', id] }),
  })
  return (
    <DataState query={q}>
      {(c) => (
        <>
          <PageHeader title={`${titleCase(c.method)} cluster`} subtitle={`${c.size} addresses · confidence ${c.confidence.toFixed(2)} · ${titleCase(c.review_status)}`} />
          <p className="mb-3 rounded border border-warn/30 bg-warn/5 p-2 text-xs text-warn">{c.limitations}</p>
          {can('alert.acknowledge') && (
            <Card className="mb-4 p-4">
              <div className="flex flex-wrap items-end gap-2">
                <Field label="Review note"><Textarea className="min-h-10 w-96" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
                <Button onClick={() => review.mutate('confirmed_by_analyst')} disabled={review.isPending}>Mark plausible</Button>
                <Button onClick={() => review.mutate('rejected_by_analyst')} disabled={review.isPending}>Reject</Button>
              </div>
              {review.isError && <p className="mt-2 text-xs text-crit">{problemMessage(review.error)}</p>}
            </Card>
          )}
          <Card>
            <CardHeader title="Members" subtitle="Link confidence reflects supporting co-spend / change evidence" />
            <Table>
              <thead><tr><Th>Address</Th><Th>Link confidence</Th><Th>Evidence transactions</Th></tr></thead>
              <tbody>{c.members.map((m) => (
                <tr key={m.address}>
                  <Td><Link className="mono text-accent-2 hover:underline" to={`/addresses/${encodeURIComponent(m.address)}`}>{shortHash(m.address, 12)}</Link></Td>
                  <Td className="mono">{m.link_confidence.toFixed(2)}</Td>
                  <Td className="space-x-2">{m.evidence_txids.slice(0, 4).map((t) => <Link key={t} className="mono text-xs text-accent-2 hover:underline" to={`/transactions/${t}`}>{shortHash(t, 6)}</Link>)}</Td>
                </tr>
              ))}</tbody>
            </Table>
          </Card>
        </>
      )}
    </DataState>
  )
}
