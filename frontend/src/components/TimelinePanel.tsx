import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { FlagOut, TimelineCleanupPlan, TimelineEventOut } from '../types'
import { SeverityBadge } from './Badge'

interface EventGroup {
  key: string
  event_type: string
  event_date: string | null
  events: TimelineEventOut[]
  excluded: boolean
}

const typeLabel = (t: string) => t.replace(/_/g, ' ')

/** Timeline with the same event from several documents shown as one row
 *  ("recorded in N documents"), expandable to each source. Noise can be
 *  excluded (kept on record, ignored by the flags) and a reviewed cleanup
 *  re-dates and re-labels events committed before the current rules. */
export function TimelinePanel({ caseId }: { caseId: string }) {
  const [events, setEvents] = useState<TimelineEventOut[]>([])
  const [loaded, setLoaded] = useState(false)
  const [flags, setFlags] = useState<FlagOut[]>([])
  const [docNames, setDocNames] = useState<Record<string, string>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [showExcluded, setShowExcluded] = useState(false)
  const [plan, setPlan] = useState<TimelineCleanupPlan | null>(null)
  const [applyRedate, setApplyRedate] = useState(true)
  const [applyRelabel, setApplyRelabel] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const [timeline, flagList, docs] = await Promise.all([
        api.getTimeline(caseId), api.getFlags(caseId), api.listDocuments(caseId),
      ])
      setEvents(timeline)
      setFlags(flagList.filter((f) => f.flag_type === 'TIMELINE_IRREGULARITY' || f.flag_type === 'PRE_BIRTH_PETITION_ANOMALY'))
      setDocNames(Object.fromEntries(docs.map((d) => [d.id, d.filename])))
      setLoaded(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load timeline.')
    }
  }, [caseId])

  useEffect(() => { load() }, [load])

  const groups = useMemo(() => {
    const byKey = new Map<string, EventGroup>()
    for (const e of events) {
      const key = `${e.event_type}|${e.event_date ?? ''}|${e.excluded}`
      const group = byKey.get(key) ?? { key, event_type: e.event_type, event_date: e.event_date, events: [], excluded: e.excluded }
      group.events.push(e)
      byKey.set(key, group)
    }
    // Undated events last; otherwise chronological.
    return [...byKey.values()].sort((a, b) =>
      (a.event_date ?? '9999') < (b.event_date ?? '9999') ? -1 : (a.event_date ?? '9999') > (b.event_date ?? '9999') ? 1 : 0)
  }, [events])

  const visibleGroups = groups.filter((g) => showExcluded || !g.excluded)
  const excludedCount = events.filter((e) => e.excluded).length

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  const setExcluded = (group: EventGroup, excluded: boolean) =>
    run(async () => {
      await api.setTimelineExcluded(caseId, group.events.map((e) => e.id), excluded)
      await load()
    })

  const openCleanup = () => run(async () => { setMessage(null); setPlan(await api.getTimelineCleanup(caseId)) })

  const applyCleanup = () =>
    run(async () => {
      const result = await api.runTimelineCleanup(caseId, { redate: applyRedate, relabel: applyRelabel })
      setPlan(null)
      setMessage(`Cleanup applied: ${result.redated} event(s) re-dated, ${result.relabelled} re-labelled. Flags and score recalculated.`)
      await load()
    })

  const toggle = (key: string) =>
    setExpanded((prev) => { const next = new Set(prev); if (next.has(key)) next.delete(key); else next.add(key); return next })

  return (
    <div className="space-y-4">
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {message && <p className="text-emerald-400 text-sm">{message}</p>}

      {flags.length > 0 && (
        <div className="space-y-2">
          {flags.map((f) => (
            <div key={f.id} className="border border-red-900 bg-red-950/30 rounded px-3 py-2">
              <div className="flex items-center gap-2 mb-1">
                <SeverityBadge severity={f.severity} />
                <span className="text-sm font-medium text-red-200">{f.title}</span>
              </div>
              <p className="text-xs text-neutral-400">{f.description}</p>
            </div>
          ))}
        </div>
      )}

      {!loaded && !error && <p className="text-neutral-500 text-sm">Loading timeline…</p>}
      {loaded && <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-neutral-500">
          {events.length} event(s) from committed documents, shown as {groups.filter((g) => !g.excluded).length} row(s).
          {excludedCount > 0 && ` ${excludedCount} excluded.`}
        </p>
        <div className="flex items-center gap-3 shrink-0">
          {excludedCount > 0 && (
            <label className="text-xs text-neutral-400 flex items-center gap-1.5">
              <input type="checkbox" checked={showExcluded} onChange={(e) => setShowExcluded(e.target.checked)} />
              Show excluded
            </label>
          )}
          <button onClick={openCleanup} disabled={busy}
            className="text-xs border border-neutral-700 rounded px-2.5 py-1 text-neutral-300 hover:text-white disabled:opacity-50">
            Clean up…
          </button>
        </div>
      </div>}

      {plan && (
        <div className="border border-amber-800 bg-amber-950/20 rounded p-4 space-y-3">
          <h3 className="text-sm font-semibold text-white">Timeline cleanup: review before applying</h3>
          <p className="text-xs text-neutral-400">Nothing is deleted. Documents and their extractions are unchanged; only how their events are dated and labelled on the timeline.</p>

          <label className="flex items-start gap-2 text-sm text-neutral-200">
            <input type="checkbox" className="mt-1" checked={applyRedate} onChange={(e) => setApplyRedate(e.target.checked)} disabled={!plan.redate.length} />
            <span>Re-date {plan.redate.length} undated event(s) whose date can now be read
              {plan.redate.length > 0 && (
                <ul className="mt-1 text-xs text-neutral-400 space-y-0.5">
                  {plan.redate.map((r) => <li key={r.id}>{r.description} → <b className="text-neutral-200">{r.new_date}</b>{r.note && <span className="text-amber-400"> ({r.note})</span>}</li>)}
                </ul>
              )}
            </span>
          </label>

          <label className="flex items-start gap-2 text-sm text-neutral-200">
            <input type="checkbox" className="mt-1" checked={applyRelabel} onChange={(e) => setApplyRelabel(e.target.checked)} disabled={!plan.relabel.length} />
            <span>Re-label {plan.relabel.length} event(s) filed as "other" that are births, petitions, decrees or payments
              {plan.relabel.length > 0 && (
                <ul className="mt-1 text-xs text-neutral-400 space-y-0.5">
                  {plan.relabel.map((r) => <li key={r.id}>{r.description} → <b className="text-neutral-200">{typeLabel(r.to_type)}</b></li>)}
                </ul>
              )}
              <span className="block text-xs text-amber-400 mt-1">Re-labelled births, petitions and decrees are checked by the timeline flags, so new flags may appear.</span>
            </span>
          </label>

          {plan.duplicate_groups.length > 0 && (
            <p className="text-xs text-neutral-400">
              Repeated events are already shown as single rows ({plan.duplicate_groups.map((g) => `${typeLabel(g.event_type)} ${g.event_date ?? 'undated'} ×${g.count}`).join(', ')}).
              To remove noise such as the issue date of certified copies, use <b className="text-neutral-200">Exclude</b> on that row.
            </p>
          )}

          <div className="flex gap-2">
            <button onClick={applyCleanup} disabled={busy || (!(applyRedate && plan.redate.length) && !(applyRelabel && plan.relabel.length))}
              className="bg-red-700 hover:bg-red-600 disabled:opacity-40 text-white text-sm px-4 py-1.5 rounded">
              Apply cleanup
            </button>
            <button onClick={() => setPlan(null)} className="text-sm text-neutral-400 hover:text-white px-3">Cancel</button>
          </div>
        </div>
      )}

      <div className="border border-neutral-800 rounded divide-y divide-neutral-800">
        {visibleGroups.length === 0 && <p className="text-neutral-600 text-sm p-3">No timeline events recorded yet.</p>}
        {visibleGroups.map((group) => {
          const count = group.events.length
          const open = expanded.has(group.key)
          const single = count === 1 ? group.events[0] : null
          return (
            <div key={group.key} className={group.excluded ? 'opacity-50' : ''}>
              <div className="px-3 py-2 flex items-center gap-4">
                <span className="text-xs text-neutral-500 w-24 shrink-0">{group.event_date ?? '—'}</span>
                <span className="text-xs uppercase text-neutral-400 w-32 shrink-0">{typeLabel(group.event_type)}</span>
                <span className="text-sm text-neutral-300 truncate flex-1 min-w-0">
                  {single ? single.description : (
                    <button onClick={() => toggle(group.key)} className="text-left hover:text-white">
                      {open ? '▾' : '▸'} Recorded in {count} documents
                      <span className="text-neutral-500"> · {group.events[0].description}</span>
                    </button>
                  )}
                </span>
                {group.excluded && <span className="text-[10px] uppercase text-neutral-500 shrink-0">excluded</span>}
                <button onClick={() => setExcluded(group, !group.excluded)} disabled={busy}
                  title={group.excluded ? 'Put back on the timeline' : 'Keep on record but leave out of the timeline and its flags'}
                  className="text-xs text-neutral-500 hover:text-neutral-200 shrink-0">
                  {group.excluded ? 'Include' : 'Exclude'}
                </button>
              </div>
              {(open || single) && (
                <div className={single ? 'px-3 pb-2 -mt-1' : 'px-3 pb-2 space-y-0.5'}>
                  {group.events.map((e) => (
                    <div key={e.id} className="text-xs text-neutral-500 pl-[17rem] truncate">
                      {!single && <span className="text-neutral-400">{e.description} · </span>}
                      {e.source_document_id ? docNames[e.source_document_id] ?? 'deleted document' : 'no source document'}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
