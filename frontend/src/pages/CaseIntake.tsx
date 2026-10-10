import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { useCases } from '../context/CaseContext'

export function CaseIntake() {
  const navigate = useNavigate()
  const { refreshCases, selectCase } = useCases()

  const [caseNumber, setCaseNumber] = useState('')
  const [title, setTitle] = useState('')
  const [fullName, setFullName] = useState('')
  const [aliases, setAliases] = useState('')
  const [dob, setDob] = useState('')
  const [birthPlace, setBirthPlace] = useState('')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadingSample, setLoadingSample] = useState(false)

  async function handleLoadSample() {
    setLoadingSample(true)
    setError(null)
    try {
      const sample = await api.loadSampleCase()
      await refreshCases()
      selectCase(sample.id)
      navigate(`/cases/${sample.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load the sample case.')
    } finally {
      setLoadingSample(false)
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!caseNumber.trim() || !title.trim() || !fullName.trim()) {
      setError('Case number, case title, and subject full name are required.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const created = await api.createCase({
        case_number: caseNumber.trim(),
        title: title.trim(),
        subject: {
          full_name: fullName.trim(),
          aliases: aliases.split(',').map((a) => a.trim()).filter(Boolean),
          date_of_birth: dob || null,
          birth_place: birthPlace.trim() || null,
          notes: notes.trim() || null,
        },
      })
      await refreshCases()
      selectCase(created.id)
      navigate(`/cases/${created.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create case.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto py-10 px-6">
      <h2 className="text-xl font-semibold text-white mb-1">New Case — Subject Profile</h2>
      <p className="text-neutral-500 text-sm mb-6">
        This is required before any documents can be uploaded. The subject becomes the center
        node of the case's network map.
      </p>

      <div className="mb-6 border border-neutral-800 rounded px-4 py-3 flex items-center justify-between gap-4">
        <p className="text-xs text-neutral-500">
          Want to see how it works first? Load a fully fictional sample case with invented people, documents and dates.
        </p>
        <button
          type="button"
          onClick={handleLoadSample}
          disabled={loadingSample}
          className="shrink-0 text-xs bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50 text-white px-3 py-1.5 rounded"
        >
          {loadingSample ? 'Loading…' : 'Load sample case'}
        </button>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-neutral-400 mb-1">Case Number *</label>
            <input
              value={caseNumber}
              onChange={(e) => setCaseNumber(e.target.value)}
              className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white"
              placeholder="e.g. ADOP-1979-014"
            />
          </div>
          <div>
            <label className="block text-xs text-neutral-400 mb-1">Case Title *</label>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white"
              placeholder="e.g. Project Rivera"
            />
          </div>
        </div>

        <hr className="border-neutral-800" />

        <div>
          <label className="block text-xs text-neutral-400 mb-1">Subject Full Name *</label>
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white"
          />
        </div>

        <div>
          <label className="block text-xs text-neutral-400 mb-1">Known Aliases (comma-separated)</label>
          <input
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
            className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white"
          />
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-neutral-400 mb-1">Date of Birth</label>
            <input
              type="date"
              value={dob}
              onChange={(e) => setDob(e.target.value)}
              className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white"
            />
          </div>
          <div>
            <label className="block text-xs text-neutral-400 mb-1">Birth Place</label>
            <input
              value={birthPlace}
              onChange={(e) => setBirthPlace(e.target.value)}
              className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white"
            />
          </div>
        </div>

        <div>
          <label className="block text-xs text-neutral-400 mb-1">Notes</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white"
          />
        </div>

        {error && <p className="text-red-400 text-sm">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded"
        >
          {submitting ? 'Creating…' : 'Create Case'}
        </button>
      </form>
    </div>
  )
}
