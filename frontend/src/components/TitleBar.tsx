import { useEffect, useState } from 'react'

// Lazily resolved: the Tauri window API only exists when running inside the
// Tauri shell. In plain-browser dev (vite dev server opened directly) this
// stays null and the bar still renders, just without working controls.
type TauriWindow = {
  minimize: () => Promise<void>
  toggleMaximize: () => Promise<void>
  close: () => Promise<void>
  isMaximized: () => Promise<boolean>
  onResized: (cb: () => void) => Promise<() => void>
}

function useTauriWindow(): TauriWindow | null {
  const [win, setWin] = useState<TauriWindow | null>(null)
  useEffect(() => {
    let unlisten: (() => void) | undefined
    import('@tauri-apps/api/window')
      .then(({ getCurrentWindow }) => {
        const w = getCurrentWindow() as unknown as TauriWindow
        setWin(w)
      })
      .catch(() => setWin(null))
    return () => {
      unlisten?.()
    }
  }, [])
  return win
}

export function TitleBar() {
  const win = useTauriWindow()
  const [maximized, setMaximized] = useState(false)

  useEffect(() => {
    if (!win) return
    win.isMaximized().then(setMaximized).catch(() => {})
    let cleanup: (() => void) | undefined
    win.onResized(() => {
      win.isMaximized().then(setMaximized).catch(() => {})
    }).then((fn) => { cleanup = fn }).catch(() => {})
    return () => cleanup?.()
  }, [win])

  return (
    <div
      data-tauri-drag-region
      className="h-9 shrink-0 flex items-center justify-between bg-neutral-950 border-b border-neutral-800 select-none"
    >
      <div data-tauri-drag-region className="flex items-center gap-2 px-3 h-full flex-1">
        <span className="inline-block w-2.5 h-2.5 rounded-full bg-gradient-to-br from-red-500 to-red-900 shrink-0" />
        <span className="text-xs font-semibold text-neutral-200 tracking-wide">THE RED THREAD</span>
        <span className="text-[10px] text-neutral-600">|</span>
        <span className="text-[10px] text-neutral-500">Alderson OSINT Group LLC</span>
      </div>
      <div className="flex items-stretch h-full">
        <TitleBarButton label="Minimize" onClick={() => win?.minimize()}>
          <svg width="10" height="10" viewBox="0 0 10 10"><rect x="0" y="4.5" width="10" height="1" fill="currentColor" /></svg>
        </TitleBarButton>
        <TitleBarButton label={maximized ? 'Restore' : 'Maximize'} onClick={() => win?.toggleMaximize()}>
          <svg width="10" height="10" viewBox="0 0 10 10"><rect x="0.5" y="0.5" width="9" height="9" fill="none" stroke="currentColor" /></svg>
        </TitleBarButton>
        <TitleBarButton label="Close" danger onClick={() => win?.close()}>
          <svg width="10" height="10" viewBox="0 0 10 10">
            <line x1="0" y1="0" x2="10" y2="10" stroke="currentColor" />
            <line x1="10" y1="0" x2="0" y2="10" stroke="currentColor" />
          </svg>
        </TitleBarButton>
      </div>
    </div>
  )
}

function TitleBarButton({
  children,
  onClick,
  label,
  danger,
}: {
  children: React.ReactNode
  onClick: () => void
  label: string
  danger?: boolean
}) {
  return (
    <button
      aria-label={label}
      onClick={onClick}
      className={`w-11 h-full flex items-center justify-center text-neutral-400 transition-colors ${
        danger ? 'hover:bg-red-700 hover:text-white' : 'hover:bg-neutral-800 hover:text-neutral-100'
      }`}
    >
      {children}
    </button>
  )
}
