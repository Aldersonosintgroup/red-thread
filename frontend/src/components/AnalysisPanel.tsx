import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { AnalysisEvidence, AnalysisHypothesis, CaseAnalysisOut } from '../types'

const CONFIDENCE_STYLE: Record<string, string> = {
  low: 'bg-neutral-800 text-neutral-300',
  moderate: 'bg-amber-900/60 text-amber-200',
  high: 'bg-red-900/60 text-red-200',
}

const LABELS = {
  en: {
    summary: 'Summary', facts: 'Established facts', hypotheses: 'Hypotheses', confidence: 'confidence',
    supporting: 'Supporting evidence', contradicting: 'Evidence against / unexplained', benign: 'Possible benign explanations',
    confirm: 'Would confirm', refute: 'Would refute', gaps: 'Gaps in the record', next: 'Recommended next steps',
    quality: 'Data quality notes', unsupported: 'no valid source — treat as unsupported',
  },
  es: {
    summary: 'Resumen', facts: 'Hechos establecidos', hypotheses: 'Hipótesis', confidence: 'confianza',
    supporting: 'Evidencia a favor', contradicting: 'Evidencia en contra / sin explicar', benign: 'Posibles explicaciones inocentes',
    confirm: 'Lo confirmaría', refute: 'Lo refutaría', gaps: 'Vacíos en el registro', next: 'Próximos pasos recomendados',
    quality: 'Notas sobre la calidad de los datos', unsupported: 'sin fuente válida — tratar como no respaldado',
  },
}

/** Minimal, safe rendering of the model's summary: paragraphs, "- " bullets
 *  and **bold**. No HTML from the model is ever injected. */
function RichText({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/)
  const inline = (line: string) =>
    line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith('**') && part.endsWith('**') ? <b key={i} className="text-neutral-100">{part.slice(2, -2)}</b> : part)
  return (
    <div className="space-y-2 text-sm text-neutral-300 leading-relaxed">
      {blocks.map((block, i) => {
        const lines = block.split('\n').filter(Boolean)
        if (lines.every((l) => /^\s*[-•]\s/.test(l))) {
          return <ul key={i} className="list-disc pl-5 space-y-1">{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*[-•]\s/, ''))}</li>)}</ul>
        }
        return <p key={i}>{inline(block)}</p>
      })}
    </div>
  )
}

function Sources({ ids, record }: { ids: string[]; record: Record<string, string> }) {
  return (
    <span className="inline-flex flex-wrap gap-1 ml-1 align-middle">
      {ids.map((id) => (
        <span key={id} title={record[id] ?? id}
          className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-neutral-700 text-neutral-400 cursor-help">
          {id}
        </span>
      ))}
    </span>
  )
}

function EvidenceList({ items, record, unsupportedLabel }: { items: AnalysisEvidence[]; record: Record<string, string>; unsupportedLabel: string }) {
  if (!items.length) return <p className="text-xs text-neutral-600">—</p>
  return (
    <ul className="space-y-1.5">
      {items.map((item, i) => (
        <li key={i} className={`text-sm ${item.unsupported ? 'text-amber-300' : 'text-neutral-300'}`}>
          {item.statement}
          {item.unsupported ? <span className="text-xs text-amber-400"> ({unsupportedLabel})</span> : <Sources ids={item.sources} record={record} />}
        </li>
      ))}
    </ul>
  )
}

