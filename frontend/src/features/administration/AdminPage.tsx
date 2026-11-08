import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Pagination } from '@/components/Pagination'
import { DataState, Empty } from '@/components/states'
import { Badge, Button, Card, CardBody, CardHeader, Field, Input, Modal, Select, Table, Tabs, Td, Th } from '@/components/ui/primitives'
import { PageHeader } from '@/layouts/AppLayout'
import { get, patch, post, problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { Paginated, User } from '@/types/api'
import { formatDate, shortHash, titleCase } from '@/utils/format'

type Tab = 'users' | 'roles' | 'config' | 'audit' | 'security'

export default function AdminPage() {
  const { can } = useAuth()
  const tabs = ([
    can('user.admin') && { id: 'users', label: 'Users' }, can('user.admin') && { id: 'roles', label: 'Roles & permissions' },
    can('config.change') && { id: 'config', label: 'Thresholds & models' }, can('audit.read') && { id: 'audit', label: 'Audit log' },
    { id: 'security', label: 'My security' },
  ].filter(Boolean) as { id: Tab; label: string }[])
  const [tab, setTab] = useState<Tab>(tabs[0]?.id ?? 'security')
  return (
    <>
      <PageHeader title="Administration" />
      <Tabs<Tab> value={tab} onChange={setTab} tabs={tabs} />
      <div className="mt-4">
        {tab === 'users' && <Users />}
        {tab === 'roles' && <Roles />}
        {tab === 'config' && <Config />}
        {tab === 'audit' && <Audit />}
        {tab === 'security' && <MySecurity />}
      </div>
    </>
  )
}

const newUserSchema = z.object({
  email: z.string().regex(/^[^@\s]+@[^@\s]+$/, 'Valid email required'),
  full_name: z.string().min(1, 'Required'),
  password: z.string().min(12, 'At least 12 characters'),
  role: z.enum(['viewer', 'analyst', 'senior_analyst', 'administrator']),
})

function Users() {
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)
  const [offset, setOffset] = useState(0)
  const q = useQuery({ queryKey: ['users', offset], queryFn: () => get<Paginated<User>>('/admin/users', { limit: 50, offset }) })
  const form = useForm<z.infer<typeof newUserSchema>>({ resolver: zodResolver(newUserSchema), defaultValues: { email: '', full_name: '', password: '', role: 'analyst' } })
  const create = useMutation({ mutationFn: (v: z.infer<typeof newUserSchema>) => post('/admin/users', { ...v, roles: [v.role] }), onSuccess: () => { setOpen(false); form.reset(); void qc.invalidateQueries({ queryKey: ['users'] }) } })
  const upd = useMutation({ mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => patch(`/admin/users/${id}`, body), onSuccess: () => void qc.invalidateQueries({ queryKey: ['users'] }) })
  return (
    <Card>
      <CardHeader title="Users" actions={<Button variant="primary" size="sm" onClick={() => setOpen(true)}>Add user</Button>} />
      {upd.isError && <p className="px-4 pt-2 text-xs text-crit">{problemMessage(upd.error)}</p>}
      <DataState query={q} isEmpty={(d) => d.items.length === 0}>
        {(d) => (
          <>
            <Table><thead><tr><Th>Name</Th><Th>Email</Th><Th>Role</Th><Th>MFA</Th><Th>Last login</Th><Th>Status</Th></tr></thead><tbody>
              {d.items.map((u) => (
                <tr key={u.id}>
                  <Td>{u.full_name}</Td><Td className="mono text-xs">{u.email}</Td>
                  <Td><Select aria-label={`Role for ${u.email}`} value={u.role_names[0]} onChange={(e) => upd.mutate({ id: u.id, body: { roles: [e.target.value] } })} className="h-7 w-40 text-xs">
                    {['viewer', 'analyst', 'senior_analyst', 'administrator'].map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
                  </Select></Td>
                  <Td>{u.mfa_enabled ? <Badge tone="ok">on</Badge> : <Badge>off</Badge>}</Td>
                  <Td className="mono text-xs">{formatDate(u.last_login_at)}</Td>
                  <Td><Button size="sm" variant={u.is_active ? 'ghost' : 'secondary'} onClick={() => upd.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? 'Deactivate' : 'Activate'}</Button></Td>
                </tr>
              ))}
            </tbody></Table>
            <Pagination total={d.total} limit={50} offset={offset} onChange={setOffset} />
          </>
        )}
      </DataState>
      <Modal open={open} onOpenChange={setOpen} title="Add user">
        <form className="mt-3 space-y-3" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <Field label="Email" error={form.formState.errors.email?.message}><Input {...form.register('email')} /></Field>
          <Field label="Full name" error={form.formState.errors.full_name?.message}><Input {...form.register('full_name')} /></Field>
          <Field label="Initial password" hint="≥12 chars, three of lower/upper/digit/symbol" error={form.formState.errors.password?.message}><Input type="password" autoComplete="new-password" {...form.register('password')} /></Field>
          <Field label="Role"><Select {...form.register('role')}>{['viewer', 'analyst', 'senior_analyst', 'administrator'].map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}</Select></Field>
          {create.isError && <p role="alert" className="text-xs text-crit">{problemMessage(create.error)}</p>}
          <div className="flex justify-end gap-2"><Button type="button" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" variant="primary" disabled={create.isPending}>Create</Button></div>
        </form>
      </Modal>
    </Card>
  )
}

function Roles() {
  const q = useQuery({ queryKey: ['roles'], queryFn: () => get<{ name: string; description: string; permissions: string[] }[]>('/admin/roles') })
  return (
    <DataState query={q}>
      {(roles) => (
        <div className="grid gap-4 md:grid-cols-2">
          {roles.map((r) => (
            <Card key={r.name}><CardHeader title={titleCase(r.name)} subtitle={r.description} />
              <CardBody className="flex flex-wrap gap-1.5">{r.permissions.map((p) => <Badge key={p} tone="info">{p}</Badge>)}</CardBody></Card>
          ))}
        </div>
      )}
    </DataState>
  )
}

interface ConfigData { risk_weights: Record<string, number>; risk_weights_version: number; alert_rules: { code: string; category: string; description: string; enabled: boolean; thresholds: Record<string, number>; version: number }[] }

function Config() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['config'], queryFn: () => get<ConfigData>('/admin/configuration') })
  const [weights, setWeights] = useState<Record<string, number> | null>(null)
  const save = useMutation({ mutationFn: (body: unknown) => patch<ConfigData>('/admin/configuration', body), onSuccess: () => { setWeights(null); void qc.invalidateQueries({ queryKey: ['config'] }) } })
  const rerun = useMutation({ mutationFn: () => post<Record<string, unknown>>('/admin/pipeline/rerun', undefined) })
  return (
    <DataState query={q}>
      {(c) => {
        const w = weights ?? c.risk_weights
        return (
          <div className="space-y-4">
            {save.isError && <p className="text-sm text-crit">{problemMessage(save.error)}</p>}
            <Card>
              <CardHeader title={`Risk weights (v${c.risk_weights_version})`} subtitle="Weights are normalised over available components. Changes apply on the next recalculation."
                actions={<><Button size="sm" disabled={!weights || save.isPending} onClick={() => save.mutate({ risk_weights: weights })}>Save weights</Button>
                  <Button size="sm" variant="primary" disabled={rerun.isPending} onClick={() => rerun.mutate()}>{rerun.isPending ? 'Recomputing…' : 'Recompute pipeline'}</Button></>} />
              <CardBody className="grid gap-3 sm:grid-cols-3">
                {Object.entries(w).map(([k, v]) => (
                  <Field key={k} label={titleCase(k)}><Input type="number" min={0} max={1} step={0.05} value={v} onChange={(e) => setWeights({ ...w, [k]: Number(e.target.value) })} /></Field>
                ))}
              </CardBody>
              {rerun.isSuccess && <CardBody className="mono text-xs text-muted">{JSON.stringify(rerun.data)}</CardBody>}
              {rerun.isError && <CardBody className="text-xs text-crit">{problemMessage(rerun.error)}</CardBody>}
            </Card>
            <Card>
              <CardHeader title="Alert rules" subtitle="Thresholds are versioned; every change is audited." />
              <Table><thead><tr><Th>Rule</Th><Th>Category</Th><Th>Thresholds</Th><Th>Version</Th><Th>Enabled</Th></tr></thead><tbody>
                {c.alert_rules.map((r) => (
                  <tr key={r.code}>
                    <Td><div className="mono text-xs">{r.code}</div><div className="text-xs text-muted">{r.description}</div></Td>
                    <Td className="text-xs">{titleCase(r.category)}</Td>
                    <Td className="space-y-1">{Object.entries(r.thresholds).map(([k, v]) => (
                      <label key={k} className="flex items-center gap-2 text-xs"><span className="mono w-40 text-muted">{k}</span>
                        <Input type="number" step="any" defaultValue={v} className="h-7 w-28" onBlur={(e) => { const n = Number(e.target.value); if (n !== v) save.mutate({ alert_rules: [{ code: r.code, thresholds: { [k]: n } }] }) }} /></label>
                    ))}</Td>
                    <Td className="mono">{r.version}</Td>
                    <Td><input type="checkbox" aria-label={`Enable ${r.code}`} checked={r.enabled} onChange={(e) => save.mutate({ alert_rules: [{ code: r.code, enabled: e.target.checked }] })} /></Td>
                  </tr>
                ))}
              </tbody></Table>
            </Card>
          </div>
        )
      }}
    </DataState>
  )
}

