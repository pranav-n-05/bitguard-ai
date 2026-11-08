import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderPlus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Field, Input, Modal, Select, Textarea } from '@/components/ui/primitives'
import { get, post, problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { CaseRow, Paginated } from '@/types/api'

interface Props {
  txids?: string[]
  addresses?: string[]
  alertIds?: string[]
  evidence?: { evidence_type: string; reference: string }
}

/** Link an entity to a new or existing investigation, optionally recording it as evidence. */
export function AddToCase({ txids = [], addresses = [], alertIds = [], evidence }: Props) {
  const { can } = useAuth()
  const nav = useNavigate()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [caseId, setCaseId] = useState('new')
  const [title, setTitle] = useState('')
  const [desc, setDesc] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const cases = useQuery({ queryKey: ['cases', 'open-mini'], enabled: open, queryFn: () => get<Paginated<CaseRow>>('/investigations', { status: ['open', 'in_progress', 'on_hold'], limit: 100 }) })

  const m = useMutation({
    mutationFn: async () => {
      let id = caseId
      if (id === 'new') {
        const c = await post<CaseRow>('/investigations', { title, txids, addresses, alert_ids: alertIds })
        id = c.id
      } else {
        await post(`/investigations/${id}/entities`, { txids, addresses, alert_ids: alertIds })
      }
      if (evidence && can('evidence.attach') && desc.trim()) await post(`/investigations/${id}/evidence`, { ...evidence, description: desc })
      return id
    },
    onSuccess: (id) => {
      void qc.invalidateQueries({ queryKey: ['cases'] })
      setOpen(false)
      nav(`/investigations/${id}`)
    },
    onError: (e) => setErr(problemMessage(e)),
  })

  if (!can('case.create')) return null
  return (
    <>
      <Button size="sm" onClick={() => setOpen(true)}><FolderPlus size={14} /> Add to case</Button>
      <Modal open={open} onOpenChange={setOpen} title="Add to investigation">
        <form className="mt-3 space-y-3" onSubmit={(e) => { e.preventDefault(); setErr(null); m.mutate() }}>
          <Field label="Investigation">
            <Select value={caseId} onChange={(e) => setCaseId(e.target.value)}>
              <option value="new">New investigation…</option>
              {cases.data?.items.map((c) => <option key={c.id} value={c.id}>{c.case_number} — {c.title}</option>)}
            </Select>
          </Field>
          {caseId === 'new' && <Field label="Title"><Input required minLength={3} value={title} onChange={(e) => setTitle(e.target.value)} /></Field>}
          {evidence && can('evidence.attach') && (
            <Field label="Evidence note (optional)" hint="If provided, the entity is recorded as evidence with provenance and integrity hash.">
              <Textarea value={desc} onChange={(e) => setDesc(e.target.value)} />
            </Field>
          )}
          {err && <p role="alert" className="text-xs text-crit">{err}</p>}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={m.isPending || (caseId === 'new' && title.trim().length < 3)}>{m.isPending ? 'Saving…' : 'Save'}</Button>
          </div>
        </form>
      </Modal>
    </>
  )
}
