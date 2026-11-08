import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { z } from 'zod'
import { AlertStatusBadge, BandBadge, CaseStatusBadge, RiskScore } from '@/components/badges'
import { Pagination } from '@/components/Pagination'
import { DataState, Empty } from '@/components/states'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Modal, Select, Table, Tabs, Td, Textarea, Th } from '@/components/ui/primitives'
import { useSearchState } from '@/hooks/useSearchState'
import { PageHeader } from '@/layouts/AppLayout'
import { download, get, patch, post, problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { CaseBundle, CaseRow, Paginated, Report } from '@/types/api'
import { formatDate, shortHash, titleCase } from '@/utils/format'

const createSchema = z.object({
  title: z.string().trim().min(3, 'At least 3 characters').max(255),
  summary: z.string().max(20000).optional(),
  priority: z.enum(['low', 'moderate', 'elevated', 'high']),
})
type CreateForm = z.infer<typeof createSchema>

export default function InvestigationsPage() {
  const { can } = useAuth()
  const nav = useNavigate()
  const { get: g, set } = useSearchState()
  const [open, setOpen] = useState(false)
  const params = { status: g('status') ? [g('status')] : undefined, q: g('q') ?? undefined, limit: 50, offset: Number(g('offset') ?? 0) }
  const q = useQuery({ queryKey: ['cases', params], queryFn: () => get<Paginated<CaseRow>>('/investigations', params) })
  const form = useForm<CreateForm>({ resolver: zodResolver(createSchema), defaultValues: { title: '', summary: '', priority: 'moderate' } })
  const create = useMutation({ mutationFn: (v: CreateForm) => post<CaseRow>('/investigations', v), onSuccess: (c) => nav(`/investigations/${c.id}`) })

  return (
    <>
      <PageHeader title="Investigations" actions={can('case.create') && <Button variant="primary" onClick={() => setOpen(true)}>New investigation</Button>} />
      <Card className="mb-4 p-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Status"><Select value={g('status') ?? ''} onChange={(e) => set({ status: e.target.value })}><option value="">Any</option>{['open', 'in_progress', 'on_hold', 'closed'].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}</Select></Field>
          <Field label="Search"><Input defaultValue={g('q') ?? ''} placeholder="title or case number" onKeyDown={(e) => { if (e.key === 'Enter') set({ q: (e.target as HTMLInputElement).value }) }} /></Field>
        </div>
      </Card>
      <Card>
        <DataState query={q} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No investigations" />}>
          {(d) => (
            <>
              <Table>
                <thead><tr><Th>Case</Th><Th>Title</Th><Th>Priority</Th><Th>Status</Th><Th>Updated</Th></tr></thead>
                <tbody>{d.items.map((c) => (
                  <tr key={c.id} className="hover:bg-bg-2">
                    <Td className="mono text-xs">{c.case_number}</Td>
                    <Td><Link className="text-accent-2 hover:underline" to={`/investigations/${c.id}`}>{c.title}</Link></Td>
                    <Td><BandBadge band={c.priority} /></Td><Td><CaseStatusBadge status={c.status} /></Td>
                    <Td className="mono text-xs">{formatDate(c.updated_at)}</Td>
                  </tr>
                ))}</tbody>
              </Table>
              <Pagination total={d.total} limit={50} offset={params.offset} onChange={(o) => set({ offset: o }, false)} />
            </>
          )}
        </DataState>
      </Card>
      <Modal open={open} onOpenChange={setOpen} title="New investigation">
        <form className="mt-3 space-y-3" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <Field label="Title" error={form.formState.errors.title?.message}><Input {...form.register('title')} /></Field>
          <Field label="Summary"><Textarea {...form.register('summary')} /></Field>
          <Field label="Priority"><Select {...form.register('priority')}>{['low', 'moderate', 'elevated', 'high'].map((p) => <option key={p} value={p}>{titleCase(p)}</option>)}</Select></Field>
          {create.isError && <p role="alert" className="text-xs text-crit">{problemMessage(create.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" disabled={create.isPending}>Create</Button></div>
        </form>
      </Modal>
    </>
  )
}

type Tab = 'overview' | 'evidence' | 'notes' | 'timeline' | 'reports'

export function InvestigationDetailPage() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const qc = useQueryClient()
  const [tab, setTab] = useState<Tab>('overview')
  const [note, setNote] = useState('')
  const [decision, setDecision] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [verify, setVerify] = useState<Record<number, { verified: boolean; [k: string]: unknown }>>({})
  const [ev, setEv] = useState({ evidence_type: 'transaction', reference: '', description: '' })
  const q = useQuery({ queryKey: ['case', id], queryFn: () => get<CaseBundle>(`/investigations/${id}`) })
  const reports = useQuery({ queryKey: ['reports', id], enabled: tab === 'reports', queryFn: () => get<Paginated<Report>>('/reports', { investigation_id: id }) })
  const users = useQuery({ queryKey: ['assignable'], queryFn: () => get<{ id: string; full_name: string; email: string }[]>('/admin/users/assignable') })
  const ok = { onSuccess: () => { setErr(null); void qc.invalidateQueries({ queryKey: ['case', id] }); void qc.invalidateQueries({ queryKey: ['reports', id] }) }, onError: (e: unknown) => setErr(problemMessage(e)) }
  const update = useMutation({ mutationFn: (body: Record<string, unknown>) => patch(`/investigations/${id}`, body), ...ok })
  const addNote = useMutation({ mutationFn: () => post(`/investigations/${id}/notes`, { body: note }), ...ok, onSuccess: () => { setNote(''); ok.onSuccess() } })
  const addEv = useMutation({ mutationFn: () => post(`/investigations/${id}/evidence`, ev), ...ok, onSuccess: () => { setEv({ ...ev, reference: '', description: '' }); ok.onSuccess() } })
  const exp = useMutation({ mutationFn: async (fmt: string) => { const r = await post<Report>(`/investigations/${id}/export`, { format: fmt }); await download(`/reports/${r.id}/download`, `case.${fmt}`); return r }, ...ok })

  return (
    <DataState query={q}>
      {(b) => {
        const c = b.case
        const closed = c.status === 'closed'
        return (
          <>
            <PageHeader title={`${c.case_number} · ${c.title}`} subtitle={`Created ${formatDate(c.created_at)} by ${c.created_by} · assigned ${c.assigned_to ?? 'nobody'}`}
              actions={<><BandBadge band={c.priority} /><CaseStatusBadge status={c.status} />
                {can('report.generate') && ['pdf', 'json', 'csv'].map((f) => <Button key={f} size="sm" onClick={() => exp.mutate(f)} disabled={exp.isPending}>Export {f.toUpperCase()}</Button>)}</>} />
            {err && <p role="alert" className="mb-3 rounded border border-crit/40 bg-crit/10 p-2 text-sm text-crit">{err}</p>}
            <Tabs<Tab> value={tab} onChange={setTab} tabs={[{ id: 'overview', label: 'Linked entities' }, { id: 'evidence', label: `Evidence (${b.evidence.length})` }, { id: 'notes', label: `Notes (${b.notes.length})` }, { id: 'timeline', label: 'Timeline' }, { id: 'reports', label: 'Reports' }]} />
            <div className="mt-4">
              {tab === 'overview' && (
                <div className="grid gap-4 xl:grid-cols-3">
                  <div className="space-y-4 xl:col-span-2">
                    <Card>
                      <CardHeader title={`Transactions (${b.transactions.length})`} />
                      {b.transactions.length === 0 ? <Empty title="None linked" /> : (
                        <Table><thead><tr><Th>txid</Th><Th>First seen</Th><Th>Risk</Th></tr></thead><tbody>
                          {b.transactions.map((t) => <tr key={t.txid}><Td><Link className="mono text-accent-2 hover:underline" to={`/transactions/${t.txid}`}>{shortHash(t.txid)}</Link></Td><Td className="mono text-xs">{formatDate(t.first_seen_at)}</Td><Td><RiskScore score={t.risk_score} band={t.risk_band} entityType="transaction" entityKey={t.txid} /></Td></tr>)}
                        </tbody></Table>
                      )}
                    </Card>
                    <Card>
                      <CardHeader title={`Addresses (${b.addresses.length})`} />
                      {b.addresses.length === 0 ? <Empty title="None linked" /> : (
                        <ul className="divide-y divide-line text-sm">{b.addresses.map((a) => <li key={a.address} className="flex justify-between px-4 py-2"><Link className="mono text-accent-2 hover:underline" to={`/addresses/${encodeURIComponent(a.address)}`}>{shortHash(a.address, 14)}</Link><RiskScore score={a.risk_score} entityType="address" entityKey={a.address} /></li>)}</ul>
                      )}
                    </Card>
                    <Card>
                      <CardHeader title={`Alerts (${b.alerts.length})`} />
                      {b.alerts.length === 0 ? <Empty title="None linked" /> : (
                        <ul className="divide-y divide-line text-sm">{b.alerts.map((a) => <li key={a.id}><Link to={`/alerts/${a.id}`} className="flex items-center gap-2 px-4 py-2 hover:bg-bg-2"><BandBadge band={a.severity} />{titleCase(a.category)}<span className="ml-auto"><AlertStatusBadge status={a.status} /></span></Link></li>)}</ul>
                      )}
                    </Card>
                  </div>
                  <div className="space-y-4">
                    <Card>
                      <CardHeader title="Case management" />
                      <CardBody className="space-y-3">
                        {c.summary && <p className="text-sm">{c.summary}</p>}
                        <Field label="Status">
                          <Select value={c.status} disabled={!can('case.create') || update.isPending} onChange={(e) => update.mutate({ status: e.target.value, ...(decision ? { analyst_decision: decision } : {}) })}>
                            {['open', 'in_progress', 'on_hold', 'closed'].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}
                          </Select>
                        </Field>
                        {can('case.assign') && (
                          <Field label="Assigned to">
                            <Select defaultValue="" onChange={(e) => e.target.value && update.mutate({ assigned_to: e.target.value })}>
                              <option value="">{c.assigned_to ?? 'Unassigned'}</option>
                              {users.data?.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
                            </Select>
                          </Field>
                        )}
                        <Field label="Analyst decision" hint="Required before closing. Record reasoning, not conclusions of guilt.">
                          <Textarea defaultValue={c.analyst_decision ?? ''} onChange={(e) => setDecision(e.target.value)} disabled={!can('case.create')} />
                        </Field>
                        {can('case.create') && <Button size="sm" disabled={!decision.trim() || update.isPending} onClick={() => update.mutate({ analyst_decision: decision })}>Save decision</Button>}
                      </CardBody>
                    </Card>
                  </div>
                </div>
              )}
              {tab === 'evidence' && (
                <div className="space-y-4">
                  {can('evidence.attach') && !closed && (
                    <Card className="p-4">
                      <form className="grid gap-3 md:grid-cols-[160px_1fr_1fr_auto] md:items-end" onSubmit={(e) => { e.preventDefault(); addEv.mutate() }}>
                        <Field label="Type"><Select value={ev.evidence_type} onChange={(e) => setEv({ ...ev, evidence_type: e.target.value })}>{['transaction', 'address', 'observation', 'alert', 'raw_record'].map((t) => <option key={t}>{t}</option>)}</Select></Field>
                        <Field label="Reference"><Input required value={ev.reference} onChange={(e) => setEv({ ...ev, reference: e.target.value.trim() })} placeholder="txid / address / id" /></Field>
                        <Field label="Description"><Input required minLength={3} value={ev.description} onChange={(e) => setEv({ ...ev, description: e.target.value })} /></Field>
                        <Button type="submit" variant="primary" disabled={addEv.isPending}>Attach</Button>
                      </form>
                    </Card>
                  )}
                  <Card>
                    <CardHeader title="Evidence register" subtitle="Append-only. Integrity hash covers snapshot, provenance and analysis versions." />
                    {b.evidence.length === 0 ? <Empty title="No evidence attached" /> : (
                      <Table><thead><tr><Th>#</Th><Th>Type</Th><Th>Reference</Th><Th>Description</Th><Th>Integrity</Th><Th>Verify</Th></tr></thead><tbody>
                        {b.evidence.map((e) => (
                          <tr key={e.id}>
                            <Td className="mono">{e.id}</Td><Td><Badge>{e.type}</Badge></Td><Td className="mono text-xs">{shortHash(e.reference, 10)}</Td><Td className="text-xs">{e.description}</Td>
                            <Td className="mono text-xs" title={e.integrity_hash}>{shortHash(e.integrity_hash, 8)}</Td>
                            <Td>
                              {verify[e.id] ? <Badge tone={verify[e.id].verified ? 'ok' : 'crit'}>{verify[e.id].verified ? 'verified' : 'FAILED'}</Badge> : (
                                <Button size="sm" onClick={async () => { const r = await get<{ verified: boolean }>(`/investigations/${id}/evidence/${e.id}/verify`); setVerify((v) => ({ ...v, [e.id]: r })) }}>Verify</Button>
                              )}
                            </Td>
                          </tr>
                        ))}
                      </tbody></Table>
                    )}
                  </Card>
                </div>
              )}
              {tab === 'notes' && (
                <Card>
                  {can('case.create') && (
                    <CardBody className="space-y-2 border-b border-line">
                      <Textarea aria-label="New note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Add an investigation note…" />
                      <Button size="sm" variant="primary" disabled={!note.trim() || addNote.isPending} onClick={() => addNote.mutate()}>Add note</Button>
                    </CardBody>
                  )}
                  {b.notes.length === 0 ? <Empty title="No notes" /> : (
                    <ul className="divide-y divide-line text-sm">{b.notes.map((n, i) => <li key={i} className="px-4 py-3"><div className="text-xs text-muted">{n.author} · {formatDate(n.at)}</div><p className="mt-1 whitespace-pre-wrap">{n.body}</p></li>)}</ul>
                  )}
                </Card>
              )}
              {tab === 'timeline' && (
                <Card>
                  <CardHeader title="Case timeline" subtitle="From the hash-chained audit log" />
                  <ol className="divide-y divide-line text-sm">{b.timeline.map((t) => (
                    <li key={t.seq} className="flex gap-3 px-4 py-2"><span className="mono w-44 shrink-0 text-xs text-muted">{formatDate(t.at)}</span><span className="mono text-accent-2">{t.action}</span><span className="text-muted">{t.actor ?? 'system'}</span><span className="mono ml-auto text-xs text-muted" title={t.entry_hash}>{shortHash(t.entry_hash, 6)}</span></li>
                  ))}</ol>
                </Card>
              )}
              {tab === 'reports' && (
                <Card>
                  <DataState query={reports} isEmpty={(r) => r.items.length === 0} empty={<Empty title="No reports exported yet" />}>
                    {(r) => (
                      <Table><thead><tr><Th>Generated</Th><Th>Format</Th><Th>SHA-256</Th><Th>Size</Th><Th /></tr></thead><tbody>
                        {r.items.map((x) => <tr key={x.id}><Td className="mono text-xs">{formatDate(x.generated_at)}</Td><Td><Badge>{x.format}</Badge></Td><Td className="mono text-xs">{shortHash(x.sha256, 10)}</Td><Td className="num">{(x.size_bytes / 1024).toFixed(1)} KB</Td><Td><Button size="sm" onClick={() => void download(`/reports/${x.id}/download`, `report.${x.format}`)}>Download</Button></Td></tr>)}
                      </tbody></Table>
                    )}
                  </DataState>
                </Card>
              )}
            </div>
            <p className="mt-4 text-xs text-muted">{b.disclaimer}</p>
          </>
        )
      }}
    </DataState>
  )
}
