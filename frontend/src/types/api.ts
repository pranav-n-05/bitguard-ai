export type Band = 'low' | 'moderate' | 'elevated' | 'high'
export type AlertStatus = 'new' | 'acknowledged' | 'under_investigation' | 'escalated' | 'resolved' | 'false_positive'
export type CaseStatus = 'open' | 'in_progress' | 'on_hold' | 'closed'
export type DataQuality = 'valid' | 'partial' | 'invalid' | 'quarantined' | 'unavailable'

export interface Paginated<T> { items: T[]; total: number; limit: number; offset: number }
export interface Problem { title: string; status: number; detail: string; errors?: { loc: (string | number)[]; msg: string }[]; request_id?: string }

export interface User {
  id: string; email: string; full_name: string; is_active: boolean; mfa_enabled: boolean
  role_names: string[]; permission_codes: string[]; last_login_at: string | null
}
export interface TokenPair { access_token: string; refresh_token: string; expires_at: string }

export interface RiskBrief { score: number; band: Band; assessment_id: number }
export interface Tx {
  txid: string; first_seen_at: string; block_height: number | null; total_input_sat: number; total_output_sat: number
  fee_sat: number; input_count: number; output_count: number; script_type: string | null; data_quality: DataQuality
  dataset_id: string; risk: RiskBrief | null; alert_count: number
}
export interface Io { position: number; address: string; amount_sat: number; script_type: string | null }
export interface Observation {
  id: number; observed_at: string; src_ip: string; dst_ip: string; src_port: number; dst_port: number
  protocol: string | null; asn: number | null; geo_country: string | null; data_quality: DataQuality
}
export interface Detection { id: number; pattern: string; confidence: number; explanation: string; limitations: string; metrics: Record<string, unknown>; txids: string[]; anchor_txid?: string | null; addresses?: string[] }
export interface TxDetail extends Tx {
  block_hash: string | null; vsize: number | null; version: number | null; locktime: number | null; content_hash: string
  inputs: Io[]; outputs: Io[]; observations: Observation[]; features: Record<string, number | null> | null
  feature_schema_version: string | null; graph_detections: Detection[]
  provenance: { dataset_id: string; dataset_name: string; provenance: string; dataset_file_id: string; file_name: string; file_sha256: string; raw_record_id: number; record_index: number; record_hash: string }
  data_labels: string[]
}
export interface RiskComponent { component: string; normalised: number; weight: number; contribution: number; raw_value: number | null; rationale: string; available: boolean }
export interface Contribution { feature: string; contribution: number; direction: 'high' | 'low'; value: number | null; missing: boolean }
export interface RiskDetail {
  available: boolean; reason?: string; entity_type: string; entity_key: string; assessment_id: number; score: number; band: Band
  uncertainty: number; rule_version: string; weights: Record<string, number>; model_version_id: string | null; explanation: string
  limitations: string; recommended_action: string; evidence_refs: Record<string, unknown>; assessed_at: string
  components: RiskComponent[]
  anomaly: { anomaly_score: number; raw_score: number; is_outlier: boolean; top_features: Contribution[]; explanation_method: string; note: string } | null
  history: { assessment_id: number; score: number; band: Band; assessed_at: string; is_current: boolean; change_reason: string | null }[]
  alerts: { id: string; category: string; status: AlertStatus; severity: Band }[]
}
export interface AddressInfo {
  address: string; address_type: string; network: string; first_seen_at: string; last_seen_at: string
  features: Record<string, unknown> | null
  clusters: { cluster_id: string; method: string; cluster_confidence: number; size: number; link_confidence: number; review_status: string; limitations: string }[]
  correlations: { id: number; type: string; strength: number; confidence: number; metrics: Record<string, unknown>; limitations: string }[]
  graph_detections: Detection[]; risk: RiskBrief | null; investigations: string[]; notice: string
}
export interface Alert {
  id: string; category: string; severity: Band; status: AlertStatus; title: string; entity_type: string; entity_key: string
  txid: string | null; addresses: string[]; network_observation_ids: number[]; risk_score: number | null; risk_assessment_id: number | null
  detection_method: string; triggered_rules: Record<string, unknown>[]; model_version_id: string | null; evidence_refs: Record<string, unknown>
  explanation: string; confidence: string; uncertainty_notes: string; assigned_to: string | null; occurrence_count: number
  resolution_note: string | null; created_at: string; updated_at: string
}
export interface AlertDetail extends Alert {
  notes: { id: number; author_id: string; body: string; created_at: string }[]
  related_alerts: { id: string; category: string; severity: Band; status: AlertStatus; reason: string }[]
  allowed_transitions: AlertStatus[]
}
export interface CaseRow {
  id: string; case_number: string; title: string; summary: string | null; status: CaseStatus; priority: Band
  created_by: string; assigned_to: string | null; analyst_decision: string | null; created_at: string; updated_at: string; closed_at: string | null
}
export interface Evidence {
  id: number; evidence_type: string; reference: string; description: string; source_file_sha256: string | null; record_hash: string | null
  txid: string | null; integrity_hash: string; retrieved_at: string; analysis_version: Record<string, unknown>; snapshot: Record<string, unknown>
}
export interface CaseBundle {
  case: { id: string; case_number: string; title: string; summary: string | null; status: CaseStatus; priority: Band; created_by: string; assigned_to: string | null; analyst_decision: string | null; created_at: string; closed_at: string | null }
  transactions: { txid: string; first_seen_at: string; total_output_sat: number; fee_sat: number; inputs: number; outputs: number; risk_score: number | null; risk_band: Band | null }[]
  addresses: { address: string; risk_score: number | null }[]
  alerts: { id: string; category: string; severity: Band; status: AlertStatus; risk_score: number | null; explanation: string }[]
  network_observation_ids: number[]
  notes: { author: string; at: string; body: string }[]
  evidence: { id: number; type: string; reference: string; description: string; integrity_hash: string; record_hash: string | null; source_file_sha256: string | null; retrieved_at: string; added_by: string }[]
  timeline: { seq: number; at: string; action: string; actor: string | null; details: Record<string, unknown>; entry_hash: string }[]
  disclaimer: string
}
export interface Report { id: string; report_type: string; format: string; investigation_id: string | null; parameters: Record<string, unknown>; sha256: string; size_bytes: number; generated_by: string; generated_at: string }
export interface ModelInfo {
  id: string; name: string; algorithm: string; version: string; entity_type: string; params: Record<string, unknown>
  feature_schema: { features: string[] }; training_snapshot: Record<string, unknown>; artifact_sha256: string; random_seed: number
  is_active: boolean; trained_at: string; notes: string | null
  evaluation: { label_source: string; metrics: Record<string, unknown>; caveats: string } | null
  feature_importance_among_outliers?: { feature: string; mean_contribution: number }[]
}
export interface Dataset { id: string; name: string; description: string | null; provenance: string; status: string; created_at: string }
export interface Job {
  id: string; dataset_id: string; dataset_file_id: string; status: string; stage: string; attempts: number; total_records: number | null
  processed_records: number; valid_records: number; partial_records: number; quarantined_records: number; duplicate_records: number
  started_at: string | null; finished_at: string | null; error_message: string | null; created_at: string
}
export interface CyElements { nodes: { data: Record<string, unknown> & { id: string; type: string; label: string } }[]; edges: { data: Record<string, unknown> & { id: string; source: string; target: string; type: string } }[]; truncated: boolean; node_count: number; edge_count: number; limitations?: string }
