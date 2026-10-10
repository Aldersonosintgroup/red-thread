import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Actor, DocumentOut, StatementIn, StatementOut } from '../types'
import { SeverityBadge } from './Badge'

const EMPTY: StatementIn = {
  kind: 'testimony', statement: '', source_name: '', source_relationship: '', statement_date: null, method: '',
  basis: 'unknown', status: 'unverified', relation: 'context', related_document_ids: [], related_actor_ids: [],
  flag_severity: null,
}

const TESTIMONY_METHODS = ['In-person interview', 'Phone call', 'Video call', 'Email', 'Letter', 'Sworn statement / affidavit', 'Recorded interview']
const FINDING_METHODS = ['DNA test', 'Civil registry search', 'Court records search', 'Comparison of documents', 'Public records search', 'Expert opinion']
const STATUS_STYLE: Record<string, string> = {
  verified: 'bg-emerald-900/60 text-emerald-200', corroborated: 'bg-sky-900/60 text-sky-200', unverified: 'bg-neutral-800 text-neutral-300',
}
const RELATION_TEXT: Record<string, string> = { supports: 'Supports', contradicts: 'Contradicts', context: 'Concerns' }

const field = 'w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white'
const label = 'block text-xs text-neutral-400 mb-1'

/** Testimony and verified findings: evidence that isn't a scanned document. */
export function StatementsPanel({ caseId, onChanged }: { caseId: string; onChanged?: () => void }) {
  const [statements, setStatements] = useState<StatementOut[]>([])
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [actors, setActors] = useState<Actor[]>([])
  const [draft, setDraft] = useState<StatementIn | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    try {
      const [s, d, a] = await Promise.all([api.listStatements(caseId), api.listDocuments(caseId), api.listActors(caseId)])
      setStatements(s)
      setDocuments([...d].sort((x, y) => x.upload_order - y.upload_order))
      setActors([...a].sort((x, y) => x.canonical_name.localeCompare(y.canonical_name)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load statements.')
    }
  }
  useEffect(() => { load() }, [caseId]) // eslint-disable-line react-hooks/exhaustive-deps

  const docName = useMemo(() => Object.fromEntries(documents.map((d) => [d.id, d.filename])), [documents])
  const actorName = useMemo(() => Object.fromEntries(actors.map((a) => [a.id, a.canonical_name])), [actors])

  function startNew(kind: 'testimony' | 'finding') {
    setEditingId(null)
    setDraft({ ...EMPTY, kind, status: kind === 'finding' ? 'verified' : 'unverified', source_name: kind === 'finding' ? 'Investigator' : '' })
    setError(null)
  }

  function startEdit(s: StatementOut) {
    setEditingId(s.id)
    setDraft({
      kind: s.kind, statement: s.statement, source_name: s.source_name ?? '', source_relationship: s.source_relationship ?? '',
      statement_date: s.statement_date, method: s.method ?? '', basis: s.basis ?? 'unknown', status: s.status,
      relation: s.relation, related_document_ids: s.related_document_ids, related_actor_ids: s.related_actor_ids,
      flag_severity: s.flag_severity,
    })
    setError(null)
  }

  async function save() {
    if (!draft || !draft.statement.trim()) { setError('Write the statement or finding first.'); return }
    setSaving(true)
    setError(null)
    try {
      const body = { ...draft, statement_date: draft.statement_date || null }
      if (editingId) await api.updateStatement(caseId, editingId, body)
      else await api.createStatement(caseId, body)
      setDraft(null)
      setEditingId(null)
      await load()
      onChanged?.()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save.')
    } finally {
      setSaving(false)
    }
  }

  async function remove(id: string) {
    try {
      await api.deleteStatement(caseId, id)
      setConfirmDelete(null)
      await load()
      onChanged?.()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not delete.')
    }
  }

  const set = <K extends keyof StatementIn>(key: K, value: StatementIn[K]) => setDraft((d) => (d ? { ...d, [key]: value } : d))
  const toggleIn = (key: 'related_document_ids' | 'related_actor_ids', id: string) =>
    setDraft((d) => {
      if (!d) return d
      const list = d[key].includes(id) ? d[key].filter((x) => x !== id) : [...d[key], id]
      return { ...d, [key]: list }
    })

  return (
    <div className="max-w-5xl space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <p className="text-sm text-neutral-400 max-w-2xl">
          Evidence that isn't a scanned document. <b className="text-neutral-200">Testimony</b> records what a person said
          (an adoptive parent, a relative, a former employee). A <b className="text-neutral-200">verified finding</b> records
          something you established yourself, and how (a DNA test, a registry search). Both are cited in the AI analysis
          and included in exports, and either can raise a flag.
        </p>
        <div className="flex gap-2 shrink-0">
          <button onClick={() => startNew('testimony')} className="bg-red-700 hover:bg-red-600 text-white text-sm px-3 py-2 rounded">+ Testimony</button>
          <button onClick={() => startNew('finding')} className="bg-neutral-800 hover:bg-neutral-700 text-white text-sm px-3 py-2 rounded">+ Verified finding</button>
        </div>
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {draft && (
        <div className="border border-neutral-700 rounded p-4 space-y-4 bg-neutral-950">
          <div className="flex items-center gap-3">
            <h3 className="text-white font-medium">
              {editingId ? 'Edit' : 'New'} {draft.kind === 'testimony' ? 'testimony' : 'verified finding'}
            </h3>
            <div className="flex border border-neutral-700 rounded overflow-hidden ml-auto text-xs">
              {(['testimony', 'finding'] as const).map((k) => (
                <button key={k} onClick={() => set('kind', k)}
                  className={`px-3 py-1 ${draft.kind === k ? 'bg-neutral-700 text-white' : 'text-neutral-400 hover:text-white'}`}>
                  {k === 'testimony' ? 'Testimony' : 'Verified finding'}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className={label}>{draft.kind === 'testimony' ? 'What did they say?' : 'What did you establish?'}</label>
            <textarea value={draft.statement} onChange={(e) => set('statement', e.target.value)} rows={3} className={field}
              placeholder={draft.kind === 'testimony'
                ? 'e.g. She said she knew at the time that the adoption was arranged through a black-market broker.'
                : 'e.g. DNA testing shows the woman named as the mother on the birth certificate is not the biological mother.'} />
            {draft.kind === 'testimony' && <p className="text-[11px] text-neutral-600 mt-1">Write it as close to their own words as you can. Quote directly where possible.</p>}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className={label}>{draft.kind === 'testimony' ? 'Who said it' : 'Verified by'}</label>
              <input value={draft.source_name ?? ''} onChange={(e) => set('source_name', e.target.value)} className={field}
                placeholder={draft.kind === 'testimony' ? 'Name' : 'Investigator, lab, agency…'} />
            </div>
            <div>
              <label className={label}>{draft.kind === 'testimony' ? 'Their relationship to the case' : 'Role'}</label>
              <input value={draft.source_relationship ?? ''} onChange={(e) => set('source_relationship', e.target.value)} className={field}
                placeholder={draft.kind === 'testimony' ? 'e.g. adoptive mother, birth sibling' : 'e.g. lead investigator'} />
            </div>
            <div>
              <label className={label}>{draft.kind === 'testimony' ? 'Date said' : 'Date verified'}</label>
              <input type="date" value={draft.statement_date ?? ''} onChange={(e) => set('statement_date', e.target.value || null)} className={field} />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className={label}>{draft.kind === 'testimony' ? 'How it was obtained' : 'How it was verified'}</label>
              <input list={`methods-${draft.kind}`} value={draft.method ?? ''} onChange={(e) => set('method', e.target.value)} className={field} placeholder="Choose or type" />
              <datalist id={`methods-${draft.kind}`}>
                {(draft.kind === 'testimony' ? TESTIMONY_METHODS : FINDING_METHODS).map((m) => <option key={m} value={m} />)}
              </datalist>
            </div>
            {draft.kind === 'testimony' && (
              <div>
                <label className={label}>Did they witness it themselves?</label>
                <select value={draft.basis ?? 'unknown'} onChange={(e) => set('basis', e.target.value as StatementIn['basis'])} className={field}>
                  <option value="firsthand">Yes, first-hand</option>
                  <option value="secondhand">No, they were told (second-hand)</option>
                  <option value="unknown">Not clear</option>
                </select>
              </div>
            )}
            <div>
              <label className={label}>Status</label>
              <select value={draft.status} onChange={(e) => set('status', e.target.value as StatementIn['status'])} className={field}>
                <option value="unverified">Unverified</option>
                <option value="corroborated">Corroborated by other evidence</option>
                <option value="verified">Verified</option>
              </select>
            </div>
          </div>

          {documents.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-1">
                <label className="text-xs text-neutral-400">Related documents</label>
                <select value={draft.relation} onChange={(e) => set('relation', e.target.value as StatementIn['relation'])}
                  className="bg-neutral-900 border border-neutral-700 rounded px-2 py-0.5 text-xs text-white">
                  <option value="context">this concerns</option>
                  <option value="supports">this supports</option>
                  <option value="contradicts">this contradicts</option>
                </select>
              </div>
              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                {documents.map((d) => (
                  <button key={d.id} onClick={() => toggleIn('related_document_ids', d.id)} title={d.filename}
                    className={`text-[11px] px-2 py-0.5 rounded border max-w-60 truncate ${draft.related_document_ids.includes(d.id) ? 'border-red-500 bg-red-950/40 text-white' : 'border-neutral-700 text-neutral-400 hover:text-white'}`}>
                    {d.filename}
                  </button>
                ))}
              </div>
            </div>
          )}

          {actors.length > 0 && (
            <div>
              <label className={label}>People or organizations it concerns</label>
              <div className="flex flex-wrap gap-1.5 max-h-28 overflow-y-auto">
                {actors.map((a) => (
                  <button key={a.id} onClick={() => toggleIn('related_actor_ids', a.id)}
                    className={`text-[11px] px-2 py-0.5 rounded border ${draft.related_actor_ids.includes(a.id) ? 'border-red-500 bg-red-950/40 text-white' : 'border-neutral-700 text-neutral-400 hover:text-white'}`}>
                    {a.canonical_name}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div>
            <label className={label}>Raise a flag?</label>
            <div className="flex flex-wrap gap-1.5">
              {([null, 'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'] as const).map((sev) => (
                <button key={sev ?? 'none'} onClick={() => set('flag_severity', sev)}
                  className={`text-xs px-2.5 py-1 rounded border ${draft.flag_severity === sev ? 'border-white text-white bg-neutral-800' : 'border-neutral-700 text-neutral-400 hover:text-white'}`}>
                  {sev ?? 'No flag'}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-neutral-600 mt-1">
              Shows in Flags &amp; Score marked as raised by you. It doesn't change the score, which is based on the documents alone.
            </p>
          </div>

          <div className="flex gap-2">
            <button onClick={save} disabled={saving} className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm px-4 py-2 rounded">
              {saving ? 'Saving…' : editingId ? 'Save changes' : 'Add to case'}
            </button>
            <button onClick={() => { setDraft(null); setEditingId(null) }} className="text-neutral-400 hover:text-white text-sm px-3">Cancel</button>
          </div>
        </div>
      )}

      {statements.length === 0 && !draft && (
        <p className="text-sm text-neutral-600">No testimony or findings recorded yet.</p>
      )}

      <div className="space-y-3">
        {statements.map((s) => (
          <div key={s.id} className="border border-neutral-800 rounded p-4">
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${s.kind === 'finding' ? 'bg-violet-900/60 text-violet-200' : 'bg-amber-900/50 text-amber-200'}`}>
                {s.kind === 'finding' ? 'VERIFIED FINDING' : 'TESTIMONY'}
              </span>
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${STATUS_STYLE[s.status]}`}>{s.status.toUpperCase()}</span>
              {s.flag_severity && <SeverityBadge severity={s.flag_severity} />}
              <div className="ml-auto flex gap-3 text-xs">
                <button onClick={() => startEdit(s)} className="text-neutral-400 hover:text-white">Edit</button>
                {confirmDelete === s.id ? (
                  <>
                    <button onClick={() => remove(s.id)} className="text-red-400 hover:text-red-300">Delete permanently</button>
                    <button onClick={() => setConfirmDelete(null)} className="text-neutral-400 hover:text-white">Keep</button>
                  </>
                ) : (
                  <button onClick={() => setConfirmDelete(s.id)} className="text-neutral-500 hover:text-red-400">Delete</button>
                )}
              </div>
            </div>
            <p className="text-sm text-neutral-100 whitespace-pre-wrap">{s.kind === 'testimony' ? `“${s.statement}”` : s.statement}</p>
            <p className="text-xs text-neutral-500 mt-2">
              {s.kind === 'testimony' ? 'Said by ' : 'Verified by '}
              <span className="text-neutral-300">{s.source_name || 'unnamed source'}</span>
              {s.source_relationship && <> ({s.source_relationship})</>}
              {s.statement_date && <> · {s.statement_date}</>}
              {s.method && <> · {s.method}</>}
              {s.kind === 'testimony' && s.basis && s.basis !== 'unknown' && <> · {s.basis === 'firsthand' ? 'first-hand' : 'second-hand'}</>}
            </p>
            {(s.related_document_ids.length > 0 || s.related_actor_ids.length > 0) && (
              <p className="text-xs text-neutral-500 mt-1">
                {s.related_document_ids.length > 0 && (
                  <>{RELATION_TEXT[s.relation]}: <span className={s.relation === 'contradicts' ? 'text-amber-300' : 'text-neutral-300'}>
                    {s.related_document_ids.map((id) => docName[id] ?? 'deleted document').join(', ')}</span></>
                )}
                {s.related_document_ids.length > 0 && s.related_actor_ids.length > 0 && ' · '}
                {s.related_actor_ids.length > 0 && <>About: <span className="text-neutral-300">{s.related_actor_ids.map((id) => actorName[id] ?? 'removed person').join(', ')}</span></>}
              </p>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
