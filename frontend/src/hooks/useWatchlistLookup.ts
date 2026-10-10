import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { WatchlistEntityOut } from '../types'

export function useWatchlistLookup() {
  const [lookup, setLookup] = useState<Map<string, WatchlistEntityOut>>(new Map())

  useEffect(() => {
    let cancelled = false
    api.listWatchlist().then((entities) => {
      if (!cancelled) setLookup(new Map(entities.map((e) => [e.id, e])))
    }).catch(() => {
      /* non-critical: badges just won't show category colors */
    })
    return () => { cancelled = true }
  }, [])

  return lookup
}
