import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { useVault } from '../context/VaultContext'
import { useCases } from '../context/CaseContext'

export function Sidebar() {
  const { cases, selectedCaseId, selectCase, loading, error, connecting, refreshCases } = useCases()
  const navigate = useNavigate()
  const vault = useVault()
  const [loadingSample, setLoadingSample] = useState(false)
  const hasSample = cases.some((c) => c.case_number === 'SAMPLE-0001')

  async function openSampleCase() {
    setLoadingSample(true)
    try {
      const sample = await api.loadSampleCase()
      await refreshCases()
      selectCase(sample.id)
      navigate(`/cases/${sample.id}`)
    } finally {
      setLoadingSample(false)
    }
  }

  return (
    <aside className="w-64 shrink-0 bg-neutral-950 border-r border-neutral-800 flex flex-col h-full">
      <div className="p-4 border-b border-neutral-800">
        <h1 className="text-red-500 font-bold text-lg leading-tight">The Red Thread</h1>
        <p className="text-neutral-500 text-xs">El Hilo Rojo</p>
      </div>

      <div className="p-3">
        <button
          onClick={() => {
            selectCase(null)
            navigate('/intake')
          }}
          className="w-full bg-red-700 hover:bg-red-600 text-white text-sm font-medium py-2 rounded"
        >
          + New Case
        </button>
      </div>

      <div className="px-3 pb-2 text-xs uppercase tracking-wide text-neutral-500">Case History</div>
      <div className="flex-1 overflow-y-auto px-2 space-y-1">
        {loading && error && (
          <p className="text-amber-400 text-sm px-2">{error}</p>
        )}
        {loading && !error && (
          <p className="text-neutral-500 text-sm px-2">
            {connecting ? 'Starting backend…' : 'Loading…'}
          </p>
        )}
        {!loading && cases.length === 0 && (
          <p className="text-neutral-600 text-sm px-2">No cases yet.</p>
        )}
        {cases.map((c) => (
          <button
            key={c.id}
            onClick={() => {
              selectCase(c.id)
              navigate(`/cases/${c.id}`)
            }}
            className={`w-full text-left px-2 py-2 rounded text-sm transition ${
              selectedCaseId === c.id
                ? 'bg-neutral-800 text-white'
                : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'
            }`}
          >
            <div className="font-medium truncate">{c.title}</div>
            <div className="text-xs text-neutral-500 truncate">{c.case_number}</div>
          </button>
        ))}
      </div>

      <div className="p-3 border-t border-neutral-800">
        {!hasSample && (
          <button
            onClick={openSampleCase}
            disabled={loadingSample}
            title="A fully fictional case for demonstrations and training"
            className="w-full text-neutral-400 hover:text-neutral-200 disabled:opacity-50 text-sm py-1.5 text-left px-2"
          >
            {loadingSample ? 'Loading sample…' : 'Load sample case (demo)'}
          </button>
        )}
        <button
          onClick={() => navigate('/help')}
          className="w-full text-neutral-200 hover:text-white text-sm py-1.5 text-left px-2 font-medium"
        >
          ? Help &amp; guide
        </button>
        <button
          onClick={() => navigate('/watchlist')}
          className="w-full text-neutral-400 hover:text-neutral-200 text-sm py-1.5 text-left px-2"
        >
          Investigated Entities
        </button>
        <button
          onClick={() => navigate('/settings')}
          className="w-full text-neutral-400 hover:text-neutral-200 text-sm py-1.5 text-left px-2"
        >
          Settings
        </button>
        {vault.status.enabled && (
          <button
            onClick={() => vault.lockNow()}
            title="Lock the app now. The passphrase is needed to reopen case files."
            className="w-full text-neutral-400 hover:text-neutral-200 text-sm py-1.5 text-left px-2"
          >
            Lock
          </button>
        )}
      </div>
    </aside>
  )
}