function Audit() {
  const [offset, setOffset] = useState(0)
  const [action, setAction] = useState('')
  const q = useQuery({ queryKey: ['audit', offset, action], queryFn: () => get<Paginated<{ seq: number; occurred_at: string; actor_email: string | null; action: string; entity_type: string; entity_id: string | null; details: Record<string, unknown>; entry_hash: string }>>('/admin/audit-logs', { limit: 50, offset, action: action || undefined }) })
  const verify = useMutation({ mutationFn: () => get<{ valid: boolean; entries_checked: number; first_invalid_seq: number | null }>('/admin/audit-logs/verify') })
  return (
    <Card>
      <CardHeader title="Audit log" subtitle="Append-only (database-enforced) and SHA-256 hash-chained"
        actions={<><Input aria-label="Filter by action prefix" placeholder="action prefix e.g. alert." value={action} onChange={(e) => { setAction(e.target.value); setOffset(0) }} className="h-8 w-56" />
          <Button size="sm" onClick={() => verify.mutate()} disabled={verify.isPending}>Verify chain</Button>
          {verify.data && <Badge tone={verify.data.valid ? 'ok' : 'crit'}>{verify.data.valid ? `valid · ${verify.data.entries_checked} entries` : `BROKEN at seq ${verify.data.first_invalid_seq}`}</Badge>}</>} />
      <DataState query={q} isEmpty={(d) => d.items.length === 0} empty={<Empty title="No audit entries" />}>
        {(d) => (
          <>
            <Table><thead><tr><Th>Seq</Th><Th>When</Th><Th>Actor</Th><Th>Action</Th><Th>Entity</Th><Th>Hash</Th></tr></thead><tbody>
              {d.items.map((a) => (
                <tr key={a.seq} title={JSON.stringify(a.details)}>
                  <Td className="mono">{a.seq}</Td><Td className="mono text-xs">{formatDate(a.occurred_at)}</Td><Td className="text-xs">{a.actor_email ?? 'system'}</Td>
                  <Td className="mono text-xs text-accent-2">{a.action}</Td><Td className="mono text-xs">{a.entity_type}:{shortHash(a.entity_id, 6)}</Td><Td className="mono text-xs">{shortHash(a.entry_hash, 6)}</Td>
                </tr>
              ))}
            </tbody></Table>
            <Pagination total={d.total} limit={50} offset={offset} onChange={setOffset} />
          </>
        )}
      </DataState>
    </Card>
  )
}

