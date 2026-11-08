import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { RiskScore } from '@/components/badges'
import { Pagination, SortTh } from '@/components/Pagination'
import { DataState, Empty } from '@/components/states'
import { Button, Card, CopyText, Field, Input, KV, Select, Sheet, Table, Td, Th } from '@/components/ui/primitives'
import { useSearchState } from '@/hooks/useSearchState'
import { PageHeader } from '@/layouts/AppLayout'
import { get } from '@/services/api'
import type { Paginated, Tx, TxDetail } from '@/types/api'
import { formatDate, formatSat, satToBtc, shortHash } from '@/utils/format'

const LIMIT = 50

export default function TransactionsPage() {
  const { get: g, set } = useSearchState()
  const [drawer, setDrawer] = useState<string | null>(null)
  const params = {
    q: g('q') ?? undefined, start: g('start') ?? undefined, end: g('end') ?? undefined, band: g('band') ?? undefined,
    min_value_sat: g('min_value_sat') ?? undefined, min_outputs: g('min_outputs') ?? undefined,
    sort: g('sort') ?? '-first_seen_at', limit: LIMIT, offset: Number(g('offset') ?? 0),
  }
  const q = useQuery({ queryKey: ['transactions', params], queryFn: () => get<Paginated<Tx>>('/transactions', params), placeholderData: (p) => p })

  return (
    <>
      <PageHeader title="Transactions" subtitle="Canonical transactions from ingested bulk data. Amounts in satoshis (integer)." />
      <Card className="mb-4 p-3">
        <form
          className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6"
          onSubmit={(e) => {
            e.preventDefault()
            const f = new FormData(e.currentTarget)
            set(Object.fromEntries(['q', 'start', 'end', 'band', 'min_value_sat', 'min_outputs'].map((k) => [k, (f.get(k) as string) || null])))
          }}
        >
          <Field label="txid prefix or address"><Input name="q" defaultValue={params.q} placeholder="e.g. 3fa1… or bc1q…" /></Field>
          <Field label="From (UTC)"><Input name="start" type="datetime-local" defaultValue={params.start?.slice(0, 16)} /></Field>
          <Field label="To (UTC)"><Input name="end" type="datetime-local" defaultValue={params.end?.slice(0, 16)} /></Field>
          <Field label="Risk band">
            <Select name="band" defaultValue={params.band ?? ''}>
              <option value="">Any</option><option value="low">Low</option><option value="moderate">Moderate</option><option value="elevated">Elevated</option><option value="high">High</option>
            </Select>
          </Field>
          <Field label="Min value (sat)"><Input name="min_value_sat" inputMode="numeric" pattern="\d*" defaultValue={params.min_value_sat} /></Field>
          <div className="flex items-end gap-2">
            <Field label="Min outputs"><Input name="min_outputs" inputMode="numeric" pattern="\d*" defaultValue={params.min_outputs} /></Field>
            <Button type="submit" variant="primary">Apply</Button>
          </div>
        </form>
      </Card>
      <Card>
        <DataState query={q} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No transactions match these filters" />}>
          {(d) => (
            <>
              <Table>
                <thead>
                  <tr>
                    <Th>txid</Th>
                    <SortTh label="First seen" field="first_seen_at" sort={params.sort} onSort={(s) => set({ sort: s })} />
                    <SortTh label="Value" field="total_output_sat" sort={params.sort} onSort={(s) => set({ sort: s })} className="text-right" />
                    <SortTh label="Fee" field="fee_sat" sort={params.sort} onSort={(s) => set({ sort: s })} />
                    <SortTh label="In" field="input_count" sort={params.sort} onSort={(s) => set({ sort: s })} />
                    <SortTh label="Out" field="output_count" sort={params.sort} onSort={(s) => set({ sort: s })} />
                    <Th>Risk</Th>
                    <Th>Alerts</Th>
                  </tr>
                </thead>
                <tbody>
                  {d.items.map((t) => (
                    <tr key={t.txid} className="cursor-pointer hover:bg-bg-2" onClick={() => setDrawer(t.txid)}>
                      <Td><button className="mono text-accent-2 hover:underline" onClick={(e) => { e.stopPropagation(); setDrawer(t.txid) }}>{shortHash(t.txid)}</button></Td>
                      <Td className="mono text-xs">{formatDate(t.first_seen_at)}</Td>
                      <Td className="mono text-right">{satToBtc(t.total_output_sat)}</Td>
                      <Td className="mono">{formatSat(t.fee_sat)}</Td>
                      <Td className="num">{t.input_count}</Td>
                      <Td className="num">{t.output_count}</Td>
                      <Td onClick={(e) => e.stopPropagation()}><RiskScore score={t.risk?.score} band={t.risk?.band} entityType="transaction" entityKey={t.txid} /></Td>
                      <Td className="num">{t.alert_count || ''}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <Pagination total={d.total} limit={LIMIT} offset={params.offset} onChange={(o) => set({ offset: o }, false)} />
            </>
          )}
        </DataState>
      </Card>
      <TxDrawer txid={drawer} onClose={() => setDrawer(null)} />
    </>
  )
}

function TxDrawer({ txid, onClose }: { txid: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ['tx', txid], queryFn: () => get<TxDetail>(`/transactions/${txid}`), enabled: !!txid })
  return (
    <Sheet open={!!txid} onOpenChange={(o) => !o && onClose()} title="Transaction">
      <DataState query={q}>
        {(t) => (
          <div className="space-y-4">
            <CopyText value={t.txid} />
            <KV items={[
              ['First seen', formatDate(t.first_seen_at)], ['Block height', t.block_height ?? '—'],
              ['Total in', satToBtc(t.total_input_sat)], ['Total out', satToBtc(t.total_output_sat)],
              ['Fee', formatSat(t.fee_sat)], ['Data quality', t.data_quality],
              ['Risk', <RiskScore key="r" score={t.risk?.score} band={t.risk?.band} entityType="transaction" entityKey={t.txid} />],
              ['Source', `${t.provenance.dataset_name} (${t.provenance.provenance})`],
            ]} />
            <div className="grid gap-3 sm:grid-cols-2">
              <IoList title={`Inputs (${t.inputs.length})`} rows={t.inputs} />
              <IoList title={`Outputs (${t.outputs.length})`} rows={t.outputs} />
            </div>
            {t.graph_detections.length > 0 && (
              <div className="text-sm"><span className="text-muted">Structural detections: </span>{t.graph_detections.map((d) => d.pattern).join(', ')}</div>
            )}
            <Button asChild variant="primary"><Link to={`/transactions/${t.txid}`}>Open full investigation view</Link></Button>
          </div>
        )}
      </DataState>
    </Sheet>
  )
}

export function IoList({ title, rows }: { title: string; rows: { position: number; address: string; amount_sat: number; script_type: string | null }[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-muted">{title}</div>
      <ul className="max-h-72 divide-y divide-line overflow-y-auto rounded border border-line">
        {rows.map((r) => (
          <li key={r.position} className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs">
            <Link to={`/addresses/${encodeURIComponent(r.address)}`} className="mono truncate text-accent-2 hover:underline" title={r.address}>{shortHash(r.address, 12)}</Link>
            <span className="mono shrink-0">{satToBtc(r.amount_sat)}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
