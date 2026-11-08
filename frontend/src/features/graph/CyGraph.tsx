import cytoscape, { type Core, type ElementDefinition } from 'cytoscape'
import { useEffect, useRef } from 'react'
import type { CyElements } from '@/types/api'

const BAND: Record<string, string> = { low: '#22c55e', moderate: '#38bdf8', elevated: '#f59e0b', high: '#ef4444' }

export const NODE_TYPES: { type: string; color: string; label: string }[] = [
  { type: 'address', color: '#94a3b8', label: 'Address' },
  { type: 'transaction', color: '#f7931a', label: 'Transaction' },
  { type: 'ip', color: '#a78bfa', label: 'IP (co-occurrence)' },
  { type: 'asn', color: '#64748b', label: 'ASN' },
  { type: 'country', color: '#475569', label: 'Country' },
  { type: 'cluster', color: '#14b8a6', label: 'Cluster (probabilistic)' },
  { type: 'case', color: '#e879f9', label: 'Investigation case' },
]

const STYLE: cytoscape.StylesheetStyle[] = [
  { selector: 'node', style: { 'background-color': '#94a3b8', label: 'data(label)', color: '#cbd5e1', 'font-size': 8, 'text-valign': 'bottom', 'text-margin-y': 3, width: 14, height: 14, 'border-width': 0 } },
  ...NODE_TYPES.map((n) => ({ selector: `node[type = "${n.type}"]`, style: { 'background-color': n.color } })),
  { selector: 'node[type = "transaction"]', style: { shape: 'round-rectangle', width: 16, height: 12 } },
  { selector: 'node[type = "ip"]', style: { shape: 'diamond' } },
  { selector: 'node[type = "cluster"]', style: { shape: 'hexagon' } },
  ...Object.entries(BAND).map(([b, c]) => ({ selector: `node[risk_band = "${b}"]`, style: { 'border-width': b === 'low' ? 0 : 3, 'border-color': c } })),
  { selector: 'node[?focus]', style: { width: 26, height: 26, 'border-width': 3, 'border-color': '#e5e7eb' } },
  { selector: 'node:selected', style: { 'border-width': 3, 'border-color': '#38bdf8' } },
  { selector: 'edge', style: { width: 1, 'line-color': '#334155', 'target-arrow-color': '#334155', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.6, 'curve-style': 'bezier' } },
  { selector: 'edge[type = "INPUT_OF"]', style: { 'line-color': '#ef4444', 'target-arrow-color': '#ef4444', opacity: 0.6 } },
  { selector: 'edge[type = "OUTPUT_OF"]', style: { 'line-color': '#22c55e', 'target-arrow-color': '#22c55e', opacity: 0.6 } },
  { selector: 'edge[type = "OBSERVED_FROM"], edge[type = "ASSOCIATED_WITH"]', style: { 'line-style': 'dashed', 'line-color': '#7c3aed', 'target-arrow-shape': 'none', opacity: 0.5 } },
  { selector: 'edge[type = "PART_OF_CLUSTER"], edge[type = "LINKED_TO_CASE"]', style: { 'line-style': 'dotted', 'target-arrow-shape': 'none', opacity: 0.6 } },
]

export interface GraphProps {
  elements: CyElements
  hiddenTypes?: Set<string>
  onSelect?: (data: Record<string, unknown>) => void
  onReady?: (cy: Core) => void
  height?: number
}

export function CyGraph({ elements, hiddenTypes, onSelect, onReady, height = 560 }: GraphProps) {
  const ref = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)

  useEffect(() => {
    if (!ref.current) return
    const els: ElementDefinition[] = [...elements.nodes, ...elements.edges]
    const cy = cytoscape({
      container: ref.current, elements: els, style: STYLE, minZoom: 0.1, maxZoom: 4,
      layout: { name: elements.nodes.length > 600 ? 'grid' : 'cose', animate: false, nodeRepulsion: () => 9000, idealEdgeLength: () => 60, randomize: false } as cytoscape.LayoutOptions,
    })
    cy.on('tap', 'node', (e) => onSelect?.(e.target.data()))
    cyRef.current = cy
    onReady?.(cy)
    return () => cy.destroy()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elements])

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().forEach((n) => {
      n.style('display', hiddenTypes?.has(n.data('type') as string) ? 'none' : 'element')
    })
  }, [hiddenTypes, elements])

  return <div ref={ref} style={{ height }} className="w-full rounded-md border border-line bg-bg" role="img" aria-label={`Graph with ${elements.node_count} nodes and ${elements.edge_count} edges`} />
}

export function Legend() {
  return (
    <div className="flex flex-wrap gap-3 text-xs text-muted">
      {NODE_TYPES.map((n) => (
        <span key={n.type} className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: n.color }} />{n.label}</span>
      ))}
      <span className="inline-flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-crit" />input → tx</span>
      <span className="inline-flex items-center gap-1.5"><span className="inline-block h-0.5 w-4 bg-ok" />tx → output</span>
      <span>Ring colour = risk band</span>
    </div>
  )
}

export function nodeRoute(d: Record<string, unknown>): string | null {
  switch (d.type) {
    case 'address': return `/addresses/${encodeURIComponent(String(d.address))}`
    case 'transaction': return `/transactions/${String(d.txid)}`
    case 'ip': return `/network/ip/${encodeURIComponent(String(d.ip))}`
    case 'asn': return `/network/asn/${String(d.asn)}`
    case 'cluster': return `/graph/clusters/${String(d.cluster_id)}`
    case 'case': return `/investigations/${String(d.case_id)}`
    default: return null
  }
}
