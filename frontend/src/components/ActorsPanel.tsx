import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { Actor, MergeSuggestion } from '../types'
import { CategoryBadge } from './Badge'
import { useWatchlistLookup } from '../hooks/useWatchlistLookup'

const SWATCHES = ['#ef4444', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899']

export function ActorsPanel({ caseId }: { caseId: string }) {
  const [actors, setActors] = useState<Actor[]>([])
  const [error, setError] = useState<string | null>(null)
  const [mergeSource, setMergeSource] = useState('')
  const [mergeTarget, setMergeTarget] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const watchlist = useWatchlistLookup()

  async function load() {
    try {
      setActors(await api.listActors(caseId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load actors.')
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

  async function handleMerge(sourceId?: string, targetId?: string) {
    const source = sourceId ?? mergeSource
    const target = targetId ?? mergeTarget
    if (!source || !target || source === target) return
    try {
      await api.mergeActors(caseId, source, target)
      setMergeSource('')
      setMergeTarget('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Merge failed.')
    }
  }

  async function handleSaveEdit(actor: Actor, patch: { canonical_name: string; role: string; notes: string; custom_color: string | null }) {
    try {
      await api.updateActor(caseId, actor.id, patch)
      setEditingId(null)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Update failed.')
    }
  }

  async function handleDelete(actor: Actor) {
    if (!confirm(`Remove "${actor.canonical_name}" from this case? This cannot be undone.`)) return
    try {
      await api.deleteActor(caseId, actor.id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed.')
    }
  }

  return (
    <div className="space-y-6">
      {error && <p className="text-red-400 text-sm">{error}</p>}

      <MergeSuggestionsPanel caseId={caseId} onResolved={load} />

      <div className="border border-neutral-800 rounded divide-y divide-neutral-800">
        {actors.map((actor) => {
          const watchlistEntity = actor.watchlist_match_id ? watchlist.get(actor.watchlist_match_id) : undefined
          return (
            <div key={actor.id} className="px-3 py-2">
              {editingId === actor.id ? (
                <InlineEditor actor={actor} onSave={handleSaveEdit} onCancel={() => setEditingId(null)} />
              ) : (
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    {actor.custom_color && (
                      <span className="inline-block w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: actor.custom_color }} />
                    )}
                    <div className="min-w-0">
                      <div className="text-sm text-neutral-200 flex items-center gap-2">
                        {actor.canonical_name}
                        {actor.is_subject && <span className="text-xs text-purple-300 bg-purple-900/40 border border-purple-700 rounded px-1.5">SUBJECT</span>}
                        {watchlistEntity && <CategoryBadge category={watchlistEntity.category} />}
                      </div>
                      <div className="text-xs text-neutral-500 truncate">
                        {actor.role ?? 'No role recorded'}
                        {actor.aliases.length > 0 && ` · aliases: ${actor.aliases.join(', ')}`}
                        {actor.notes && ` · ${actor.notes}`}
                      </div>
                    </div>
                  </div>
                  {!actor.is_subject && (
                    <div className="flex items-center gap-3 shrink-0">
                      <button onClick={() => setEditingId(actor.id)} className="text-xs text-neutral-400 hover:text-white">
                        Edit
                      </button>
                      <button onClick={() => handleDelete(actor)} className="text-xs text-neutral-500 hover:text-red-400">
                        Remove
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}
        {actors.length === 0 && <p className="text-neutral-600 text-sm p-3">No actors in this case yet.</p>}
      </div>

      <div className="border border-neutral-800 rounded p-3">
        <h3 className="text-sm font-medium text-neutral-300 mb-2">Merge Duplicate Actors</h3>
        <div className="flex gap-2 items-center">
          <select value={mergeSource} onChange={(e) => setMergeSource(e.target.value)} className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white flex-1">
            <option value="">Merge this…</option>
            {actors.map((a) => <option key={a.id} value={a.id}>{a.canonical_name}</option>)}
          </select>
          <span className="text-neutral-500 text-xs">into</span>
          <select value={mergeTarget} onChange={(e) => setMergeTarget(e.target.value)} className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white flex-1">
            <option value="">…this</option>
            {actors.map((a) => <option key={a.id} value={a.id}>{a.canonical_name}</option>)}
          </select>
          <button onClick={() => handleMerge()} className="bg-neutral-800 hover:bg-neutral-700 text-sm text-white px-3 py-1.5 rounded">
            Merge
          </button>
        </div>
      </div>
    </div>
  )
}

function MergeSuggestionsPanel({ caseId, onResolved }: { caseId: string; onResolved: () => void }) {
  const [suggestions, setSuggestions] = useState<MergeSuggestion[] | null>(null)
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const [error, setError] = useState<string | null>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

  async function load() {
    try {
      setSuggestions(await api.getMergeSuggestions(caseId))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load merge suggestions.')
    }
  }

  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId])

  const pairKey = (s: MergeSuggestion) => `${s.actor_a.id}:${s.actor_b.id}`
  const visible = (suggestions ?? []).filter((s) => !dismissed.has(pairKey(s)))

  async function accept(s: MergeSuggestion) {
    setBusyKey(pairKey(s))
    try {
      // Keep whichever name looks more complete (longer) as the target.
      const target = s.actor_a.canonical_name.length >= s.actor_b.canonical_name.length ? s.actor_a : s.actor_b
      const source = target.id === s.actor_a.id ? s.actor_b : s.actor_a
      await api.mergeActors(caseId, source.id, target.id)
      await load()
      onResolved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Merge failed.')
    } finally {
      setBusyKey(null)
    }
  }

  function reject(s: MergeSuggestion) {
    setDismissed((prev) => new Set(prev).add(pairKey(s)))
  }

  if (error) return <p className="text-red-400 text-sm">{error}</p>
  if (!suggestions || visible.length === 0) return null

  return (
    <div className="border border-amber-800 bg-amber-950/20 rounded p-3 space-y-2">
      <h3 className="text-sm font-medium text-amber-200">
        Possible Duplicates ({visible.length})
      </h3>
      <p className="text-xs text-neutral-500">
        Likely the same real-world entity, extracted with different spelling or word order. Review each — nothing merges without your confirmation.
      </p>
      <div className="space-y-1.5 pt-1">
        {visible.map((s) => (
          <div key={pairKey(s)} className="flex items-center justify-between gap-3 bg-neutral-900 border border-neutral-800 rounded px-3 py-2">
            <div className="text-sm text-neutral-200 min-w-0 truncate">
              <span>{s.actor_a.canonical_name}</span>
              <span className="text-neutral-600 mx-2">≈</span>
              <span>{s.actor_b.canonical_name}</span>
              <span className="text-neutral-600 ml-2 text-xs">({s.score.toFixed(0)}% match)</span>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <button
                onClick={() => accept(s)}
                disabled={busyKey === pairKey(s)}
                className="text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-50"
              >
                Merge
              </button>
              <button onClick={() => reject(s)} className="text-xs text-neutral-500 hover:text-neutral-300">
                Not a duplicate
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function InlineEditor({
  actor,
  onSave,
  onCancel,
}: {
  actor: Actor
  onSave: (actor: Actor, patch: { canonical_name: string; role: string; notes: string; custom_color: string | null }) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(actor.canonical_name)
  const [role, setRole] = useState(actor.role ?? '')
  const [notes, setNotes] = useState(actor.notes ?? '')
  const [color, setColor] = useState<string | null>(actor.custom_color)

  return (
    <div className="space-y-2">
      <div className="flex gap-2 items-center">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white" />
        <input value={role} onChange={(e) => setRole(e.target.value)} placeholder="Role" className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white" />
      </div>
      <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white" />
      <div className="flex items-center gap-2">
        <span className="text-xs text-neutral-500">Custom color:</span>
        <button
          onClick={() => setColor(null)}
          className={`w-5 h-5 rounded-full border-2 ${color === null ? 'border-white' : 'border-neutral-700'} bg-neutral-800`}
          title="None"
        />
        {SWATCHES.map((hex) => (
          <button
            key={hex}
            onClick={() => setColor(hex)}
            className={`w-5 h-5 rounded-full border-2 ${color === hex ? 'border-white' : 'border-transparent'}`}
            style={{ backgroundColor: hex }}
            title={hex}
          />
        ))}
        <div className="flex-1" />
        <button onClick={() => onSave(actor, { canonical_name: name, role, notes, custom_color: color ?? '' })} className="text-xs text-emerald-400 hover:text-emerald-300">Save</button>
        <button onClick={onCancel} className="text-xs text-neutral-500 hover:text-neutral-300">Cancel</button>
      </div>
    </div>
  )
}