function MySecurity() {
  const { user, reload } = useAuth()
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null)
  const [otp, setOtp] = useState('')
  const [pw, setPw] = useState({ current_password: '', new_password: '' })
  const begin = useMutation({ mutationFn: () => post<{ secret: string; otpauth_uri: string }>('/auth/mfa/setup'), onSuccess: setSetup })
  const enable = useMutation({ mutationFn: () => post(user?.mfa_enabled ? '/auth/mfa/disable' : '/auth/mfa/enable', { otp }), onSuccess: () => { setSetup(null); setOtp(''); void reload() } })
  const change = useMutation({ mutationFn: () => post('/auth/password', pw), onSuccess: () => setPw({ current_password: '', new_password: '' }) })
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Two-factor authentication (TOTP)" subtitle={user?.mfa_enabled ? 'Enabled' : 'Disabled'} />
        <CardBody className="space-y-3 text-sm">
          {!user?.mfa_enabled && !setup && <Button onClick={() => begin.mutate()}>Set up authenticator</Button>}
          {setup && <div className="space-y-1"><p>Add this secret to your authenticator app (offline-friendly; no QR service is contacted):</p><p className="mono break-all rounded bg-bg p-2 text-xs">{setup.secret}</p><p className="mono break-all text-xs text-muted">{setup.otpauth_uri}</p></div>}
          {(setup || user?.mfa_enabled) && (
            <div className="flex items-end gap-2">
              <Field label="6-digit code"><Input inputMode="numeric" maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value)} className="w-32" /></Field>
              <Button variant="primary" onClick={() => enable.mutate()} disabled={otp.length !== 6 || enable.isPending}>{user?.mfa_enabled ? 'Disable MFA' : 'Confirm & enable'}</Button>
            </div>
          )}
          {(begin.isError || enable.isError) && <p className="text-xs text-crit">{problemMessage(begin.error ?? enable.error)}</p>}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Change password" subtitle="All other sessions are revoked after a change." />
        <CardBody className="space-y-3">
          <Field label="Current password"><Input type="password" autoComplete="current-password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
          <Field label="New password"><Input type="password" autoComplete="new-password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
          <Button onClick={() => change.mutate()} disabled={change.isPending || !pw.current_password || !pw.new_password}>Change password</Button>
          {change.isError && <p className="text-xs text-crit">{problemMessage(change.error)}</p>}
          {change.isSuccess && <p className="text-xs text-ok">Password changed.</p>}
        </CardBody>
      </Card>
    </div>
  )
}
