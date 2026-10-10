import { useEffect, useState } from 'react'
import { api, ApiError } from '../api/client'
import { SecurityPanel } from '../components/SecurityPanel'
import type { AppSettings, AppSettingsUpdate } from '../types'

type ModelField = 'claude_vision_model' | 'gemini_vision_model' | 'openai_vision_model' | 'xai_model' | 'custom_model'
type KeyField = 'anthropic_api_key' | 'gemini_api_key' | 'openai_api_key' | 'xai_api_key' | 'custom_api_key'

interface ProviderInfo {
  label: string
  blurb: string
  keyField?: KeyField
  keyConfigured?: (s: AppSettings) => boolean
  modelField?: ModelField
  keyHelp?: string
}

const PROVIDERS: Record<string, ProviderInfo> = {
  claude: {
    label: 'Claude (Anthropic) — recommended, best accuracy on dense documents',
    blurb: 'Best results on handwriting, stamps and Spanish legal documents.',
    keyField: 'anthropic_api_key', keyConfigured: (s) => s.anthropic_key_configured, modelField: 'claude_vision_model',
    keyHelp: 'Get a key at console.anthropic.com',
  },
  grok: {
    label: 'Grok (xAI)',
    blurb: 'Use a model that accepts images (e.g. grok-4) so it can read scans.',
    keyField: 'xai_api_key', keyConfigured: (s) => s.xai_key_configured, modelField: 'xai_model',
    keyHelp: 'Get a key at console.x.ai',
  },
  openai: {
    label: 'OpenAI (ChatGPT models)',
    blurb: 'Use a model that accepts images (e.g. gpt-4o, gpt-4o-mini).',
    keyField: 'openai_api_key', keyConfigured: (s) => s.openai_key_configured, modelField: 'openai_vision_model',
    keyHelp: 'Get a key at platform.openai.com',
  },
  gemini: {
    label: 'Gemini (Google)',
    blurb: 'Use a model that accepts images (e.g. gemini-2.5-flash, gemini-2.5-pro).',
    keyField: 'gemini_api_key', keyConfigured: (s) => s.gemini_key_configured, modelField: 'gemini_vision_model',
    keyHelp: 'Get a key at aistudio.google.com',
  },
  custom: {
    label: 'Other AI (OpenRouter, Mistral, DeepSeek, Groq, local server…)',
    blurb: 'Any service that offers an OpenAI-compatible API. OpenRouter alone gives access to hundreds of models with one key.',
    keyField: 'custom_api_key', keyConfigured: (s) => s.custom_key_configured, modelField: 'custom_model',
    keyHelp: 'Leave blank for a local server that needs no key',
  },
  ollama: {
    label: 'Built-in local engine (free, offline, nothing leaves this computer)',
    blurb: 'Slower and less accurate than the cloud options, and cannot run the case analysis, but completely private.',
  },
}

const CUSTOM_PRESETS: [string, string][] = [
  ['OpenRouter', 'https://openrouter.ai/api/v1'],
  ['Mistral', 'https://api.mistral.ai/v1'],
  ['DeepSeek', 'https://api.deepseek.com/v1'],
  ['Groq', 'https://api.groq.com/openai/v1'],
  ['Together', 'https://api.together.xyz/v1'],
  ['LM Studio (this computer)', 'http://localhost:1234/v1'],
]

const inputClass = 'flex-1 min-w-0 bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white'
const buttonClass = 'bg-neutral-800 hover:bg-neutral-700 text-sm text-white px-3 rounded disabled:opacity-50'

