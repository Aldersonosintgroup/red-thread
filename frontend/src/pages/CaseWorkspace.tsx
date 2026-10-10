import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, retryOnStartup } from '../api/client'
import { ActorsPanel } from '../components/ActorsPanel'
import { AnalysisPanel } from '../components/AnalysisPanel'
import { DiscrepancyPanel } from '../components/DiscrepancyPanel'
import { DocumentsPanel } from '../components/DocumentsPanel'
import { ExportPanel } from '../components/ExportPanel'
import { FinancialPanel } from '../components/FinancialPanel'
import { FlagsScorePanel } from '../components/FlagsScorePanel'
import { NetworkGraph } from '../components/NetworkGraph'
import { NotesPanel } from '../components/NotesPanel'
import { StatementsPanel } from '../components/StatementsPanel'
import { TimelinePanel } from '../components/TimelinePanel'
import type { CaseDetail } from '../types'

const TABS = ['Documents', 'Statements', 'Network Map', 'Timeline', 'Actors', 'Financial', 'Discrepancies', 'Flags & Score', 'Analysis', 'Notes', 'Export'] as const
type Tab = (typeof TABS)[number]

export function CaseWorkspace() {
  const { caseId } = useParams<{ caseId: string }>()
  const [caseDetail, setCaseDetail] = useState<CaseDetail | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('Documents')
  const [refreshToken, setRefreshToken] = useState(0)

  const loadCase = useCallback(async () => {
    if (!caseId) return
    setError(null)
    const detail = await retryOnStartup(
      () => api.getCase(caseId),
      (err) =>
        setError(
          err instanceof Error
            ? `Still trying to reach the backend: ${err.message}`
            : 'Still trying to reach the backend — this is taking longer than usual.',
        ),
    )
    setError(null)
    setCaseDetail(detail)
  }, [caseId])

  useEffect(() => {
    loadCase()
  }, [loadCase])

  if (!caseId) return null
  if (error) return <div className="p-6 text-amber-400 text-sm">{error}</div>
  if (!caseDetail) return <div className="p-6 text-neutral-500 text-sm">Loading case…</div>

  return (
    <div className="flex flex-col h-full">
      <div className="border-b border-neutral-800 px-6 py-4">
        <div className="flex items-baseline gap-3">
          <h2 className="text-lg font-semibold text-white">{caseDetail.title}</h2>
          <span className="text-neutral-500 text-sm">{caseDetail.case_number}</span>
        </div>
        {caseDetail.subject && (
          <p className="text-neutral-400 text-sm">
            Subject: {caseDetail.subject.full_name}
            {caseDetail.subject.aliases.length > 0 && ` (aka ${caseDetail.subject.aliases.join(', ')})`}
            {caseDetail.subject.date_of_birth && ` · b. ${caseDetail.subject.date_of_birth}`}
          </p>
        )}
      </div>

      <div className="flex border-b border-neutral-800 px-6">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm border-b-2 -mb-px ${
              tab === t ? 'border-red-600 text-white' : 'border-transparent text-neutral-500 hover:text-neutral-300'
            }`}
          >
            {t}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {tab === 'Documents' && (
          <DocumentsPanel caseId={caseId} onCommitted={() => setRefreshToken((v) => v + 1)} />
        )}
        {tab === 'Statements' && <StatementsPanel caseId={caseId} />}
        {tab === 'Network Map' && <NetworkGraph key={refreshToken} caseId={caseId} />}
        {tab === 'Analysis' && <AnalysisPanel caseId={caseId} />}
        {tab === 'Financial' && <FinancialPanel key={refreshToken} caseId={caseId} caseNumber={caseDetail.case_number} />}
        {tab === 'Timeline' && <TimelinePanel key={refreshToken} caseId={caseId} />}
        {tab === 'Actors' && <ActorsPanel key={refreshToken} caseId={caseId} />}
        {tab === 'Discrepancies' && <DiscrepancyPanel key={refreshToken} caseId={caseId} />}
        {tab === 'Flags & Score' && <FlagsScorePanel key={refreshToken} caseId={caseId} />}
        {tab === 'Notes' && <NotesPanel key={caseDetail.id} caseId={caseId} initialNotes={caseDetail.notes} />}
        {tab === 'Export' && <ExportPanel caseId={caseId} />}
      </div>
    </div>
  )
}
