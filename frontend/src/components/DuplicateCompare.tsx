import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DocumentOut, DuplicateDocumentSuggestion } from '../types'

type Zoom = 'fit' | 0.5 | 1

function Pane({ caseId, doc, side, zoom }: { caseId: string; doc: DocumentOut; side: string; zoom: Zoom }) {
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)
  const extraction = doc.edited_extraction ?? doc.raw_extraction
  const names = extraction?.names.map((n) => n.name) ?? []
  const dates = extraction?.dates.map((d) => d.date ?? d.raw ?? '').filter(Boolean) ?? []

  return (
    <div className="flex-1 min-w-0 flex flex-col border border-neutral-800 rounded overflow-hidden">
      <div className="px-3 py-2 bg-neutral-900 border-b border-neutral-800 space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="text-[10px] uppercase tracking-wider text-neutral-500">{side}</span>
          <span className="text-sm text-white truncate">{doc.filename}</span>
          {doc.committed
            ? <span className="ml-auto text-[10px] uppercase bg-purple-900/60 text-purple-200 px-1.5 py-0.5 rounded shrink-0">reviewed</span>
            : <span className="ml-auto text-[10px] uppercase bg-neutral-800 text-neutral-400 px-1.5 py-0.5 rounded shrink-0">{doc.status}</span>}
        </div>
        <div className="text-xs text-neutral-500">
          Upload #{doc.upload_order + 1} · {new Date(doc.uploaded_at).toLocaleString()}
          {natural && ` · ${natural.w}×${natural.h}px`}
        </div>
        <div className="text-xs text-neutral-400 truncate">
          {extraction
            ? `${extraction.doc_type ?? 'unknown type'} · ${names.length} name(s)${names.length ? ': ' + names.slice(0, 3).join(', ') : ''}${names.length > 3 ? '…' : ''} · ${dates.length} date(s)${dates.length ? ': ' + dates.slice(0, 3).join(', ') : ''}`
            : 'Not read yet'}
        </div>
      </div>
      {zoom === 'fit' || !natural ? (
        // Fit: the image is sized by the pane itself, whole page visible.
        <div className="flex-1 min-h-0 bg-black p-2">
          <img
            src={api.documentFileUrl(caseId, doc.id)}
            onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            alt={doc.filename}
            className="w-full h-full object-contain"
          />
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-auto bg-black">
          <div className="min-w-full min-h-full w-max grid place-items-center p-2">
            <img
              src={api.documentFileUrl(caseId, doc.id)}
              alt={doc.filename}
              className="max-w-none"
              style={{ width: natural.w * zoom, height: natural.h * zoom }}
            />
          </div>
        </div>
      )}
    </div>
  )
}

/** Side-by-side check of a suspected duplicate pair. The only path to
 *  deleting a copy, and deletion takes a second, explicit click. */
export function DuplicateCompare({
  caseId,
  pair,
  onDelete,
  onNotDuplicates,
  onClose,
}: {
  caseId: string
  pair: DuplicateDocumentSuggestion
  onDelete: (documentId: string) => Promise<void>
  onNotDuplicates: () => void
  onClose: () => void
}) {
  const [zoom, setZoom] = useState<Zoom>('fit')
  const [pending, setPending] = useState<DocumentOut | null>(null)
  const [busy, setBusy] = useState(false)
  const { document_a: left, document_b: right } = pair

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  async function confirmDelete() {
    if (!pending) return
    setBusy(true)
    try {
      await onDelete(pending.id)
    } finally {
      setBusy(false)
    }
  }

  const zoomButton = (value: Zoom, label: string) => (
    <button onClick={() => setZoom(value)}
      className={`text-xs px-2 py-1 rounded ${zoom === value ? 'bg-neutral-700 text-white' : 'text-neutral-400 hover:text-white'}`}>
      {label}
    </button>
  )

  return (
    <div className="fixed inset-0 z-50 bg-black/80 flex flex-col p-4 gap-3" role="dialog" aria-modal="true">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-white font-semibold text-sm">Compare possible duplicates</h2>
          <p className="text-xs text-neutral-400">
            Visual similarity: {pair.distance === 0 ? 'pixel-identical' : `very close (difference ${pair.distance} of 64)`}. Check both before deleting either.
          </p>
        </div>
        <div className="flex items-center gap-1">
          {zoomButton('fit', 'Fit')}
          {zoomButton(0.5, '50%')}
          {zoomButton(1, '100%')}
          <button onClick={onClose} className="ml-3 text-neutral-400 hover:text-white text-sm px-2" title="Close (Esc)">✕</button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex gap-3">
        <Pane caseId={caseId} doc={left} side="Left" zoom={zoom} />
        <Pane caseId={caseId} doc={right} side="Right" zoom={zoom} />
      </div>

      {pending ? (
        <div className="border border-red-800 bg-red-950/40 rounded px-4 py-3 flex items-center gap-4">
          <p className="text-sm text-red-100 flex-1">
            Delete <b>{pending.filename}</b> permanently?
            {pending.committed && ' It has been reviewed: its timeline events and network links will be removed from the case.'}
          </p>
          <button onClick={confirmDelete} disabled={busy}
            className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm px-4 py-1.5 rounded shrink-0">
            {busy ? 'Deleting…' : 'Delete this copy'}
          </button>
          <button onClick={() => setPending(null)} className="text-sm text-neutral-300 hover:text-white shrink-0">Cancel</button>
        </div>
      ) : (
        <div className="flex items-center gap-2 justify-center flex-wrap">
          <button onClick={() => setPending(right)} className="text-sm bg-neutral-800 hover:bg-neutral-700 text-white px-4 py-1.5 rounded">
            Keep left · delete right
          </button>
          <button onClick={() => setPending(left)} className="text-sm bg-neutral-800 hover:bg-neutral-700 text-white px-4 py-1.5 rounded">
            Keep right · delete left
          </button>
          <button onClick={onNotDuplicates} className="text-sm text-neutral-300 hover:text-white border border-neutral-700 px-4 py-1.5 rounded">
            Not duplicates: keep both
          </button>
        </div>
      )}
    </div>
  )
}