export function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [keyDraft, setKeyDraft] = useState('')
  const [modelDraft, setModelDraft] = useState('')
  const [urlDraft, setUrlDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null)

  useEffect(() => {
    api.getSettings().then(setSettings).catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load settings.'))
  }, [])

  const provider = settings?.ai_provider ?? 'claude'
  const info = PROVIDERS[provider] ?? PROVIDERS.ollama

  // Show the selected provider's saved model and address when switching.
  useEffect(() => {
    if (!settings) return
    setKeyDraft('')
    setModelDraft(info.modelField ? settings[info.modelField] : '')
    setUrlDraft(settings.custom_base_url)
    setTestResult(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, settings?.custom_base_url])

  async function handleSave(patch: AppSettingsUpdate) {
    setError(null)
    try {
      const updated = await api.updateSettings(patch)
      setSettings(updated)
      setSaved(true)
      setTestResult(null)
      setTimeout(() => setSaved(false), 1500)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save settings.')
    }
  }

  async function handleTest() {
    setTesting(true)
    setTestResult(null)
    try {
      setTestResult(await api.testSettings())
    } catch (err) {
      setTestResult({ ok: false, message: err instanceof ApiError ? err.message : 'Test failed.' })
    } finally {
      setTesting(false)
    }
  }

  if (!settings) return <div className="p-6 text-neutral-500 text-sm">Loading…</div>

  return (
    <div className="max-w-xl mx-auto py-10 px-6 space-y-6">
      <h2 className="text-xl font-semibold text-white mb-1">Settings</h2>
      {error && <p className="text-red-400 text-sm">{error}</p>}
      {saved && <p className="text-emerald-400 text-sm">Saved.</p>}

      <div>
        <label className="block text-xs text-neutral-400 mb-1">AI provider</label>
        <select
          value={provider}
          onChange={(e) => handleSave({ ai_provider: e.target.value })}
          className="w-full bg-neutral-900 border border-neutral-700 rounded px-3 py-2 text-sm text-white"
        >
          {Object.entries(PROVIDERS).map(([value, p]) => <option key={value} value={value}>{p.label}</option>)}
        </select>
        <p className="text-neutral-600 text-xs mt-1">
          Used to read documents and to write the case analysis. If it fails, document reading falls back to the built-in
          local engine only. Documents are never sent to a provider you haven't selected.
        </p>
      </div>

      {provider !== 'ollama' && (
        <p className="text-xs text-amber-300 bg-amber-950/30 border border-amber-900 rounded px-3 py-2">
          With a cloud provider selected, each document image is sent to that provider over an encrypted connection to
          be read, under that provider's own terms. For investigations where nothing may leave this computer, choose the
          built-in local engine.
        </p>
      )}

      <div className="border border-neutral-800 rounded p-4 space-y-4">
        <p className="text-xs text-neutral-400">{info.blurb}</p>

        {provider === 'custom' && (
          <div>
            <label className="block text-xs text-neutral-400 mb-1">Service address (API base URL)</label>
            <div className="flex gap-2">
              <input value={urlDraft} onChange={(e) => setUrlDraft(e.target.value)} placeholder="https://openrouter.ai/api/v1" className={inputClass} />
              <button onClick={() => handleSave({ custom_base_url: urlDraft })} className={buttonClass}>Save</button>
            </div>
            <div className="flex flex-wrap gap-1.5 mt-2">
              {CUSTOM_PRESETS.map(([name, url]) => (
                <button key={name} onClick={() => { setUrlDraft(url); handleSave({ custom_base_url: url }) }}
                  className={`text-[11px] px-2 py-0.5 rounded border ${settings.custom_base_url === url ? 'border-neutral-400 text-white' : 'border-neutral-700 text-neutral-400 hover:text-white'}`}>
                  {name}
                </button>
              ))}
            </div>
          </div>
        )}

        {info.keyField && (
          <div>
            <label className="block text-xs text-neutral-400 mb-1">
              API key {info.keyConfigured?.(settings) && <span className="text-emerald-400">(saved)</span>}
            </label>
            <div className="flex gap-2">
              <input type="password" value={keyDraft} onChange={(e) => setKeyDraft(e.target.value)}
                placeholder="Stored on this computer only; never shown again" className={inputClass} />
              <button onClick={() => { handleSave({ [info.keyField!]: keyDraft }); setKeyDraft('') }} className={buttonClass}>Save</button>
            </div>
            {info.keyHelp && <p className="text-neutral-600 text-xs mt-1">{info.keyHelp}. Usage is billed by that provider.</p>}
          </div>
        )}

        {info.modelField && (
          <div>
            <label className="block text-xs text-neutral-400 mb-1">Model</label>
            <div className="flex gap-2">
              <input value={modelDraft} onChange={(e) => setModelDraft(e.target.value)}
                placeholder={provider === 'custom' ? 'e.g. openai/gpt-4o or mistral-medium-latest' : ''} className={inputClass} />
              <button onClick={() => handleSave({ [info.modelField!]: modelDraft })} className={buttonClass}>Save</button>
            </div>
            <p className="text-neutral-600 text-xs mt-1">The model must accept images to read scanned documents.</p>
          </div>
        )}

        {provider === 'ollama' && (
          <p className="text-neutral-600 text-xs">Model: {settings.ollama_vision_model}. No key, no internet needed.</p>
        )}

        <div className="flex items-center gap-3">
          <button onClick={handleTest} disabled={testing} className={buttonClass + ' py-1.5'}>
            {testing ? 'Testing…' : 'Test connection'}
          </button>
          {testResult && (
            <span className={`text-xs ${testResult.ok ? 'text-emerald-400' : 'text-red-400'}`}>{testResult.message}</span>
          )}
        </div>
        <p className="text-neutral-600 text-[11px]">The test sends one short message with no case data.</p>
      </div>

      <div className="pt-2">
        <h3 className="text-sm font-medium text-neutral-300 mb-2">Security</h3>
        <SecurityPanel />
      </div>

      <AboutSection />
    </div>
  )
}

const LEGAL_DOCS = { eula: ['License agreement', '/eula.txt'], notices: ['Third-party licenses', '/third-party-notices.txt'] } as const

function AboutSection() {
  const [open, setOpen] = useState<keyof typeof LEGAL_DOCS | null>(null)
  const [text, setText] = useState('')

  async function show(doc: keyof typeof LEGAL_DOCS) {
    if (open === doc) { setOpen(null); return }
    setOpen(doc)
    setText('Loading…')
    try {
      const resp = await fetch(LEGAL_DOCS[doc][1])
      setText(resp.ok ? await resp.text() : 'Could not load this document.')
    } catch {
      setText('Could not load this document.')
    }
  }

  return (
    <div className="pt-2">
      <h3 className="text-sm font-medium text-neutral-300 mb-2">About &amp; licenses</h3>
      <p className="text-xs text-neutral-400">
        The Red Thread {__APP_VERSION__} · © {new Date().getFullYear()} Alderson OSINT Group LLC. All rights reserved.
      </p>
      <p className="text-xs text-neutral-600 mt-1">
        An investigative aid, not legal advice. Built with open-source software including the Qwen3-VL model (Apache 2.0)
        and Ollama (MIT).
      </p>
      <div className="flex gap-2 mt-2">
        {(Object.keys(LEGAL_DOCS) as (keyof typeof LEGAL_DOCS)[]).map((doc) => (
          <button key={doc} onClick={() => show(doc)}
            className={`text-xs px-2.5 py-1 rounded border ${open === doc ? 'border-neutral-400 text-white' : 'border-neutral-700 text-neutral-400 hover:text-white'}`}>
            {LEGAL_DOCS[doc][0]}
          </button>
        ))}
      </div>
      {open && (
        <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-neutral-400 bg-neutral-950 border border-neutral-800 rounded p-3">
          {text}
        </pre>
      )}
    </div>
  )
}
