import { useQuery } from '@tanstack/react-query'
import type { Core } from 'cytoscape'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DataState, Empty } from '@/components/states'
import { Badge, Button, Field, Select } from '@/components/ui/primitives'
import { get } from '@/services/api'
import type { CyElements } from '@/types/api'
import { CyGraph, Legend, nodeRoute, NODE_TYPES } from './CyGraph'

/** Graph around one entity with hop control, type filters, PNG/JSON export and click-through navigation. */
export function GraphPanel({ url, height = 520, defaultHops = 1 }: { url: string; height?: number; defaultHops?: number }) {
  const nav = useNavigate()
  const [hops, setHops] = useState(defaultHops)
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [sel, setSel] = useState<Record<string, unknown> | null>(null)
  const cy = useRef<Core | null>(null)
  const q = useQuery({ queryKey: ['graph', url, hops], queryFn: () => get<CyElements>(url, { hops, max_nodes: 400 }) })

  function exportPng() {
    const png = cy.current?.png({ full: true, bg: '#080d18', scale: 2 })
    if (!png) return
    const a = document.createElement('a')
    a.href = png
    a.download = 'bitguard-graph.png'
    a.click()
  }
  function exportJson() {
    if (!q.data) return
    const blob = new Blob([JSON.stringify(q.data, null, 1)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'bitguard-graph.json'
    a.click()
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Hops">
          <Select value={hops} onChange={(e) => setHops(Number(e.target.value))} className="w-24">
            {[1, 2, 3, 4].map((h) => <option key={h} value={h}>{h}</option>)}
          </Select>
        </Field>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Toggle node types">
          {NODE_TYPES.filter((n) => n.type !== 'address' && n.type !== 'transaction').map((n) => (
            <Button key={n.type} size="sm" variant={hidden.has(n.type) ? 'ghost' : 'secondary'} aria-pressed={!hidden.has(n.type)}
              onClick={() => setHidden((h) => { const x = new Set(h); if (x.has(n.type)) x.delete(n.type); else x.add(n.type); return x })}>
              {n.label}
            </Button>
          ))}
        </div>
        <div className="ml-auto flex gap-2">
          <Button size="sm" onClick={() => cy.current?.fit(undefined, 30)}>Fit</Button>
          <Button size="sm" onClick={exportPng}>PNG</Button>
          <Button size="sm" onClick={exportJson}>JSON</Button>
        </div>
      </div>
      <DataState query={q} isEmpty={(d) => d.nodes.length === 0} empty={<Empty title="No graph data for this entity" />}>
        {(d) => (
          <>
            {d.truncated && <Badge tone="warn">Graph truncated at node budget — narrow hops or use path analysis</Badge>}
            <CyGraph elements={d} hiddenTypes={hidden} onSelect={setSel} onReady={(c) => (cy.current = c)} height={height} />
            <Legend />
            {d.limitations && <p className="text-xs text-muted">{d.limitations}</p>}
          </>
        )}
      </DataState>
      {sel && (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-line bg-bg-2 p-3 text-sm">
          <Badge tone="info">{String(sel.type)}</Badge>
          <span className="mono truncate">{String(sel.address ?? sel.txid ?? sel.ip ?? sel.asn ?? sel.label)}</span>
          {sel.risk_score !== undefined && <span>risk <span className="mono">{String(sel.risk_score)}</span></span>}
          {nodeRoute(sel) && <Button size="sm" variant="primary" className="ml-auto" onClick={() => nav(nodeRoute(sel)!)}>Open</Button>}
        </div>
      )}
    </div>
  )
}
