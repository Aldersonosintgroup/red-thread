import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { DiscrepancyGroup } from '../types'

export function DiscrepancyPanel({ caseId }: { caseId: string }) {
  const [groups, setGroups] = useState<DiscrepancyGroup[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.getDiscrepancies(caseId)
      .then((data) => { if (!cancelled) setGroups(data) })
      .catch((err) => { if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load discrepancies.') })
    return () => { cancelled = true }
  }, [caseId])

  if (error) return <p className="text-red-400 text-sm">{error}</p>
  if (groups.length === 0) return <p className="text-neutral-600 text-sm">No comparable fields recorded across documents yet.</p>

  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <div key={group.field} className={`border rounded p-3 ${group.is_contradictory ? 'border-red-800 bg-red-950/20' : 'border-neutral-800'}`}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-medium text-neutral-200 capitalize">{group.field.replace('_', ' ')}</h3>
            {group.is_contradictory && (
              <span className="text-xs text-red-300 bg-red-900/50 border border-red-700 rounded px-2 py-0.5">
                Contradiction
              </span>
            )}
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-neutral-500 text-xs">
                <th className="text-left font-normal py-1">Document</th>
                <th className="text-left font-normal py-1">Value</th>
              </tr>
            </thead>
            <tbody>
              {group.rows.map((row, i) => (
                <tr key={i} className="border-t border-neutral-800">
                  <td className="py-1 text-neutral-400">{row.document_filename}</td>
                  <td className="py-1 text-neutral-200">{row.value || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
