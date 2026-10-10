import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { CategoryBadge } from '../components/Badge'
import type { WatchlistCategory, WatchlistEntityOut } from '../types'

export function WatchlistPage() {
  const [entities, setEntities] = useState<WatchlistEntityOut[]>([])
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [category, setCategory] = useState<WatchlistCategory>('YELLOW')
  const [entityType, setEntityType] = useState('')
  const [importResult, setImportResult] = useState<string | null>(null)

  async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setError(null)
    try {
      const result = await api.importWatchlist(file)
      setImportResult(
        `Imported ${result.added} entr${result.added === 1 ? 'y' : 'ies'}` +
          (result.skipped_existing ? `, skipped ${result.skipped_existing} already on the list` : '') +
          (result.invalid ? `, ignored ${result.invalid} invalid` : '') + '.',
      )
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Import failed.')
    }
  }

  async function load() {
    try {
      setEntities(await api.listWatchlist())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load watchlist.')
    }
  }

  useEffect(() => { load() }, [])

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault()
    if (!name.trim()) return
    try {
      await api.createWatchlistEntity({ name: name.trim(), aliases: [], category, entity_type: entityType.trim() || null, notes: null })
      setName('')
      setEntityType('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to add entity.')
    }
  }

  async function handleDelete(id: string) {
    try {
      await api.deleteWatchlistEntity(id)
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to delete entity.')
    }
  }

  const grouped: Record<WatchlistCategory, WatchlistEntityOut[]> = { RED: [], ORANGE: [], YELLOW: [] }
  for (const e of entities) grouped[e.category].push(e)

  return (
    <div className="max-w-3xl mx-auto py-10 px-6">
      <h2 className="text-xl font-semibold text-white mb-1">Investigated Entities</h2>
      <p className="text-neutral-500 text-sm mb-4">
        A private, local, user-editable watchlist of previously-investigated entities. Never
        published externally — used only for case-matching within this app.
      </p>
      <div className="flex items-center gap-4 mb-6 text-xs">
        <a href={api.watchlistExportUrl()} className="text-neutral-400 hover:text-white">Export list (JSON)</a>
        <label className="text-neutral-400 hover:text-white cursor-pointer">
          Import list…
          <input type="file" accept=".json,application/json" onChange={handleImport} className="hidden" />
        </label>
        {importResult && <span className="text-emerald-400">{importResult}</span>}
      </div>

      {error && <p className="text-red-400 text-sm mb-4">{error}</p>}

      <form onSubmit={handleAdd} className="flex gap-2 mb-6">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name" className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white" />
        <input value={entityType} onChange={(e) => setEntityType(e.target.value)} placeholder="Type (e.g. Attorney)" className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white" />
        <select value={category} onChange={(e) => setCategory(e.target.value as WatchlistCategory)} className="bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white">
          <option value="RED">RED</option>
          <option value="ORANGE">ORANGE</option>
          <option value="YELLOW">YELLOW</option>
        </select>
        <button type="submit" className="bg-red-700 hover:bg-red-600 text-white text-sm font-medium px-4 py-2 rounded">Add</button>
      </form>

      {(['RED', 'ORANGE', 'YELLOW'] as const).map((cat) => (
        <div key={cat} className="mb-6">
          <h3 className="text-sm font-medium text-neutral-400 mb-2 flex items-center gap-2">
            <CategoryBadge category={cat} /> Tier
          </h3>
          <div className="border border-neutral-800 rounded divide-y divide-neutral-800">
            {grouped[cat].length === 0 && <p className="text-neutral-600 text-sm p-3">None.</p>}
            {grouped[cat].map((entity) => (
              <div key={entity.id} className="px-3 py-2 flex items-center justify-between">
                <div>
                  <div className="text-sm text-neutral-200">{entity.name}</div>
                  <div className="text-xs text-neutral-500">{entity.entity_type ?? '—'}{entity.is_seed && ' · fictional sample'}</div>
                </div>
                <button onClick={() => handleDelete(entity.id)} className="text-xs text-neutral-500 hover:text-red-400">Remove</button>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
