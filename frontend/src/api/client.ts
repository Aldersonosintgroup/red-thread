import axios from 'axios'
import type {
  Actor, ActorDetails, AppSettings, AppSettingsUpdate, CaseAnalysisOut, StatementIn, StatementOut, CaseDetail, CaseScoreOut, CaseSummary, DiscrepancyGroup,
  DocumentOut, DuplicateDocumentSuggestion, Edge, ExtractionResult, FlagOut, MergeSuggestion, RecurringActor, RecurringTier, SeparatedPair,
  TimelineCleanupPlan, TimelineEventOut, VaultStatus, WatchlistCategory, WatchlistEntityOut,
} from '../types'

// Overridable for test builds only (VITE_API_BASE); the app always uses 8420.
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8420'

const http = axios.create({ baseURL: API_BASE, timeout: 20000 })

// Fired whenever the backend answers 423 (encryption on and the vault
// locked, e.g. after auto-lock); the VaultGate swaps in the unlock screen.
export const LOCKED_EVENT = 'redthread:locked'
http.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 423) window.dispatchEvent(new Event(LOCKED_EVENT))
    return Promise.reject(error)
  },
)

export class ApiError extends Error {
  status?: number
  constructor(message: string, status?: number) {
    super(message)
    this.status = status
  }
}

// On a fresh install's first-ever launch, Windows Defender (or similar)
// scans the just-written backend executable before letting it run, which
// can push startup well past a few seconds. The backend WILL come up —
// Tauri's own startup gate only shows the window after a successful health
// check — so callers retry indefinitely instead of giving up with a
// dead-end error for what is actually still normal startup.
const STARTUP_RETRY_INTERVAL_MS = 1500
const STARTUP_SLOW_AFTER_ATTEMPTS = 20 // ~30s: let the caller switch messaging

export async function retryOnStartup<T>(
  fn: () => Promise<T>,
  onSlowStartup?: (err: unknown) => void,
): Promise<T> {
  let attempt = 0
  for (;;) {
    attempt += 1
    try {
      return await fn()
    } catch (err) {
      if (attempt === STARTUP_SLOW_AFTER_ATTEMPTS) {
        onSlowStartup?.(err)
      }
      await new Promise((resolve) => setTimeout(resolve, STARTUP_RETRY_INTERVAL_MS))
    }
  }
}

function unwrap<T>(promise: Promise<{ data: T }>): Promise<T> {
  return promise
    .then((res) => res.data)
    .catch((err) => {
      const detail = err?.response?.data?.detail
      const message = typeof detail === 'string' ? detail : err?.message || 'Request failed'
      throw new ApiError(message, err?.response?.status)
    })
}

