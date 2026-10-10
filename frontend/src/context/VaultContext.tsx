import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api, LOCKED_EVENT, retryOnStartup } from '../api/client'
import { TitleBar } from '../components/TitleBar'
import { UnlockScreen } from '../components/UnlockScreen'
import type { VaultStatus } from '../types'

interface VaultContextValue {
  status: VaultStatus
  refresh: () => Promise<void>
  lockNow: () => Promise<void>
}

const VaultContext = createContext<VaultContextValue | null>(null)

export function useVault(): VaultContextValue {
  const value = useContext(VaultContext)
  if (!value) throw new Error('useVault must be used inside VaultGate')
  return value
}

/** Renders the app only while the case data is readable. With encryption
 *  on and the vault locked (at launch, on "Lock", or after auto-lock), the
 *  whole app, case context included, is unmounted behind the unlock screen,
 *  so nothing from the previous session stays on screen or in memory. */
export function VaultGate({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<VaultStatus | null>(null)

  const refresh = useCallback(async () => {
    setStatus(await retryOnStartup(() => api.getVaultStatus()))
  }, [])

  const lockNow = useCallback(async () => {
    setStatus(await api.lockVault())
  }, [])

  useEffect(() => {
    refresh()
    const onLocked = () => setStatus((s) => (s ? { ...s, locked: true } : s))
    window.addEventListener(LOCKED_EVENT, onLocked)
    return () => window.removeEventListener(LOCKED_EVENT, onLocked)
  }, [refresh])

  if (!status) {
    return (
      <div className="flex flex-col h-screen bg-neutral-950">
        <TitleBar />
        <div className="flex-1 flex items-center justify-center text-neutral-500 text-sm">Starting…</div>
      </div>
    )
  }
  if (status.locked) {
    return <UnlockScreen status={status} onUnlocked={setStatus} />
  }
  return <VaultContext.Provider value={{ status, refresh, lockNow }}>{children}</VaultContext.Provider>
}
