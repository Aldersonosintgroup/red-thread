import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, retryOnStartup } from '../api/client'
import type { CaseSummary } from '../types'

interface CaseContextValue {
  cases: CaseSummary[]
  selectedCaseId: string | null
  selectCase: (caseId: string | null) => void
  refreshCases: () => Promise<void>
  loading: boolean
  error: string | null
  connecting: boolean
}

const CaseContext = createContext<CaseContextValue | undefined>(undefined)

const STORAGE_KEY = 'redthread.selectedCaseId'

export function CaseProvider({ children }: { children: ReactNode }) {
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(
    () => localStorage.getItem(STORAGE_KEY),
  )
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [connecting, setConnecting] = useState(false)

  const refreshCases = useCallback(async () => {
    setLoading(true)
    setConnecting(true)
    const data = await retryOnStartup(
      () => api.listCases(),
      (err) =>
        setError(
          err instanceof Error
            ? `Still trying to reach the backend: ${err.message}`
            : 'Still trying to reach the backend — this is taking longer than usual.',
        ),
    )
    setCases(data)
    setError(null)
    setConnecting(false)
    setLoading(false)
  }, [])

  useEffect(() => {
    refreshCases()
  }, [refreshCases])

  const selectCase = useCallback((caseId: string | null) => {
    setSelectedCaseId(caseId)
    if (caseId) {
      localStorage.setItem(STORAGE_KEY, caseId)
    } else {
      localStorage.removeItem(STORAGE_KEY)
    }
  }, [])

  return (
    <CaseContext.Provider value={{ cases, selectedCaseId, selectCase, refreshCases, loading, error, connecting }}>
      {children}
    </CaseContext.Provider>
  )
}

export function useCases() {
  const ctx = useContext(CaseContext)
  if (!ctx) throw new Error('useCases must be used within CaseProvider')
  return ctx
}
