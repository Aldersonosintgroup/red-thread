import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { CategoryBadge } from '../components/Badge'
import { useCases } from '../context/CaseContext'
import type { RecurringActor, RecurringTier, SeparatedPair } from '../types'

const TIER_STYLES: Record<RecurringTier, string> = {
  confirmed: 'bg-emerald-900/50 text-emerald-300 border-emerald-700',
  strong: 'bg-blue-900/50 text-blue-300 border-blue-700',
  possible: 'bg-neutral-800 text-neutral-300 border-neutral-600',
}

const TIER_HELP: Record<RecurringTier, string> = {
  confirmed: 'You confirmed these are the same person.',
  strong: 'Full name agrees (accents, titles and surname initials aside), or the same name with the same role.',
  possible: 'Names are similar but not certain (a misspelling, or only two names in common). Check the documents.',
}

export function TierBadge({ tier }: { tier: RecurringTier }) {
  return (
    <span title={TIER_HELP[tier]} className={`inline-block px-2 py-0.5 rounded border text-xs font-medium ${TIER_STYLES[tier]}`}>
      {tier}
    </span>
  )
}

function span(first: string | null, last: string | null) {
  if (!first) return null
  const a = first.slice(0, 4)
  const b = (last ?? first).slice(0, 4)
  return a === b ? a : `${a}–${b}`
}

