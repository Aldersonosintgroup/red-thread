import { useState } from 'react'
import { api, ApiError } from '../api/client'
import type { VaultStatus } from '../types'
import { TitleBar } from './TitleBar'

export function UnlockScreen({ status, onUnlocked }: { status: VaultStatus; onUnlocked: (s: VaultStatus) => void }) {
  const [mode, setMode] = useState<'passphrase' | 'recovery'>('passphrase')
  const [passphrase, setPassphrase] = useState('')
  const [recoveryKey, setRecoveryKey] = useState('')
  const [newPassphrase, setNewPassphrase] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    if (mode === 'recovery') {
      if (newPassphrase.length < status.min_passphrase_length) {
        setError(`The new passphrase must be at least ${status.min_passphrase_length} characters.`)
        return
      }
      if (newPassphrase !== confirm) {
        setError('The new passphrases do not match.')
        return
      }
    }
    setBusy(true)
    try {
      const next = await api.unlockVault(
        mode === 'passphrase' ? { passphrase } : { recovery_key: recoveryKey, new_passphrase: newPassphrase },
      )
      onUnlocked(next)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not unlock.')
      setPassphrase('')
    } finally {
      setBusy(false)
    }
  }

  const input = 'w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white focus:outline-none focus:border-red-700'

  return (
    <div className="flex flex-col h-screen bg-neutral-950">
      <TitleBar />
      <div className="flex-1 flex items-center justify-center px-6">
        <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
          <div className="text-center space-y-1">
            <div className="text-red-500 text-3xl">●</div>
            <h1 className="text-lg font-semibold text-white">The Red Thread is locked</h1>
            <p className="text-xs text-neutral-500">Case files are encrypted on this computer.</p>
          </div>

          {mode === 'passphrase' ? (
            <input
              type="password"
              autoFocus
              value={passphrase}
              onChange={(e) => setPassphrase(e.target.value)}
              placeholder="Passphrase"
              className={input}
              disabled={busy}
            />
          ) : (
            <div className="space-y-2">
              <input
                autoFocus
                value={recoveryKey}
                onChange={(e) => setRecoveryKey(e.target.value)}
                placeholder="Recovery key (XXXX-XXXX-…)"
                className={`${input} font-mono`}
                disabled={busy}
              />
              <input type="password" value={newPassphrase} onChange={(e) => setNewPassphrase(e.target.value)}
                placeholder="New passphrase" className={input} disabled={busy} />
              <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
                placeholder="Confirm new passphrase" className={input} disabled={busy} />
            </div>
          )}

          {error && <p className="text-red-400 text-xs">{error}</p>}

          <button
            type="submit"
            disabled={busy || (mode === 'passphrase' ? !passphrase : !recoveryKey)}
            className="w-full bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm font-medium py-2 rounded"
          >
            {busy ? 'Unlocking…' : 'Unlock'}
          </button>

          <button
            type="button"
            onClick={() => { setMode(mode === 'passphrase' ? 'recovery' : 'passphrase'); setError(null) }}
            className="w-full text-xs text-neutral-500 hover:text-neutral-300"
          >
            {mode === 'passphrase' ? 'Forgot the passphrase? Use your recovery key' : 'Back to passphrase'}
          </button>
        </form>
      </div>
    </div>
  )
}
