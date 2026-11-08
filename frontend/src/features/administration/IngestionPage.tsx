import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { DataLabel } from '@/components/badges'
import { DataState, Empty } from '@/components/states'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Select, Table, Td, Th } from '@/components/ui/primitives'
import { PageHeader } from '@/layouts/AppLayout'
import { api, get, post, problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { Dataset, Job, Paginated } from '@/types/api'
import { formatDate, formatNumber, titleCase } from '@/utils/format'

export default function IngestionPage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const [prov, setProv] = useState('synthetic')
  const [jobFilter, setJobFilter] = useState<string | null>(null)
  const ds = useQuery({ queryKey: ['datasets'], queryFn: () => get<Paginated<Dataset>>('/ingestion/datasets', { limit: 100 }) })
  const jobs = useQuery({ queryKey: ['jobs'], queryFn: () => get<Paginated<Job>>('/ingestion/jobs', { limit: 50 }), refetchInterval: (q) => (q.state.data?.items.some((j) => j.status === 'running' || j.status === 'pending') ? 3000 : false) })
  const errors = useQuery({ queryKey: ['ing-errors', jobFilter], enabled: !!jobFilter, queryFn: () => get<Paginated<{ id: number; record_index: number | null; field: string | null; error_code: string; message: string; severity: string }>>('/ingestion/errors', { job_id: jobFilter, limit: 200 }) })
  const upload = useMutation({
    mutationFn: async () => {
      const files = fileRef.current?.files
      if (!files?.length) throw new Error('Choose at least one file')
      const fd = new FormData()
      fd.append('name', name || files[0].name)
      fd.append('provenance', prov)
      Array.from(files).forEach((f) => fd.append('files', f))
      const d = (await api.post<Dataset>('/ingestion/datasets', fd)).data
      if (can('dataset.process')) await post(`/ingestion/datasets/${d.id}/process`)
      return d
    },
    onSuccess: () => { setName(''); if (fileRef.current) fileRef.current.value = ''; void qc.invalidateQueries() },
  })
  const process = useMutation({ mutationFn: (id: string) => post(`/ingestion/datasets/${id}/process`), onSuccess: () => void qc.invalidateQueries() })

  return (
    <>
      <PageHeader title="Data ingestion" subtitle="Offline bulk files only (CSV, JSON, JSON Lines, XML). Files are checksummed; every record is staged immutably; invalid records are quarantined with reasons." />
      {can('dataset.upload') && (
        <Card className="mb-4">
          <CardHeader title="Upload dataset" />
          <CardBody>
            <form className="grid gap-3 md:grid-cols-[1fr_160px_1fr_auto] md:items-end" onSubmit={(e) => { e.preventDefault(); upload.mutate() }}>
              <Field label="Dataset name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="defaults to file name" /></Field>
              <Field label="Provenance"><Select value={prov} onChange={(e) => setProv(e.target.value)}><option value="synthetic">Synthetic</option><option value="historical">Historical</option><option value="external">External</option></Select></Field>
              <Field label="Files"><input ref={fileRef} type="file" multiple accept=".csv,.json,.jsonl,.ndjson,.xml" className="text-sm" aria-label="Dataset files" /></Field>
              <Button type="submit" variant="primary" disabled={upload.isPending}>{upload.isPending ? 'Uploading & processing…' : can('dataset.process') ? 'Upload & process' : 'Upload'}</Button>
            </form>
            {upload.isError && <p role="alert" className="mt-2 text-xs text-crit">{problemMessage(upload.error)}</p>}
            {upload.isSuccess && <p className="mt-2 text-xs text-ok">Dataset registered.</p>}
          </CardBody>
        </Card>
      )}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Datasets" />
          <DataState query={ds} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No datasets yet" />}>
            {(d) => (
              <Table><thead><tr><Th>Name</Th><Th>Label</Th><Th>Status</Th><Th>Created</Th><Th /></tr></thead><tbody>
                {d.items.map((x) => <tr key={x.id}><Td>{x.name}</Td><Td><DataLabel label={x.provenance} /></Td><Td><Badge>{x.status}</Badge></Td><Td className="mono text-xs">{formatDate(x.created_at)}</Td>
                  <Td>{can('dataset.process') && x.status !== 'processed' && <Button size="sm" onClick={() => process.mutate(x.id)} disabled={process.isPending}>Process / resume</Button>}</Td></tr>)}
              </tbody></Table>
            )}
          </DataState>
        </Card>
        <Card>
          <CardHeader title="Ingestion jobs" subtitle="Resumable from the last committed checkpoint" />
          <DataState query={jobs} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No jobs yet" />}>
            {(d) => (
              <Table><thead><tr><Th>Status</Th><Th>Processed</Th><Th>Valid</Th><Th>Partial</Th><Th>Quarantined</Th><Th>Duplicates</Th><Th /></tr></thead><tbody>
                {d.items.map((j) => (
                  <tr key={j.id}>
                    <Td><Badge tone={j.status === 'failed' ? 'crit' : j.status.startsWith('completed') ? 'ok' : 'info'}>{titleCase(j.status)}</Badge>{j.error_message && <div className="mt-1 text-xs text-crit">{j.error_message}</div>}</Td>
                    <Td className="num">{formatNumber(j.processed_records)}{j.total_records ? ` / ${formatNumber(j.total_records)}` : ''}</Td>
                    <Td className="num">{formatNumber(j.valid_records)}</Td><Td className="num">{formatNumber(j.partial_records)}</Td>
                    <Td className="num">{formatNumber(j.quarantined_records)}</Td><Td className="num">{formatNumber(j.duplicate_records)}</Td>
                    <Td><Button size="sm" variant="ghost" onClick={() => setJobFilter(j.id)}>Errors</Button></Td>
                  </tr>
                ))}
              </tbody></Table>
            )}
          </DataState>
        </Card>
      </div>
      {jobFilter && (
        <Card className="mt-4">
          <CardHeader title="Record-level errors & warnings" actions={<Button size="sm" variant="ghost" onClick={() => setJobFilter(null)}>Close</Button>} />
          <DataState query={errors} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No errors for this job" />}>
            {(d) => (
              <Table><thead><tr><Th>Record</Th><Th>Severity</Th><Th>Code</Th><Th>Field</Th><Th>Message</Th></tr></thead><tbody>
                {d.items.map((e) => <tr key={e.id}><Td className="mono">{e.record_index ?? '—'}</Td><Td><Badge tone={e.severity === 'error' ? 'crit' : 'warn'}>{e.severity}</Badge></Td><Td className="mono text-xs">{e.error_code}</Td><Td className="mono text-xs">{e.field ?? '—'}</Td><Td className="text-xs">{e.message}</Td></tr>)}
              </tbody></Table>
            )}
          </DataState>
        </Card>
      )}
    </>
  )
}
