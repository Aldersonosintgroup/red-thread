import { useState } from 'react'
import { api, ApiError } from '../api/client'

export function NotesPanel({ caseId, initialNotes }: { caseId: string; initialNotes: string | null }) {
  const [notes, setNotes] = useState(initialNotes ?? '')
  const [saving, setSaving] = useState(false)
  const [savedAt, setSavedAt] = useState<Date | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      await api.updateCase(caseId, { notes })
      setSavedAt(new Date())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save notes.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="max-w-3xl space-y-3">
      <p className="text-neutral-500 text-sm">
        Free-form working notes for this case — hypotheses, leads to follow up, context that doesn't fit
        the structured fields elsewhere. Private to this case, not included in exports unless you copy it in.
      </p>
      <textarea
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        onBlur={handleSave}
        rows={20}
        placeholder="Start typing…"
        className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white leading-relaxed resize-y"
      />
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={saving}
          className="bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50 text-sm text-white px-3 py-1.5 rounded"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {savedAt && !saving && (
          <span className="text-xs text-neutral-500">Saved {savedAt.toLocaleTimeString()}</span>
        )}
        {error && <span className="text-xs text-red-400">{error}</span>}
      </div>
    </div>
  )
}
