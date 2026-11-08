import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { HBar } from '@/components/charts'
import { DataState, Empty } from '@/components/states'
import { Pagination } from '@/components/Pagination'
import { Badge, Button, Card, CardBody, CardHeader, KV, Select, Table, Td, Th } from '@/components/ui/primitives'
import { PageHeader } from '@/layouts/AppLayout'
import { get, post, problemMessage } from '@/services/api'
import { useAuth } from '@/stores/auth'
import type { Contribution, ModelInfo, Paginated } from '@/types/api'
import { formatDate, shortHash } from '@/utils/format'

const METRIC_KEYS = ['pr_auc', 'roc_auc', 'precision', 'recall', 'f1', 'false_positive_rate', 'precision_at_50', 'precision_at_100', 'seed_stability_spearman', 'flag_rate', 'positives', 'n']

export default function IntelligencePage() {
  const { can } = useAuth()
  const qc = useQueryClient()
  const [et, setEt] = useState<'transaction' | 'address'>('transaction')
  const [sel, setSel] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const models = useQuery({ queryKey: ['models', et], queryFn: () => get<ModelInfo[]>('/ai/models', { entity_type: et }) })
  const active = models.data?.find((m) => m.is_active)
  const detailId = sel ?? active?.id
  const detail = useQuery({ queryKey: ['model', detailId], enabled: !!detailId, queryFn: () => get<ModelInfo & { predictions: number }>(`/ai/models/${detailId}`) })
  const preds = useQuery({ queryKey: ['preds', et, offset], queryFn: () => get<Paginated<{ entity_key: string; anomaly_score: number; is_outlier: boolean; contributions: Contribution[]; explanation_method: string }>>('/ai/predictions', { entity_type: et, outliers_only: true, limit: 20, offset }) })
  const train = useMutation({ mutationFn: () => post('/ai/models/train', { entity_type: et, seed: 42 }), onSuccess: () => void qc.invalidateQueries({ queryKey: ['models'] }) })
  const activate = useMutation({ mutationFn: (id: string) => post(`/ai/models/${id}/activate`), onSuccess: () => void qc.invalidateQueries() })

  return (
    <>
      <PageHeader title="AI intelligence" subtitle="Unsupervised anomaly models (Isolation Forest primary, LOF comparison). Scores are outlier ranks, not probabilities."
        actions={<>
          <Select aria-label="Entity type" value={et} onChange={(e) => { setEt(e.target.value as 'transaction' | 'address'); setSel(null); setOffset(0) }} className="w-40"><option value="transaction">Transactions</option><option value="address">Addresses</option></Select>
          {can('model.train') && <Button variant="primary" onClick={() => train.mutate()} disabled={train.isPending}>{train.isPending ? 'Training…' : 'Train & compare'}</Button>}
        </>} />
      {train.isError && <p className="mb-3 text-sm text-crit">{problemMessage(train.error)}</p>}
      <Card className="mb-4">
        <CardHeader title="Model versions & training history" />
        <DataState query={models} isEmpty={(m) => m.length === 0} empty={<Empty title="No models trained yet">Models are trained automatically after the first processed dataset.</Empty>}>
          {(ms) => (
            <Table>
              <thead><tr><Th>Model</Th><Th>Version</Th><Th>Trained</Th><Th>Labels</Th><Th>PR-AUC</Th><Th>Stability</Th><Th>Status</Th><Th /></tr></thead>
              <tbody>{ms.map((m) => (
                <tr key={m.id} className={m.id === detailId ? 'bg-bg-2' : ''}>
                  <Td><button className="text-accent-2 hover:underline" onClick={() => setSel(m.id)}>{m.algorithm}</button></Td>
                  <Td className="mono text-xs">{m.version}</Td><Td className="mono text-xs">{formatDate(m.trained_at)}</Td>
                  <Td><Badge tone={m.evaluation?.label_source === 'none' ? 'neutral' : 'accent'}>{m.evaluation?.label_source ?? '—'}</Badge></Td>
                  <Td className="mono">{fmtMetric(m.evaluation?.metrics.pr_auc)}</Td>
                  <Td className="mono">{fmtMetric(m.evaluation?.metrics.seed_stability_spearman)}</Td>
                  <Td>{m.is_active ? <Badge tone="ok">active</Badge> : <Badge>inactive</Badge>}</Td>
                  <Td>{!m.is_active && can('model.train') && <Button size="sm" onClick={() => activate.mutate(m.id)} disabled={activate.isPending}>Activate</Button>}</Td>
                </tr>
              ))}</tbody>
            </Table>
          )}
        </DataState>
      </Card>
      {detailId && (
        <DataState query={detail}>
          {(m) => (
            <div className="mb-4 grid gap-4 xl:grid-cols-2">
              <Card>
                <CardHeader title={`Evaluation — ${m.name}@${m.version}`} subtitle={m.evaluation?.caveats} />
                <CardBody className="space-y-3">
                  <KV cols={3} items={METRIC_KEYS.filter((k) => m.evaluation?.metrics[k] !== undefined).map((k) => [k, fmtMetric(m.evaluation?.metrics[k])])} />
                  {m.evaluation?.metrics.confusion_matrix !== undefined && <p className="mono text-xs text-muted">confusion matrix (holdout): {JSON.stringify(m.evaluation.metrics.confusion_matrix)}</p>}
                  <KV cols={2} items={[['Seed', m.random_seed], ['Artifact SHA-256', shortHash(m.artifact_sha256, 12)], ['Training rows', String(m.training_snapshot.train_rows ?? '—')], ['Holdout rows', String(m.training_snapshot.holdout_rows ?? '—')], ['Split', String(m.training_snapshot.split ?? '—')], ['Predictions stored', m.predictions]]} />
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Feature importance among outliers" subtitle="Mean contribution across flagged entities" />
                <CardBody>
                  {m.feature_importance_among_outliers?.length ? <HBar label="Feature importance" data={m.feature_importance_among_outliers.slice(0, 12).map((f) => ({ name: f.feature, value: f.mean_contribution }))} /> : <Empty title="No predictions for this model" />}
                </CardBody>
              </Card>
            </div>
          )}
        </DataState>
      )}
      <Card>
        <CardHeader title="Prediction explanations (outliers, active model)" />
        <DataState query={preds} isEmpty={(p) => p.items.length === 0} empty={<Empty title="No outliers" />}>
          {(p) => (
            <>
              <Table>
                <thead><tr><Th>Entity</Th><Th>Score</Th><Th>Top contributing features</Th><Th>Method</Th></tr></thead>
                <tbody>{p.items.map((x) => (
                  <tr key={x.entity_key}>
                    <Td><Link className="mono text-accent-2 hover:underline" to={et === 'transaction' ? `/transactions/${x.entity_key}?tab=risk` : `/addresses/${encodeURIComponent(x.entity_key)}?tab=risk`}>{shortHash(x.entity_key)}</Link></Td>
                    <Td className="mono">{x.anomaly_score.toFixed(4)}</Td>
                    <Td className="text-xs">{x.contributions.slice(0, 3).map((c) => `${c.feature} (${c.direction})`).join(', ')}</Td>
                    <Td><Badge>{x.explanation_method}</Badge></Td>
                  </tr>
                ))}</tbody>
              </Table>
              <Pagination total={p.total} limit={20} offset={offset} onChange={setOffset} />
            </>
          )}
        </DataState>
      </Card>
    </>
  )
}

function fmtMetric(v: unknown): string {
  if (v === undefined || v === null) return '—'
  return typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(4)) : String(v)
}