export const api = {
  listCases: () => unwrap<CaseSummary[]>(http.get('/api/cases')),
  createCase: (payload: {
    case_number: string
    title: string
    subject: { full_name: string; aliases: string[]; date_of_birth: string | null; birth_place: string | null; notes: string | null }
  }) => unwrap<CaseDetail>(http.post('/api/cases', payload)),
  getCase: (caseId: string) => unwrap<CaseDetail>(http.get(`/api/cases/${caseId}`)),
  updateCase: (caseId: string, payload: { notes?: string }) =>
    unwrap<CaseDetail>(http.patch(`/api/cases/${caseId}`, payload)),
  deleteCase: (caseId: string) => unwrap<void>(http.delete(`/api/cases/${caseId}`)),

  listDocuments: (caseId: string) => unwrap<DocumentOut[]>(http.get(`/api/cases/${caseId}/documents`)),
  getDocument: (caseId: string, docId: string) =>
    unwrap<DocumentOut>(http.get(`/api/cases/${caseId}/documents/${docId}`)),
  uploadDocument: (caseId: string, file: File) => {
    const form = new FormData()
    form.append('file', file)
    return unwrap<DocumentOut>(
      http.post(`/api/cases/${caseId}/documents`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      }),
    )
  },
  commitDocument: (caseId: string, docId: string, edited_extraction: ExtractionResult) =>
    unwrap<DocumentOut>(http.post(`/api/cases/${caseId}/documents/${docId}/commit`, { edited_extraction })),
  createManualDocument: (caseId: string, label: string) =>
    unwrap<DocumentOut>(http.post(`/api/cases/${caseId}/documents/manual`, { label })),
  uncommitDocument: (caseId: string, docId: string) =>
    unwrap<DocumentOut>(http.post(`/api/cases/${caseId}/documents/${docId}/uncommit`)),
  deleteDocument: (caseId: string, docId: string) =>
    unwrap<void>(http.delete(`/api/cases/${caseId}/documents/${docId}`)),
  rereadAllDocuments: (caseId: string) =>
    unwrap<{ queued: number; manual_entries_reopened: number }>(http.post(`/api/cases/${caseId}/documents/reread-all`)),
  reextractDocument: (caseId: string, docId: string) =>
    unwrap<DocumentOut>(http.post(`/api/cases/${caseId}/documents/${docId}/reextract`)),
  rotateDocument: (caseId: string, docId: string, degrees: number) =>
    unwrap<DocumentOut>(http.post(`/api/cases/${caseId}/documents/${docId}/rotate`, null, { params: { degrees } })),
  getDuplicateDocuments: (caseId: string) =>
    unwrap<DuplicateDocumentSuggestion[]>(http.get(`/api/cases/${caseId}/documents/duplicate-suggestions`)),
  cleanExactDuplicateDocuments: (caseId: string) =>
    unwrap<{ deleted_count: number }>(http.post(`/api/cases/${caseId}/documents/clean-exact-duplicates`)),
  documentFileUrl: (caseId: string, docId: string) => `${API_BASE}/api/cases/${caseId}/documents/${docId}/file`,

  listStatements: (caseId: string) => unwrap<StatementOut[]>(http.get(`/api/cases/${caseId}/statements`)),
  createStatement: (caseId: string, body: StatementIn) => unwrap<StatementOut>(http.post(`/api/cases/${caseId}/statements`, body)),
  updateStatement: (caseId: string, id: string, body: StatementIn) =>
    unwrap<StatementOut>(http.put(`/api/cases/${caseId}/statements/${id}`, body)),
  deleteStatement: (caseId: string, id: string) => unwrap<void>(http.delete(`/api/cases/${caseId}/statements/${id}`)),
  listActors: (caseId: string) => unwrap<Actor[]>(http.get(`/api/cases/${caseId}/actors`)),
  updateActor: (caseId: string, actorId: string, payload: Partial<Pick<Actor, 'canonical_name' | 'role' | 'notes' | 'custom_color'>>) =>
    unwrap<Actor>(http.patch(`/api/cases/${caseId}/actors/${actorId}`, payload)),
  deleteActor: (caseId: string, actorId: string) =>
    unwrap<void>(http.delete(`/api/cases/${caseId}/actors/${actorId}`)),
  mergeActors: (caseId: string, source_actor_id: string, target_actor_id: string) =>
    unwrap<Actor>(http.post(`/api/cases/${caseId}/actors/merge`, { source_actor_id, target_actor_id })),
  getActorDetails: (caseId: string, actorId: string) =>
    unwrap<ActorDetails>(http.get(`/api/cases/${caseId}/actors/${actorId}/details`)),
  getMergeSuggestions: (caseId: string) =>
    unwrap<MergeSuggestion[]>(http.get(`/api/cases/${caseId}/actors/merge-suggestions`)),
  listEdges: (caseId: string) => unwrap<Edge[]>(http.get(`/api/cases/${caseId}/edges`)),

  getScore: (caseId: string) => unwrap<CaseScoreOut>(http.get(`/api/cases/${caseId}/score`)),
  recomputeScore: (caseId: string) => unwrap<CaseScoreOut>(http.post(`/api/cases/${caseId}/score/recompute`)),
  getFlags: (caseId: string) => unwrap<FlagOut[]>(http.get(`/api/cases/${caseId}/flags`)),
  getDiscrepancies: (caseId: string) => unwrap<DiscrepancyGroup[]>(http.get(`/api/cases/${caseId}/discrepancies`)),
  getTimeline: (caseId: string) => unwrap<TimelineEventOut[]>(http.get(`/api/cases/${caseId}/timeline`)),
  getTimelineCleanup: (caseId: string) =>
    unwrap<TimelineCleanupPlan>(http.get(`/api/cases/${caseId}/timeline/cleanup`)),
  runTimelineCleanup: (caseId: string, options: { redate: boolean; relabel: boolean }) =>
    unwrap<{ redated: number; relabelled: number }>(http.post(`/api/cases/${caseId}/timeline/cleanup`, options)),
  setTimelineExcluded: (caseId: string, event_ids: string[], excluded: boolean) =>
    unwrap<{ changed: number }>(http.post(`/api/cases/${caseId}/timeline/exclude`, { event_ids, excluded })),

  listAnalyses: (caseId: string) => unwrap<CaseAnalysisOut[]>(http.get(`/api/cases/${caseId}/analyses`)),
  // Reasoning over a whole case takes one to a few minutes.
  createAnalysis: (caseId: string, language: 'en' | 'es') =>
    unwrap<CaseAnalysisOut>(http.post(`/api/cases/${caseId}/analyses`, { language }, { timeout: 900000 })),
  getAnalysisRecord: (caseId: string, analysisId: string) =>
    unwrap<CaseAnalysisOut>(http.get(`/api/cases/${caseId}/analyses/${analysisId}/record`)),
  deleteAnalysis: (caseId: string, analysisId: string) =>
    unwrap<void>(http.delete(`/api/cases/${caseId}/analyses/${analysisId}`)),

  listRecurringActors: () => unwrap<RecurringActor[]>(http.get('/api/recurring-actors')),
  getRecurringInCase: (caseId: string) =>
    unwrap<Record<string, { other_cases: number; tier: RecurringTier }>>(http.get(`/api/recurring-actors/case/${caseId}`)),
  decideRecurring: (payload: { actor_ids: string[]; against?: string[]; decision: 'confirmed' | 'rejected' | 'clear' }) =>
    unwrap<{ pairs: number }>(http.post('/api/recurring-actors/decisions', payload)),
  listSeparatedPairs: () => unwrap<SeparatedPair[]>(http.get('/api/recurring-actors/separated')),
  undoSeparation: (id: string) => unwrap<void>(http.delete(`/api/recurring-actors/separated/${id}`)),

  listWatchlist: () => unwrap<WatchlistEntityOut[]>(http.get('/api/watchlist')),
  createWatchlistEntity: (payload: { name: string; aliases: string[]; category: WatchlistCategory; entity_type: string | null; notes: string | null }) =>
    unwrap<WatchlistEntityOut>(http.post('/api/watchlist', payload)),
  deleteWatchlistEntity: (entityId: string) => unwrap<void>(http.delete(`/api/watchlist/${entityId}`)),
  watchlistExportUrl: () => `${API_BASE}/api/watchlist/export`,
  importWatchlist: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return unwrap<{ added: number; skipped_existing: number; invalid: number }>(
      http.post('/api/watchlist/import', form, { headers: { 'Content-Type': 'multipart/form-data' } }),
    )
  },

  loadSampleCase: () => unwrap<CaseSummary>(http.post('/api/sample-case')),

  // Key derivation is deliberately slow (~0.5 s), and turning encryption on
  // re-encrypts every evidence file, so these get generous timeouts.
  getVaultStatus: () => unwrap<VaultStatus>(http.get('/api/vault/status')),
  enableEncryption: (passphrase: string) =>
    unwrap<{ recovery_key: string; files_encrypted: number; removed_plaintext_copies: string[] }>(
      http.post('/api/vault/enable', { passphrase }, { timeout: 600000 }),
    ),
  unlockVault: (payload: { passphrase?: string; recovery_key?: string; new_passphrase?: string }) =>
    unwrap<VaultStatus>(http.post('/api/vault/unlock', payload, { timeout: 600000 })),
  lockVault: () => unwrap<VaultStatus>(http.post('/api/vault/lock')),
  changePassphrase: (current_passphrase: string, new_passphrase: string) =>
    unwrap<VaultStatus>(http.post('/api/vault/change-passphrase', { current_passphrase, new_passphrase }, { timeout: 60000 })),
  setAutoLock: (minutes: number) => unwrap<VaultStatus>(http.put('/api/vault/auto-lock', { minutes })),

  getSettings: () => unwrap<AppSettings>(http.get('/api/settings')),
  updateSettings: (payload: AppSettingsUpdate) => unwrap<AppSettings>(http.put('/api/settings', payload)),
  testSettings: () => unwrap<{ ok: boolean; message: string }>(http.post('/api/settings/test')),

  exportPdfUrl: (caseId: string) => `${API_BASE}/api/cases/${caseId}/export/pdf`,
  exportJsonUrl: (caseId: string) => `${API_BASE}/api/cases/${caseId}/export/json`,
}