function PlainList({ items }: { items: string[] }) {
  if (!items.length) return <p className="text-xs text-neutral-600">—</p>
  return <ul className="list-disc pl-5 space-y-1 text-sm text-neutral-300">{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
}

function Hypothesis({ h, n, record, L }: { h: AnalysisHypothesis; n: number; record: Record<string, string>; L: typeof LABELS.en }) {
  const [open, setOpen] = useState(n === 1)
  return (
    <div className="border border-neutral-800 rounded">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 px-4 py-3 text-left">
        <span className="text-neutral-500 text-xs w-4">{open ? '▾' : '▸'}</span>
        <span className="text-sm font-medium text-white flex-1">{n}. {h.title}</span>
        <span className={`text-[10px] uppercase tracking-wide px-2 py-0.5 rounded ${CONFIDENCE_STYLE[h.confidence]}`}>
          {h.confidence} {L.confidence}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4 pl-11 space-y-3">
          <p className="text-sm text-neutral-300">{h.explanation}</p>
          <div className="grid md:grid-cols-2 gap-4">
            <div><h5 className="text-xs uppercase text-emerald-400 mb-1">{L.supporting}</h5><EvidenceList items={h.supporting_evidence} record={record} unsupportedLabel={L.unsupported} /></div>
            <div><h5 className="text-xs uppercase text-amber-400 mb-1">{L.contradicting}</h5><EvidenceList items={h.contradicting_evidence} record={record} unsupportedLabel={L.unsupported} /></div>
          </div>
          <div><h5 className="text-xs uppercase text-neutral-400 mb-1">{L.benign}</h5><PlainList items={h.benign_explanations} /></div>
          <div className="grid md:grid-cols-2 gap-4">
            <div><h5 className="text-xs uppercase text-neutral-400 mb-1">{L.confirm}</h5><PlainList items={h.would_confirm} /></div>
            <div><h5 className="text-xs uppercase text-neutral-400 mb-1">{L.refute}</h5><PlainList items={h.would_refute} /></div>
          </div>
        </div>
      )}
    </div>
  )
}

