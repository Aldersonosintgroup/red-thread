import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { CaseScoreOut, FlagOut } from '../types'
import { SeverityBadge } from './Badge'

const WEIGHT_LABELS: Record<string, string> = {
  timeline_score: 'Timeline (25%)',
  entity_match_score: 'Entity Match (35%)',
  financial_score: 'Financial (20%)',
  contradiction_score: 'Contradictions (15%)',
  legal_score: 'Legal (5%)',
}

export function FlagsScorePanel({ caseId }: { caseId: string }) {
  const [score, setScore] = useState<CaseScoreOut | null>(null)
  const [flags, setFlags] = useState<FlagOut[]>([])
  const [error, setError] = useState<string | null>(null)
  const [recomputing, setRecomputing] = useState(false)
  const [docNames, setDocNames] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  async function load() {
    try {
      const [scoreData, flagData, docs] = await Promise.all([api.getScore(caseId), api.getFlags(caseId), api.listDocuments(caseId)])
      setScore(scoreData)
      setFlags(flagData)
      setDocNames(Object.fromEntries(docs.map((d) => [d.id, d.filename])))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load score and flags.')
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

  async function handleRecompute() {
    setRecomputing(true)
    try {
      await api.recomputeScore(caseId)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to recompute score.')
    } finally {
      setRecomputing(false)
    }
  }

  const severityOrder = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']
  const sortedFlags = [...flags].sort((a, b) => severityOrder.indexOf(a.severity) - severityOrder.indexOf(b.severity))
  // The same flag raised by many documents (e.g. one decree cited in 36
  // pages) is shown once, with the documents behind it on expand.
  const flagGroups: { key: string; flags: FlagOut[] }[] = []
  for (const flag of sortedFlags) {
    const key = `${flag.flag_type}|${flag.severity}|${flag.title}`
    const group = flagGroups.find((g) => g.key === key)
    if (group) group.flags.push(flag)
    else flagGroups.push({ key, flags: [flag] })
  }
  const toggle = (key: string) =>
    setExpanded((prev) => { const next = new Set(prev); if (next.has(key)) next.delete(key); else next.add(key); return next })

  return (
    <div className="space-y-6">
      {error && <p className="text-red-400 text-sm">{error}</p>}

      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium text-neutral-300">Case Irregularity Score</h3>
        <button
          onClick={handleRecompute}
          disabled={recomputing}
          className="text-xs text-neutral-400 hover:text-white border border-neutral-700 rounded px-2 py-1"
        >
          {recomputing ? 'Recomputing…' : 'Recompute'}
        </button>
      </div>

      {score && (
        <div className="space-y-2">
          <div className="text-3xl font-bold text-white">{score.total_score.toFixed(1)}<span className="text-neutral-500 text-base"> / 100</span></div>
          {(['timeline_score', 'entity_match_score', 'financial_score', 'contradiction_score', 'legal_score'] as const).map((key) => (
            <div key={key}>
              <div className="flex justify-between text-xs text-neutral-400 mb-0.5">
                <span>{WEIGHT_LABELS[key]}</span>
                <span>{score[key].toFixed(1)}</span>
              </div>
              <div className="h-1.5 bg-neutral-800 rounded overflow-hidden">
                <div className="h-full bg-red-600" style={{ width: `${score[key]}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}

      <div>
        <h3 className="text-sm font-medium text-neutral-300 mb-2">Irregularity & Anomaly Flags</h3>
        <div className="space-y-2">
          {sortedFlags.length === 0 && <p className="text-neutral-600 text-sm">No flags raised for this case.</p>}
          {flagGroups.map(({ key, flags: group }) => {
            const flag = group[0]
            const open = expanded.has(key)
            return (
              <div key={key} className="border border-neutral-800 rounded px-3 py-2">
                <div className="flex items-center gap-2 mb-1">
                  <SeverityBadge severity={flag.severity} />
                  <span className="text-sm font-medium text-neutral-200">{flag.title}</span>
                  {flag.flag_type === 'INVESTIGATOR_FINDING' && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded border border-neutral-700 text-neutral-400 shrink-0"
                      title="Raised by you from testimony or a verified finding. Not counted in the score, which is based on the documents.">
                      raised by investigator
                    </span>
                  )}
                  {group.length > 1 && (
                    <button onClick={() => toggle(key)} className="ml-auto text-xs text-neutral-400 hover:text-white shrink-0">
                      {open ? '▾' : '▸'} raised by {group.length} documents
                    </button>
                  )}
                </div>
                {group.length === 1 || !open ? (
                  <p className="text-xs text-neutral-500">
                    {flag.description}
                    {group.length === 1 && flag.related_document_id && docNames[flag.related_document_id] && (
                      <span className="text-neutral-600"> · {docNames[flag.related_document_id]}</span>
                    )}
                  </p>
                ) : (
                  <ul className="text-xs text-neutral-500 space-y-0.5 mt-1">
                    {group.map((f) => (
                      <li key={f.id}>
                        {f.related_document_id ? docNames[f.related_document_id] ?? 'deleted document' : f.description}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
