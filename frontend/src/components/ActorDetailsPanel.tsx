import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Actor, ActorDetails } from '../types'
import { SeverityBadge } from './Badge'

const SWATCHES = ['#dc2626', '#ea580c', '#ca8a04', '#16a34a', '#0891b2', '#2563eb', '#7c3aed', '#db2777', '#f8fafc', '#475569']
const TIER_STYLE: Record<string, string> = {
  RED: 'bg-red-900/60 text-red-200', ORANGE: 'bg-orange-900/60 text-orange-200', YELLOW: 'bg-yellow-900/60 text-yellow-200',
}

/** Side panel for one network-map node: who it is, where the reviewed
 *  record mentions them, the flags that concern them, and their color. */
export function ActorDetailsPanel({
  caseId,
  actorId,
  onColorChange,
  onClose,
}: {
  caseId: string
  actorId: string
  onColorChange: (actor: Actor) => void
  onClose: () => void
}) {
  const [details, setDetails] = useState<ActorDetails | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setDetails(null)
    setError(null)
    api.getActorDetails(caseId, actorId)
      .then(setDetails)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load details.'))
  }, [caseId, actorId])

  async function setColor(color: string) {
    setSaving(true)
    try {
      const updated = await api.updateActor(caseId, actorId, { custom_color: color })
      setDetails((d) => (d ? { ...d, actor: updated } : d))
      onColorChange(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the color.')
    } finally {
      setSaving(false)
    }
  }

  const actor = details?.actor
  const docCount = new Set(details?.appearances.map((a) => a.document_id)).size

  return (
    <aside className="absolute top-0 right-0 bottom-0 w-80 max-w-full bg-neutral-950/95 border-l border-neutral-800 flex flex-col z-10">
      <div className="flex items-start justify-between gap-2 px-4 py-3 border-b border-neutral-800">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-white break-words">{actor?.canonical_name ?? 'Loading…'}</h3>
          {actor && <p className="text-xs text-neutral-400">{actor.is_subject ? 'Subject of the case' : actor.role ?? 'No role recorded'}</p>}
        </div>
        <button onClick={onClose} className="text-neutral-500 hover:text-white text-sm" title="Close">✕</button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-5 text-sm">
        {error && <p className="text-red-400 text-xs">{error}</p>}

        {details?.watchlist && (
          <section>
            <h4 className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">Watchlist match</h4>
            <div className="flex items-center gap-2">
              <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded ${TIER_STYLE[details.watchlist.category]}`}>{details.watchlist.category}</span>
              <span className="text-neutral-200">{details.watchlist.name}</span>
            </div>
            <p className="text-xs text-neutral-500 mt-1">
              {details.watchlist.entity_type ?? 'Type not recorded'}
              {details.watchlist.score != null && ` · ${Math.round(details.watchlist.score)}% name match`}
            </p>
            {details.watchlist.notes && <p className="text-xs text-neutral-400 mt-1">{details.watchlist.notes}</p>}
          </section>
        )}

        {actor && actor.aliases.length > 0 && (
          <section>
            <h4 className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">Also written as</h4>
            <ul className="text-xs text-neutral-300 space-y-0.5">{actor.aliases.map((a) => <li key={a}>{a}</li>)}</ul>
          </section>
        )}

        {details && (
          <section>
            <h4 className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">
              In {docCount} reviewed document{docCount === 1 ? '' : 's'}
            </h4>
            {details.appearances.length === 0 ? (
              <p className="text-xs text-neutral-600">Not named in any committed document.</p>
            ) : (
              <ul className="space-y-1.5">
                {details.appearances.map((a, i) => (
                  <li key={i} className="text-xs">
                    <div className="text-neutral-200 truncate" title={a.filename}>{a.filename}{a.page ? ` · p.${a.page}` : ''}</div>
                    <div className="text-neutral-500">
                      {a.role ?? 'role not stated'}{a.doc_type ? ` · ${a.doc_type.replace(/_/g, ' ')}` : ''}
                      {actor && a.name_as_written !== actor.canonical_name && <> · written "{a.name_as_written}"</>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}

        {details && details.flags.length > 0 && (
          <section>
            <h4 className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">Flags</h4>
            <ul className="space-y-1.5">
              {details.flags.map((f) => (
                <li key={f.id} className="text-xs">
                  <div className="flex items-center gap-2"><SeverityBadge severity={f.severity} /><span className="text-neutral-200">{f.title}</span></div>
                  {f.description && <p className="text-neutral-500 mt-0.5">{f.description}</p>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {actor?.notes && (
          <section>
            <h4 className="text-[11px] uppercase tracking-wide text-neutral-500 mb-1">Notes</h4>
            <p className="text-xs text-neutral-300 whitespace-pre-wrap">{actor.notes}</p>
          </section>
        )}

        {actor && !actor.is_subject && (
          <section>
            <h4 className="text-[11px] uppercase tracking-wide text-neutral-500 mb-2">Color on the map</h4>
            <div className="flex flex-wrap gap-2 items-center">
              {SWATCHES.map((c) => (
                <button key={c} disabled={saving} onClick={() => setColor(c)} title={c}
                  className={`w-6 h-6 rounded-full border-2 ${actor.custom_color === c ? 'border-white' : 'border-neutral-800 hover:border-neutral-500'}`}
                  style={{ backgroundColor: c }} />
              ))}
              <label className="w-6 h-6 rounded-full border-2 border-dashed border-neutral-600 hover:border-neutral-400 cursor-pointer flex items-center justify-center text-neutral-400 text-xs" title="Any color">
                +
                <input type="color" className="sr-only" value={actor.custom_color ?? '#ffffff'} onChange={(e) => setColor(e.target.value)} />
              </label>
            </div>
            {actor.custom_color && (
              <button disabled={saving} onClick={() => setColor('')} className="text-xs text-neutral-500 hover:text-neutral-300 mt-2">
                Remove custom color
              </button>
            )}
            <p className="text-[11px] text-neutral-600 mt-2">Custom colors show in Custom mode. People without one keep their watchlist color there.</p>
          </section>
        )}
        {actor?.is_subject && <p className="text-[11px] text-neutral-600">The subject is always shown in purple at the center.</p>}
      </div>
    </aside>
  )
}