export function AnalysisPanel({ caseId }: { caseId: string }) {
  const [analyses, setAnalyses] = useState<CaseAnalysisOut[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [record, setRecord] = useState<{ id: string; dossier: string } | null>(null)
  const [showRecord, setShowRecord] = useState(false)
  const [language, setLanguage] = useState<'en' | 'es'>('en')
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const list = await api.listAnalyses(caseId)
      setAnalyses(list)
      setSelectedId((current) => current && list.some((a) => a.id === current) ? current : list[0]?.id ?? null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load analyses.')
    }
  }, [caseId])

  useEffect(() => { load() }, [load])

  const selected = analyses.find((a) => a.id === selectedId) ?? null

  // The record the analysis was based on, for citation tooltips and audit.
  useEffect(() => {
    if (!selected || record?.id === selected.id) return
    api.getAnalysisRecord(caseId, selected.id)
      .then((a) => setRecord({ id: a.id, dossier: a.dossier ?? '' }))
      .catch(() => setRecord(null))
  }, [caseId, selected, record?.id])

  const citationText = useMemo(() => {
    const map: Record<string, string> = {}
    for (const line of (record?.dossier ?? '').split('\n')) {
      const m = line.match(/^\[([DEAFX]\d+)\]\s*(.*)$/)
      if (m) map[m[1]] = m[2]
    }
    return map
  }, [record])

  useEffect(() => {
    if (!running) return
    const started = Date.now()
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [running])

  async function handleGenerate() {
    setRunning(true)
    setElapsed(0)
    setError(null)
    try {
      const created = await api.createAnalysis(caseId, language)
      setAnalyses((prev) => [created, ...prev])
      setSelectedId(created.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The analysis failed.')
    } finally {
      setRunning(false)
    }
  }

  async function handleDelete() {
    if (!selected) return
    await api.deleteAnalysis(caseId, selected.id)
    setConfirmDelete(false)
    setSelectedId(null)
    await load()
  }

  const L = LABELS[selected?.language ?? 'en']

  return (
    <div className="max-w-5xl space-y-5">
      <div className="border border-neutral-800 rounded p-4 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-white">Case analysis</h3>
            <p className="text-xs text-neutral-400 mt-1 max-w-2xl">
              The AI chosen in Settings reads the reviewed case record (committed documents, timeline, actors, flags and
              discrepancies) and writes a summary, the established facts, and hypotheses about what may have happened, each
              with the evidence for and against it. Every citation is checked against the record. The record is sent to
              that AI provider as text; unreviewed documents are never included.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <select value={language} onChange={(e) => setLanguage(e.target.value as 'en' | 'es')} disabled={running}
              className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1.5 text-sm text-white">
              <option value="en">English</option>
              <option value="es">Español</option>
            </select>
            <button onClick={handleGenerate} disabled={running}
              className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm font-medium px-4 py-1.5 rounded">
              {running ? `Analysing… ${elapsed}s` : 'Generate analysis'}
            </button>
          </div>
        </div>
        {running && <p className="text-xs text-neutral-500">This usually takes one to three minutes. If you switch tabs it still finishes, and appears here when you come back.</p>}
        {error && <p className="text-red-400 text-sm">{error}</p>}
      </div>

      {analyses.length > 1 && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-neutral-500">Saved analyses:</span>
          <select value={selectedId ?? ''} onChange={(e) => { setSelectedId(e.target.value); setShowRecord(false) }}
            className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-neutral-200">
            {analyses.map((a) => (
              <option key={a.id} value={a.id}>
                {new Date(a.created_at).toLocaleString()} · {a.language.toUpperCase()} · {a.document_count} docs
              </option>
            ))}
          </select>
        </div>
      )}

      {!selected && !running && (
        <p className="text-sm text-neutral-500">No analysis yet. Review and commit documents, then generate one.</p>
      )}

      {selected && (
        <div className="space-y-6">
          <div className="border border-amber-800 bg-amber-950/30 rounded px-4 py-3 text-xs text-amber-200">
            <b>{selected.language === 'es' ? 'Aviso' : 'Disclaimer'}:</b> {selected.disclaimer}
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-neutral-500">
            <span>{new Date(selected.created_at).toLocaleString()}</span>
            <span>{selected.model}</span>
            <span>{selected.document_count} reviewed document(s)</span>
            <span title={`SHA-256 of the case record analysed: ${selected.input_hash}`} className="font-mono cursor-help">
              record {selected.input_hash.slice(0, 12)}…
            </span>
            <span className={selected.citation_check.removed_invalid_citations ? 'text-amber-400' : 'text-emerald-500'}>
              {selected.citation_check.removed_invalid_citations
                ? `${selected.citation_check.removed_invalid_citations} invalid citation(s) removed`
                : 'all citations verified'}
            </span>
            <button onClick={() => setShowRecord(!showRecord)} className="text-neutral-400 hover:text-white">
              {showRecord ? 'Hide' : 'Show'} record analysed
            </button>
            {confirmDelete ? (
              <span className="text-red-300">Delete this analysis?
                <button onClick={handleDelete} className="ml-2 text-red-400 hover:text-red-300">Delete</button>
                <button onClick={() => setConfirmDelete(false)} className="ml-2 text-neutral-400">Cancel</button>
              </span>
            ) : (
              <button onClick={() => setConfirmDelete(true)} className="text-neutral-500 hover:text-red-400">Delete</button>
            )}
          </div>

          {showRecord && (
            <pre className="text-[11px] text-neutral-400 bg-neutral-950 border border-neutral-800 rounded p-3 max-h-96 overflow-auto whitespace-pre-wrap">
              {record?.id === selected.id ? record.dossier : 'Loading…'}
            </pre>
          )}

          <section>
            <h4 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">{L.summary}</h4>
            <RichText text={selected.report.summary} />
          </section>

          <section>
            <h4 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">{L.facts}</h4>
            <EvidenceList items={selected.report.established_facts} record={citationText} unsupportedLabel={L.unsupported} />
          </section>

          <section className="space-y-2">
            <h4 className="text-xs uppercase tracking-wide text-neutral-500">{L.hypotheses}</h4>
            {selected.report.hypotheses.map((h, i) => <Hypothesis key={i} h={h} n={i + 1} record={citationText} L={L} />)}
          </section>

          <div className="grid md:grid-cols-2 gap-6">
            <section><h4 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">{L.gaps}</h4><PlainList items={selected.report.gaps} /></section>
            <section><h4 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">{L.next}</h4><PlainList items={selected.report.next_steps} /></section>
          </div>

          <section>
            <h4 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">{L.quality}</h4>
            <PlainList items={selected.report.data_quality_notes} />
          </section>
        </div>
      )}
    </div>
  )
}