export function RecurringActorsPage() {
  const [clusters, setClusters] = useState<RecurringActor[] | null>(null)
  const [separated, setSeparated] = useState<SeparatedPair[]>([])
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState<Set<string>>(new Set())
  const [showPossible, setShowPossible] = useState(true)
  const { selectCase } = useCases()
  const navigate = useNavigate()

  async function load() {
    try {
      const [c, s] = await Promise.all([api.listRecurringActors(), api.listSeparatedPairs()])
      setClusters(c)
      setSeparated(s)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load recurring actors.')
    }
  }

  useEffect(() => { load() }, [])

  async function decide(payload: Parameters<typeof api.decideRecurring>[0]) {
    setError(null)
    try {
      await api.decideRecurring(payload)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save the decision.')
    }
  }

  async function undo(id: string) {
    try {
      await api.undoSeparation(id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not undo.')
    }
  }

  function toggle(id: string) {
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function openCase(caseId: string) {
    selectCase(caseId)
    navigate(`/cases/${caseId}`)
  }

  const visible = (clusters ?? []).filter((c) => showPossible || c.tier !== 'possible')

  return (
    <div className="max-w-4xl mx-auto py-10 px-6">
      <h2 className="text-xl font-semibold text-white mb-1">Recurring Actors</h2>
      <p className="text-neutral-500 text-sm mb-2">
        People and organizations named in more than one case. One case naming someone is an allegation; several
        unrelated families naming the same person is a pattern. Nothing here is merged automatically. Confirm a
        match, or separate anyone who is a different person.
      </p>
      <p className="text-neutral-600 text-xs mb-5">
        Each case may belong to a different client. This page shows only that a name recurs and where. Open a case
        to see its evidence.
      </p>

      <div className="flex items-center gap-4 mb-5 text-xs text-neutral-400">
        <label className="flex items-center gap-2 cursor-pointer">
          <input type="checkbox" checked={showPossible} onChange={(e) => setShowPossible(e.target.checked)} />
          Show possible matches
        </label>
        <span className="flex items-center gap-2">
          <TierBadge tier="confirmed" /> <TierBadge tier="strong" /> <TierBadge tier="possible" />
          <span className="text-neutral-600">hover for meaning</span>
        </span>
      </div>

      {error && <p className="text-red-400 text-sm mb-4">{error}</p>}
      {clusters === null && !error && <p className="text-neutral-500 text-sm">Comparing cases…</p>}
      {clusters !== null && visible.length === 0 && (
        <p className="text-neutral-600 text-sm border border-neutral-800 rounded p-4">
          No one appears in more than one case yet. Matches show up here as documents are committed across cases.
        </p>
      )}

      <div className="space-y-3">
        {visible.map((c) => {
          const isOpen = open.has(c.id)
          const dates = span(c.first_date, c.last_date)
          const allIds = c.members.map((m) => m.actor_id)
          return (
            <div key={c.id} className="border border-neutral-800 rounded">
              <button onClick={() => toggle(c.id)} className="w-full text-left px-4 py-3 hover:bg-neutral-900/60">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="text-neutral-500 text-xs w-3">{isOpen ? '▾' : '▸'}</span>
                  <span className="text-white font-medium">{c.name}</span>
                  <span className="text-red-400 text-sm font-semibold">{c.case_count} cases</span>
                  <TierBadge tier={c.tier} />
                  {c.watchlist_category && <CategoryBadge category={c.watchlist_category} />}
                  {c.has_conflict && (
                    <span className="text-amber-400 text-xs" title="You separated two of these, but they are still linked through another case. Open and separate the one that doesn't belong.">
                      ⚠ conflicting decisions
                    </span>
                  )}
                </div>
                <div className="text-xs text-neutral-500 mt-1 ml-6">
                  {c.roles.length > 0 ? c.roles.join(' / ') : 'role not recorded'}
                  {dates && ` · ${dates}`}
                  {c.variants.length > 1 && ` · written as: ${c.variants.join('; ')}`}
                </div>
              </button>

              {isOpen && (
                <div className="border-t border-neutral-800 px-4 py-3">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-xs text-neutral-500">
                        <th className="pb-2 font-normal">Case</th>
                        <th className="pb-2 font-normal">Name as recorded</th>
                        <th className="pb-2 font-normal">Role</th>
                        <th className="pb-2 font-normal">Docs</th>
                        <th className="pb-2 font-normal">Dates</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-neutral-900">
                      {c.members.map((m) => (
                        <tr key={m.actor_id} className="align-top">
                          <td className="py-2 pr-3">
                            <button onClick={() => openCase(m.case_id)} className="text-neutral-200 hover:text-white underline-offset-2 hover:underline">
                              {m.case_number}
                            </button>
                            <div className="text-xs text-neutral-600 truncate max-w-[12rem]">{m.case_title}</div>
                          </td>
                          <td className="py-2 pr-3 text-neutral-300">{m.name}</td>
                          <td className="py-2 pr-3 text-neutral-400">{m.role ?? '—'}</td>
                          <td className="py-2 pr-3 text-neutral-400">{m.document_count}</td>
                          <td className="py-2 pr-3 text-neutral-400">{span(m.first_date, m.last_date) ?? '—'}</td>
                          <td className="py-2 text-right">
                            <button
                              onClick={() => decide({ actor_ids: [m.actor_id], against: allIds.filter((id) => id !== m.actor_id), decision: 'rejected' })}
                              className="text-xs text-neutral-500 hover:text-red-400"
                              title="This one is a different person: remove from the group"
                            >
                              Not the same person
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="flex gap-3 mt-3">
                    {c.tier !== 'confirmed' && (
                      <button
                        onClick={() => decide({ actor_ids: allIds, decision: 'confirmed' })}
                        className="bg-emerald-800 hover:bg-emerald-700 text-white text-xs font-medium px-3 py-1.5 rounded"
                      >
                        Confirm: all the same person
                      </button>
                    )}
                    {c.tier === 'confirmed' && (
                      <button
                        onClick={() => decide({ actor_ids: allIds, decision: 'clear' })}
                        className="text-xs text-neutral-500 hover:text-neutral-200"
                      >
                        Undo confirmation
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {separated.length > 0 && (
        <div className="mt-10">
          <h3 className="text-sm font-medium text-neutral-400 mb-2">Marked as different people</h3>
          <div className="border border-neutral-800 rounded divide-y divide-neutral-800">
            {separated.map((s) => (
              <div key={s.id} className="px-3 py-2 flex items-center justify-between text-sm">
                <span className="text-neutral-400">
                  {s.a.name_key} <span className="text-neutral-600">({s.a.case_number})</span>
                  {' ≠ '}
                  {s.b.name_key} <span className="text-neutral-600">({s.b.case_number})</span>
                </span>
                <button onClick={() => undo(s.id)} className="text-xs text-neutral-500 hover:text-neutral-200">Undo</button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
