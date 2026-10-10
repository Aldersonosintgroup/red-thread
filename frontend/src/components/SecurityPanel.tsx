import { useState } from 'react'
import { api, ApiError } from '../api/client'
import { useVault } from '../context/VaultContext'

const AUTO_LOCK_OPTIONS = [
  { minutes: 5, label: '5 minutes' },
  { minutes: 15, label: '15 minutes' },
  { minutes: 30, label: '30 minutes' },
  { minutes: 60, label: '1 hour' },
  { minutes: 0, label: 'Never' },
]

const input = 'w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white'

export function SecurityPanel() {
  const { status, refresh, lockNow } = useVault()
  const [passphrase, setPassphrase] = useState('')
  const [confirm, setConfirm] = useState('')
  const [currentPass, setCurrentPass] = useState('')
  const [newPass, setNewPass] = useState('')
  const [newConfirm, setNewConfirm] = useState('')
  const [recoveryKey, setRecoveryKey] = useState<string | null>(null)
  const [savedKey, setSavedKey] = useState(false)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const min = status.min_passphrase_length

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      await action()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
    } finally {
      setBusy(false)
    }
  }

  function handleEnable(e: React.FormEvent) {
    e.preventDefault()
    if (passphrase.length < min) return setError(`Use at least ${min} characters.`)
    if (passphrase !== confirm) return setError('The passphrases do not match.')
    run(async () => {
      const result = await api.enableEncryption(passphrase)
      setPassphrase('')
      setConfirm('')
      setRecoveryKey(result.recovery_key)
      const removed = result.removed_plaintext_copies.length
      setMessage(
        `Encrypted the database and ${result.files_encrypted} evidence file(s)` +
          (removed ? `, and securely deleted ${removed} unencrypted backup copy(ies) the app had kept.` : '.'),
      )
    })
  }

  function handleChange(e: React.FormEvent) {
    e.preventDefault()
    if (newPass.length < min) return setError(`Use at least ${min} characters.`)
    if (newPass !== newConfirm) return setError('The new passphrases do not match.')
    run(async () => {
      await api.changePassphrase(currentPass, newPass)
      setCurrentPass('')
      setNewPass('')
      setNewConfirm('')
      setMessage('Passphrase changed. Your recovery key still works.')
    })
  }

  // Shown once, right after encryption is turned on. Never retrievable later.
  if (recoveryKey) {
    return (
      <section className="border border-amber-800 bg-amber-950/20 rounded p-4 space-y-3">
        <h3 className="text-sm font-semibold text-white">Save your recovery key</h3>
        {message && <p className="text-emerald-400 text-xs">{message}</p>}
        <p className="text-xs text-neutral-300">
          If you forget your passphrase, this key is the <b>only</b> way back into your case files. It will not be
          shown again. Write it down or store it in a password manager, somewhere other than this computer.
        </p>
        <div className="font-mono text-base text-white bg-neutral-950 border border-neutral-700 rounded px-3 py-3 text-center tracking-wider select-all break-all">
          {recoveryKey}
        </div>
        <button
          onClick={() => navigator.clipboard.writeText(recoveryKey).then(() => setCopied(true)).catch(() => setCopied(false))}
          className="text-xs text-neutral-400 hover:text-white"
        >
          {copied ? 'Copied' : 'Copy to clipboard'}
        </button>
        <label className="flex items-center gap-2 text-xs text-neutral-300">
          <input type="checkbox" checked={savedKey} onChange={(e) => setSavedKey(e.target.checked)} />
          I have stored this recovery key somewhere safe.
        </label>
        <button
          disabled={!savedKey}
          onClick={async () => { setRecoveryKey(null); await refresh() }}
          className="bg-red-700 hover:bg-red-600 disabled:opacity-40 text-white text-sm px-4 py-2 rounded"
        >
          Done
        </button>
      </section>
    )
  }

  if (!status.enabled) {
    return (
      <section className="border border-neutral-800 rounded p-4 space-y-3">
        <h3 className="text-sm font-semibold text-white">Encryption: off</h3>
        <p className="text-xs text-neutral-400">
          Encrypts the case database, every uploaded document, and your saved API keys with AES-256 on this computer.
          The app will then open on a lock screen and lock itself when idle. Anyone who copies the files without your
          passphrase sees only scrambled data.
        </p>
        <p className="text-xs text-amber-400">
          There is no back door: if you lose both the passphrase and the recovery key, the case files cannot be recovered.
        </p>
        <form onSubmit={handleEnable} className="space-y-2">
          <input type="password" value={passphrase} onChange={(e) => setPassphrase(e.target.value)}
            placeholder={`Passphrase (at least ${min} characters)`} className={input} disabled={busy} />
          <input type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
            placeholder="Confirm passphrase" className={input} disabled={busy} />
          {error && <p className="text-red-400 text-xs">{error}</p>}
          <button type="submit" disabled={busy || !passphrase}
            className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm px-4 py-2 rounded">
            {busy ? 'Encrypting case files… this can take a minute' : 'Turn on encryption'}
          </button>
        </form>
      </section>
    )
  }

  return (
    <section className="border border-neutral-800 rounded p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Encryption: <span className="text-emerald-400">on</span></h3>
        <button onClick={() => run(lockNow)} className="text-xs bg-neutral-800 hover:bg-neutral-700 text-white px-3 py-1.5 rounded">
          Lock now
        </button>
      </div>
      <p className="text-xs text-neutral-500">Database, evidence files and API keys are encrypted with AES-256.</p>
      {message && <p className="text-emerald-400 text-xs">{message}</p>}
      {error && <p className="text-red-400 text-xs">{error}</p>}

      <div>
        <label className="block text-xs text-neutral-400 mb-1">Lock automatically after inactivity</label>
        <select
          value={status.auto_lock_minutes}
          onChange={(e) => run(async () => { await api.setAutoLock(Number(e.target.value)); await refresh() })}
          className={input}
        >
          {AUTO_LOCK_OPTIONS.map((o) => <option key={o.minutes} value={o.minutes}>{o.label}</option>)}
        </select>
      </div>

      <form onSubmit={handleChange} className="space-y-2">
        <label className="block text-xs text-neutral-400">Change passphrase</label>
        <input type="password" value={currentPass} onChange={(e) => setCurrentPass(e.target.value)}
          placeholder="Current passphrase" className={input} disabled={busy} />
        <input type="password" value={newPass} onChange={(e) => setNewPass(e.target.value)}
          placeholder={`New passphrase (at least ${min} characters)`} className={input} disabled={busy} />
        <input type="password" value={newConfirm} onChange={(e) => setNewConfirm(e.target.value)}
          placeholder="Confirm new passphrase" className={input} disabled={busy} />
        <button type="submit" disabled={busy || !currentPass || !newPass}
          className="bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50 text-white text-sm px-4 py-2 rounded">
          Change passphrase
        </button>
      </form>
    </section>
  )
}
