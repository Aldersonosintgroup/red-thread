export interface Subject {
  id: string
  case_id: string
  full_name: string
  aliases: string[]
  date_of_birth: string | null
  birth_place: string | null
  notes: string | null
}

export interface CaseSummary {
  id: string
  case_number: string
  title: string
  status: string
  created_at: string
  updated_at: string
}

export interface CaseDetail extends CaseSummary {
  subject: Subject | null
  notes: string | null
}

export interface Actor {
  id: string
  case_id: string
  canonical_name: string
  aliases: string[]
  role: string | null
  notes: string | null
  is_subject: boolean
  custom_color: string | null
  watchlist_match_id: string | null
  watchlist_match_score: number | null
}

export interface MergeSuggestion {
  actor_a: Actor
  actor_b: Actor
  score: number
}

export interface Edge {
  id: string
  source_actor_id: string
  target_actor_id: string
  relationship_type: string | null
}

export interface ExtractedEntity {
  name: string
  role: string | null
  page?: number | null
}

export interface ExtractedDate {
  label: string
  date: string | null
  raw?: string | null // the date as written in the document, when it differs from `date`
  note?: string | null // ambiguity / unreadable explanation for the reviewer
  page?: number | null
}

export interface ExtractedPayment {
  amount: string | null
  currency: string | null
  description: string | null
  linked_case_number: string | null
  page?: number | null
}

export interface ExtractionResult {
  doc_type: string | null
  names: ExtractedEntity[]
  dates: ExtractedDate[]
  financial_transactions: ExtractedPayment[]
  legal_references: string[]
  raw_text_notes: string | null
  parse_warning: string | null
  extracted_by?: string | null // "<provider>:<model>" that read the document
}

export type DocumentStatus = 'pending' | 'processing' | 'extracted' | 'reviewed' | 'error'

export interface DocumentOut {
  id: string
  case_id: string
  filename: string
  doc_type: string | null
  upload_order: number
  status: DocumentStatus
  error_message: string | null
  uploaded_at: string
  processed_at: string | null
  raw_extraction: ExtractionResult | null
  edited_extraction: ExtractionResult | null
  committed: boolean
  rotation: number
  has_file: boolean
}

export interface DuplicateDocumentSuggestion {
  document_a: DocumentOut
  document_b: DocumentOut
  distance: number
}

export interface TimelineEventOut {
  id: string
  event_type: string
  event_date: string | null
  description: string | null
  source_document_id: string | null
  excluded: boolean
}

export interface FlagOut {
  id: string
  flag_type: string
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW'
  title: string
  description: string | null
  related_document_id: string | null
  related_actor_id: string | null
  legal_reference: string | null
  created_at: string
}

export interface CaseScoreOut {
  timeline_score: number
  entity_match_score: number
  financial_score: number
  contradiction_score: number
  legal_score: number
  total_score: number
  computed_at: string
}

export type WatchlistCategory = 'RED' | 'ORANGE' | 'YELLOW'

export interface WatchlistEntityOut {
  id: string
  name: string
  aliases: string[]
  category: WatchlistCategory
  entity_type: string | null
  notes: string | null
  is_seed: boolean
}

export interface DiscrepancyRow {
  field: string
  document_id: string
  document_filename: string
  value: string
}

export interface DiscrepancyGroup {
  field: string
  rows: DiscrepancyRow[]
  is_contradictory: boolean
}

export interface StatementIn {
  kind: 'testimony' | 'finding'
  statement: string
  source_name: string | null
  source_relationship: string | null
  statement_date: string | null
  method: string | null
  basis: 'firsthand' | 'secondhand' | 'unknown' | null
  status: 'unverified' | 'corroborated' | 'verified'
  relation: 'supports' | 'contradicts' | 'context'
  related_document_ids: string[]
  related_actor_ids: string[]
  flag_severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | null
}

export interface StatementOut extends StatementIn {
  id: string
  case_id: string
  created_at: string
  updated_at: string | null
}

export interface AppSettings {
  ai_provider: string
  ollama_vision_model: string
  claude_vision_model: string
  gemini_vision_model: string
  openai_vision_model: string
  xai_model: string
  custom_base_url: string
  custom_model: string
  encryption_enabled: boolean
  anthropic_key_configured: boolean
  gemini_key_configured: boolean
  openai_key_configured: boolean
  xai_key_configured: boolean
  custom_key_configured: boolean
}

/** Fields accepted by PUT /api/settings: plain settings plus write-only API keys. */
export type AppSettingsUpdate = Partial<Pick<AppSettings,
  'ai_provider' | 'claude_vision_model' | 'gemini_vision_model' | 'openai_vision_model' | 'xai_model' | 'custom_base_url' | 'custom_model'>> & {
  anthropic_api_key?: string
  gemini_api_key?: string
  openai_api_key?: string
  xai_api_key?: string
  custom_api_key?: string
}

export interface VaultStatus {
  enabled: boolean
  locked: boolean
  auto_lock_minutes: number
  min_passphrase_length: number
}

export interface TimelineCleanupPlan {
  redate: { id: string; description: string | null; new_date: string; note: string | null }[]
  relabel: { id: string; description: string | null; from_type: string; to_type: string }[]
  duplicate_groups: { event_type: string; event_date: string | null; count: number }[]
}

export interface AnalysisEvidence { statement: string; sources: string[]; unsupported?: boolean }
export interface AnalysisHypothesis {
  title: string
  explanation: string
  supporting_evidence: AnalysisEvidence[]
  contradicting_evidence: AnalysisEvidence[]
  benign_explanations: string[]
  confidence: 'low' | 'moderate' | 'high'
  would_confirm: string[]
  would_refute: string[]
}
export interface CaseAnalysisOut {
  id: string
  created_at: string
  language: 'en' | 'es'
  model: string
  input_hash: string
  document_count: number
  disclaimer: string
  citation_check: { removed_invalid_citations: number; unsupported_statements: number }
  report: {
    summary: string
    established_facts: AnalysisEvidence[]
    hypotheses: AnalysisHypothesis[]
    gaps: string[]
    next_steps: string[]
    data_quality_notes: string[]
  }
  dossier?: string
}

export interface ActorDetails {
  actor: Actor
  watchlist: { name: string; category: WatchlistCategory; entity_type: string | null; notes: string | null; score: number | null } | null
  appearances: { document_id: string; filename: string; doc_type: string | null; name_as_written: string; role: string | null; page: number | null }[]
  flags: FlagOut[]
}
