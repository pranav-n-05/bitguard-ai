import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Pagination } from '@/components/Pagination'
import { DataState, Empty } from '@/components/states'
import { Badge, Button, Card, CardBody, CardHeader, Field, Select, Table, Td, Th } from '@/components/ui/primitives'
import { PageHeader } from '@/layouts/AppLayout'
import { download, get, post, problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { Paginated, Report } from '@/types/api'
import { formatDate, shortHash, titleCase } from '@/utils/format'

const FORMATS: Record<string, string[]> = { alerts: ['pdf', 'csv', 'json'], transactions: ['csv', 'json'] }

export default function ReportsPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [rt, setRt] = useState('alerts')
  const [fmt, setFmt] = useState('pdf')
  const [offset, setOffset] = useState(0)
  const q = useQuery({ queryKey: ['reports', 'all', offset], queryFn: () => get<Paginated<Report>>('/reports', { limit: 25, offset }) })
  const gen = useMutation({
    mutationFn: async () => { const r = await post<Report>('/reports/generate', { report_type: rt, format: fmt, parameters: {} }); await download(`/reports/${r.id}/download`, `${rt}.${fmt}`); return r },
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['reports'] }),
  })
  return (
    <>
      <PageHeader title="Reports" subtitle="Generated reports are stored with SHA-256 and verified on every download. Investigation summaries are exported from each case." />
      {can('report.generate') && (
        <Card className="mb-4">
          <CardHeader title="Generate register report" />
          <CardBody className="flex flex-wrap items-end gap-3">
            <Field label="Report"><Select value={rt} onChange={(e) => { setRt(e.target.value); setFmt(FORMATS[e.target.value][0]) }} className="w-48"><option value="alerts">Alert register</option><option value="transactions">Transactions</option></Select></Field>
            <Field label="Format"><Select value={fmt} onChange={(e) => setFmt(e.target.value)} className="w-28">{FORMATS[rt].map((f) => <option key={f}>{f}</option>)}</Select></Field>
            <Button variant="primary" onClick={() => gen.mutate()} disabled={gen.isPending}>{gen.isPending ? 'Generating…' : 'Generate & download'}</Button>
            {gen.isError && <span className="text-xs text-crit">{problemMessage(gen.error)}</span>}
          </CardBody>
        </Card>
      )}
      <Card>
        <DataState query={q} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No reports yet" />}>
          {(d) => (
            <>
              <Table><thead><tr><Th>Generated</Th><Th>Type</Th><Th>Format</Th><Th>Case</Th><Th>SHA-256</Th><Th /></tr></thead><tbody>
                {d.items.map((r) => (
                  <tr key={r.id}>
                    <Td className="mono text-xs">{formatDate(r.generated_at)}</Td><Td>{titleCase(r.report_type)}</Td><Td><Badge>{r.format}</Badge></Td>
                    <Td>{r.investigation_id ? <Link className="text-accent-2 hover:underline" to={`/investigations/${r.investigation_id}`}>open</Link> : '—'}</Td>
                    <Td className="mono text-xs" title={r.sha256}>{shortHash(r.sha256, 10)}</Td>
                    <Td>{can('report.generate') && <Button size="sm" onClick={() => void download(`/reports/${r.id}/download`, `report.${r.format}`)}>Download</Button>}</Td>
                  </tr>
                ))}
              </tbody></Table>
              <Pagination total={d.total} limit={25} offset={offset} onChange={setOffset} />
            </>
          )}
        </DataState>
      </Card>
    </>
  )
}
