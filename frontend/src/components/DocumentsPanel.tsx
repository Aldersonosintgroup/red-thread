import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { StatusBadge } from './Badge'
import { DuplicateCompare } from './DuplicateCompare'
import type { DocumentOut, DuplicateDocumentSuggestion, ExtractionResult } from '../types'

const ALLOWED_TYPES = ['.jpg', '.jpeg', '.png', '.pdf']

export function DocumentsPanel({ caseId, onCommitted }: { caseId: string; onCommitted: () => void }) {
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [confirmRereadAll, setConfirmRereadAll] = useState(false)
  const [rereading, setRereading] = useState(false)
  const [pdfPage, setPdfPage] = useState<{ docId: string; page: number } | null>(null)
  const [selectedForBulk, setSelectedForBulk] = useState<Set<string>>(new Set())
  const [bulkMode, setBulkMode] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [refreshToken, setRefreshToken] = useState(0)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const pollRef = useRef<number | null>(null)

  const refresh = useCallback(async (): Promise<DocumentOut[] | null> => {
    try {
      const docs = await api.listDocuments(caseId)
      setDocuments(docs)
      return docs
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load documents.')
      return null
    }
  }, [caseId])

  useEffect(() => {
    refresh()
  }, [refresh])

  // Poll while anything is pending/processing so status badges update live.
  useEffect(() => {
    const hasActive = documents.some((d) => d.status === 'pending' || d.status === 'processing')
    if (hasActive && pollRef.current === null) {
      pollRef.current = window.setInterval(refresh, 2500)
    } else if (!hasActive && pollRef.current !== null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
    return () => {
      if (pollRef.current !== null) {
        window.clearInterval(pollRef.current)
        pollRef.current = null
      }
    }
  }, [documents, refresh])

  async function handleFiles(files: FileList | null) {
    if (!files || files.length === 0) return
    setError(null)
    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const ext = '.' + (file.name.split('.').pop() ?? '').toLowerCase()
        if (!ALLOWED_TYPES.includes(ext)) {
          setError(`Skipped "${file.name}": unsupported file type.`)
          continue
        }
        try {
          await api.uploadDocument(caseId, file)
        } catch (err) {
          setError(err instanceof ApiError ? err.message : `Upload failed for "${file.name}".`)
        }
      }
      await refresh()
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleManualEntry() {
    const label = window.prompt('Label this entry (e.g. "Phone call with the notary, 2026-01-15"):')
    if (!label || !label.trim()) return
    setError(null)
    try {
      const doc = await api.createManualDocument(caseId, label.trim())
      await refresh()
      setSelectedId(doc.id)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create manual entry.')
    }
  }

  async function handleDelete(doc: DocumentOut, e: React.MouseEvent) {
    e.stopPropagation()
    if (!confirm(`Delete "${doc.filename}"? This removes it from the case${doc.committed ? ' and retracts the timeline events / connections it contributed' : ''}.`)) return
    try {
      await api.deleteDocument(caseId, doc.id)
      if (selectedId === doc.id) setSelectedId(null)
      await refresh()
      onCommitted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed.')
    }
  }

  async function handleBulkDelete() {
    if (selectedForBulk.size === 0) return
    if (!confirm(`Delete ${selectedForBulk.size} selected document(s)? This cannot be undone.`)) return
    setError(null)
    for (const id of selectedForBulk) {
      try {
        await api.deleteDocument(caseId, id)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Some deletions failed.')
      }
    }
    setSelectedForBulk(new Set())
    setBulkMode(false)
    await refresh()
    onCommitted()
  }

  function toggleBulk(id: string) {
    setSelectedForBulk((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const selectedDoc = documents.find((d) => d.id === selectedId) ?? null

  // Documents read and waiting for the investigator's review, in upload order.
  const awaitingReview = (docs: DocumentOut[]) =>
    docs
      .filter((d) => !d.committed && (d.status === 'extracted' || d.status === 'error'))
      .sort((a, b) => a.upload_order - b.upload_order)
  const reviewRemaining = awaitingReview(documents).length

  /** After committing, open the next document still awaiting review: the
   *  next one after this in upload order, else the first remaining. */
  async function commitAndNext(currentId: string) {
    const fresh = (await refresh()) ?? documents
    onCommitted()
    const current = fresh.find((d) => d.id === currentId)
    const queue = awaitingReview(fresh).filter((d) => d.id !== currentId)
    const next = queue.find((d) => current && d.upload_order > current.upload_order) ?? queue[0] ?? null
    setSelectedId(next ? next.id : currentId)
  }

  return (
    <div className="grid grid-cols-[320px_minmax(0,1fr)_minmax(0,1fr)] gap-5 h-full min-h-0">
      <div className="flex flex-col min-h-0">
        <div className="mb-3">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".jpg,.jpeg,.png,.pdf"
            onChange={(e) => handleFiles(e.target.files)}
            className="hidden"
            id="doc-upload-input"
          />
          <div className="flex gap-2">
            <label
              htmlFor="doc-upload-input"
              className="inline-block bg-neutral-800 hover:bg-neutral-700 text-sm text-white px-4 py-2 rounded cursor-pointer"
            >
              {uploading ? 'Uploading…' : 'Upload Documents'}
            </label>
            <button
              onClick={handleManualEntry}
              className="bg-neutral-900 hover:bg-neutral-800 border border-neutral-700 text-sm text-neutral-300 px-4 py-2 rounded"
            >
              + Manual Entry
            </button>
            {documents.some((d) => d.has_file) && (
              <button
                onClick={() => setConfirmRereadAll(true)}
                title="Start the analysis over: read every document again and review it fresh"
                className="text-sm text-neutral-400 hover:text-white px-2"
              >
                ↻ Re-read all…
              </button>
            )}
          </div>
          <p className="text-neutral-500 text-xs mt-1">
            JPG / PNG / PDF, processed one at a time via AI vision — or add a manual entry for anything without a scanned source.
          </p>
        </div>

        {error && <p className="text-red-400 text-sm mb-2">{error}</p>}

        {confirmRereadAll && (
          <div className="border border-red-900 bg-red-950/30 rounded p-3 mb-3 space-y-2">
            <p className="text-sm font-medium text-white">Start the analysis over?</p>
            <ul className="text-xs text-neutral-300 list-disc pl-4 space-y-0.5">
              <li>All {documents.filter((d) => d.has_file).length} uploaded files are <b>kept</b> and read again from scratch by the selected AI engine.</li>
              <li>Cleared: every name, date and payment read so far, all actors except the subject, the timeline, network links and flags.</li>
              <li>Kept: the subject profile, case notes and the watchlist. Manual entries keep their content but must be committed again.</li>
              <li>Each document then needs your review and <b>Commit to Case</b> again. Reading takes roughly {Math.max(1, Math.round((documents.filter((d) => d.has_file).length) * 13 / 60))} minute(s); with a cloud engine there is a small cost per page.</li>
            </ul>
            <div className="flex gap-2 pt-1">
              <button
                disabled={rereading}
                onClick={async () => {
                  setRereading(true)
                  setError(null)
                  try {
                    await api.rereadAllDocuments(caseId)
                    setConfirmRereadAll(false)
                    await refresh()
                    setRefreshToken((v) => v + 1)
                    onCommitted()
                  } catch (err) {
                    setError(err instanceof ApiError ? err.message : 'Could not start re-reading.')
                  } finally {
                    setRereading(false)
                  }
                }}
                className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm px-4 py-1.5 rounded"
              >
                {rereading ? 'Starting…' : 'Clear and re-read everything'}
              </button>
              <button onClick={() => setConfirmRereadAll(false)} className="text-sm text-neutral-400 hover:text-white px-3">Cancel</button>
            </div>
          </div>
        )}

        <DuplicateDocumentsPanel caseId={caseId} refreshToken={refreshToken} onResolved={() => { refresh(); setRefreshToken((v) => v + 1) }} />

        <div className="flex items-center justify-between mb-1.5">
          <button onClick={() => { setBulkMode((v) => !v); setSelectedForBulk(new Set()) }} className="text-xs text-neutral-500 hover:text-neutral-300">
            {bulkMode ? 'Cancel select' : 'Select multiple'}
          </button>
          {bulkMode && selectedForBulk.size > 0 && (
            <button onClick={handleBulkDelete} className="text-xs text-red-400 hover:text-red-300">
              Delete {selectedForBulk.size} selected
            </button>
          )}
        </div>

        <div className="flex-1 overflow-y-auto space-y-1 border border-neutral-800 rounded p-2 min-h-0">
          {documents.length === 0 && <p className="text-neutral-600 text-sm p-2">No documents uploaded yet.</p>}
          {documents.map((doc) => (
            <div
              key={doc.id}
              onClick={() => (bulkMode ? toggleBulk(doc.id) : setSelectedId(doc.id))}
              className={`w-full text-left px-2 py-2 rounded flex items-center gap-2 cursor-pointer ${
                selectedId === doc.id && !bulkMode ? 'bg-neutral-800' : 'hover:bg-neutral-900'
              }`}
            >
              {bulkMode && (
                <input type="checkbox" checked={selectedForBulk.has(doc.id)} onChange={() => toggleBulk(doc.id)} onClick={(e) => e.stopPropagation()} />
              )}
              <Thumbnail caseId={caseId} doc={doc} />
              <div className="min-w-0 flex-1">
                <div className="text-sm text-neutral-200 truncate">{doc.filename}</div>
                {doc.error_message && <div className="text-xs text-red-400 truncate">{doc.error_message}</div>}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <StatusBadge status={doc.status} />
                {!bulkMode && (
                  <span
                    onClick={(e) => handleDelete(doc, e)}
                    className="text-neutral-600 hover:text-red-400 text-xs px-1"
                    title="Delete document"
                  >
                    ✕
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="border border-neutral-800 rounded overflow-hidden min-h-0">
        {selectedDoc ? (
          <ImagePreview
            key={selectedDoc.id}
            caseId={caseId}
            document={selectedDoc}
            onRotated={refresh}
            page={pdfPage?.docId === selectedDoc.id ? pdfPage.page : null}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-neutral-600 text-sm">No document selected</div>
        )}
      </div>

      <div className="border border-neutral-800 rounded p-4 overflow-y-auto min-h-0">
        {selectedDoc ? (
          <ReviewPanel
            key={selectedDoc.id}
            caseId={caseId}
            document={selectedDoc}
            onShowPage={(page) => setPdfPage({ docId: selectedDoc.id, page })}
            onReextracted={refresh}
            onCommitted={async () => {
              await refresh()
              onCommitted()
            }}
            onCommitAndNext={() => commitAndNext(selectedDoc.id)}
            reviewRemaining={reviewRemaining}
          />
        ) : (
          <p className="text-neutral-600 text-sm">Select a document to review its extraction.</p>
        )}
      </div>
    </div>
  )
}

function isPdf(filename: string): boolean {
  return filename.toLowerCase().endsWith('.pdf')
}

function Thumbnail({ caseId, doc }: { caseId: string; doc: DocumentOut }) {
  const [failed, setFailed] = useState(false)
  if (!doc.has_file || failed) {
    return (
      <div className="w-9 h-9 rounded bg-neutral-800 shrink-0 flex items-center justify-center text-neutral-600 text-[9px]">
        {doc.has_file ? (isPdf(doc.filename) ? 'PDF' : '—') : '✎'}
      </div>
    )
  }
  return (
    <img
      src={api.documentFileUrl(caseId, doc.id)}
      onError={() => setFailed(true)}
      className="w-9 h-9 rounded object-cover shrink-0 border border-neutral-700"
      alt=""
    />
  )
}

const MIN_ZOOM = 0.05
const MAX_ZOOM = 4
const ZOOM_STEP = 1.25
const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z))

function ImagePreview({
  caseId,
  document,
  onRotated,
  page,
}: {
  caseId: string
  document: DocumentOut
  onRotated: () => void
  page: number | null
}) {
  // Zoom is relative to the image's real pixel size. The viewer opens in
  // "fit" mode (whole page visible) and stays fitted as the panel resizes,
  // until the user zooms manually.
  const [zoom, setZoom] = useState(1)
  const [fitMode, setFitMode] = useState(true)
  const [natural, setNatural] = useState<{ w: number; h: number } | null>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const [rotating, setRotating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [cacheBust, setCacheBust] = useState(0)

  const computeFit = useCallback(() => {
    const viewport = viewportRef.current
    if (!natural || !viewport) return 1
    const pad = 16
    return clampZoom(Math.min((viewport.clientWidth - pad) / natural.w, (viewport.clientHeight - pad) / natural.h))
  }, [natural])

  useEffect(() => {
    if (!fitMode || !natural) return
    const viewport = viewportRef.current
    if (!viewport) return
    // observe() fires once immediately, which applies the initial fit.
    const observer = new ResizeObserver(() => setZoom(computeFit()))
    observer.observe(viewport)
    return () => observer.disconnect()
  }, [fitMode, natural, computeFit])

  const zoomBy = useCallback((factor: number) => {
    setFitMode(false)
    setZoom((z) => clampZoom(z * factor))
  }, [])

  // Ctrl + mouse wheel zoom. Registered natively because React's wheel
  // listener is passive and can't stop the page from scrolling instead.
  useEffect(() => {
    const viewport = viewportRef.current
    if (!viewport) return
    function onWheel(e: WheelEvent) {
      if (!e.ctrlKey) return
      e.preventDefault()
      zoomBy(e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP)
    }
    viewport.addEventListener('wheel', onWheel, { passive: false })
    return () => viewport.removeEventListener('wheel', onWheel)
  }, [zoomBy, document.id])

  async function handleRotate() {
    setRotating(true)
    setError(null)
    try {
      await api.rotateDocument(caseId, document.id, 90)
      setFitMode(true)
      setCacheBust((v) => v + 1)
      onRotated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Rotate failed.')
    } finally {
      setRotating(false)
    }
  }

  if (!document.has_file) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-2 text-neutral-600 bg-neutral-950 px-6 text-center">
        <span className="text-2xl">✎</span>
        <p className="text-sm">Manual entry — no scanned file attached.</p>
      </div>
    )
  }

  if (isPdf(document.filename)) {
    return (
      <div className="h-full flex flex-col">
        <div className="px-3 py-2 border-b border-neutral-800 bg-neutral-950 text-xs text-neutral-400 flex justify-between gap-2">
          <span className="truncate">{document.filename}</span>
          {page && <span className="text-neutral-500 shrink-0">Page {page}</span>}
        </div>
        {/* Keyed on page so the viewer actually navigates: changing only
            the #page fragment of an already-loaded PDF iframe is ignored. */}
        <iframe
          key={page ?? 0}
          src={`${api.documentFileUrl(caseId, document.id)}${page ? `#page=${page}` : ''}`}
          className="flex-1 w-full bg-neutral-100"
          title={document.filename}
        />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between gap-2 px-3 py-2 border-b border-neutral-800 bg-neutral-950">
        <div className="flex items-center gap-2">
          <button onClick={() => zoomBy(1 / ZOOM_STEP)} disabled={zoom <= MIN_ZOOM} title="Zoom out (Ctrl + wheel)" className="text-xs text-neutral-400 hover:text-white disabled:opacity-40 px-1.5">−</button>
          <span className="text-xs text-neutral-500 w-10 text-center">{Math.round(zoom * 100)}%</span>
          <button onClick={() => zoomBy(ZOOM_STEP)} disabled={zoom >= MAX_ZOOM} title="Zoom in (Ctrl + wheel)" className="text-xs text-neutral-400 hover:text-white disabled:opacity-40 px-1.5">+</button>
          <button
            onClick={() => setFitMode(true)}
            title="Fit the whole page in the panel"
            className={`text-xs ml-1 ${fitMode ? 'text-white' : 'text-neutral-500 hover:text-neutral-300'}`}
          >
            Fit
          </button>
          <button
            onClick={() => {
              setFitMode(false)
              setZoom(1)
            }}
            title="Actual size"
            className="text-xs text-neutral-500 hover:text-neutral-300"
          >
            100%
          </button>
        </div>
        <button
          onClick={handleRotate}
          disabled={document.committed || rotating}
          title={document.committed ? 'Reopen (Edit) the document before rotating it' : 'Rotate 90° clockwise'}
          className="text-xs text-neutral-400 hover:text-white disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1"
        >
          ⟳ Rotate
        </button>
      </div>
      {error && <p className="text-red-400 text-xs px-3 py-1">{error}</p>}
      {/* The image is sized for real (not CSS-transformed), so the scroll
          area matches it and every edge stays reachable when zoomed in; the
          min-size grid keeps it centered when it's smaller than the panel. */}
      <div ref={viewportRef} className="flex-1 min-h-0 overflow-auto bg-black">
        <div className="min-w-full min-h-full w-max grid place-items-center p-2">
          <img
            src={`${api.documentFileUrl(caseId, document.id)}?v=${cacheBust}`}
            onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            style={natural ? { width: natural.w * zoom, height: natural.h * zoom } : { visibility: 'hidden' }}
            className="max-w-none"
            alt={document.filename}
          />
        </div>
      </div>
    </div>
  )
}

function DuplicateDocumentsPanel({
  caseId,
  refreshToken,
  onResolved,
}: {
  caseId: string
  refreshToken: number
  onResolved: () => void
}) {
  const [suggestions, setSuggestions] = useState<DuplicateDocumentSuggestion[] | null>(null)
  // "Not duplicates" decisions are remembered per case across restarts.
  const dismissedKey = `redthread:not-duplicates:${caseId}`
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem(dismissedKey) ?? '[]') as string[]) } catch { return new Set() }
  })
  const [comparing, setComparing] = useState<DuplicateDocumentSuggestion | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cleaning, setCleaning] = useState(false)

  useEffect(() => {
    api.getDuplicateDocuments(caseId)
      .then(setSuggestions)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to check for duplicate documents.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId, refreshToken])

  const pairKey = (s: DuplicateDocumentSuggestion) => `${s.document_a.id}:${s.document_b.id}`
  const visible = (suggestions ?? []).filter((s) => !dismissed.has(pairKey(s)))
  const exactCount = visible.filter((s) => s.distance === 0).length
  const fuzzy = visible.filter((s) => s.distance > 0)

  function markNotDuplicates(s: DuplicateDocumentSuggestion) {
    setDismissed((prev) => {
      const next = new Set(prev).add(pairKey(s))
      try { localStorage.setItem(dismissedKey, JSON.stringify([...next])) } catch { /* per-viewer convenience only */ }
      return next
    })
  }

  async function discardDocument(discard: string) {
    try {
      await api.deleteDocument(caseId, discard)
      setSuggestions((prev) => (prev ?? []).filter((s) => s.document_a.id !== discard && s.document_b.id !== discard))
      setComparing(null)
      onResolved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed.')
    }
  }

  async function handleCleanExact() {
    if (!confirm(`Delete the extra copies of ${exactCount} exact-duplicate photo(s), keeping the earliest upload of each? This cannot be undone.`)) return
    setCleaning(true)
    setError(null)
    try {
      await api.cleanExactDuplicateDocuments(caseId)
      const fresh = await api.getDuplicateDocuments(caseId)
      setSuggestions(fresh)
      onResolved()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Cleanup failed.')
    } finally {
      setCleaning(false)
    }
  }

  if (error) return <p className="text-red-400 text-xs mb-2">{error}</p>
  if (!suggestions || visible.length === 0) return null

  return (
    <div className="border border-amber-800 bg-amber-950/20 rounded p-2.5 mb-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-amber-200">
          Possible duplicate photos ({visible.length})
        </p>
        {exactCount > 0 && (
          <button
            onClick={handleCleanExact}
            disabled={cleaning}
            className="text-xs text-emerald-400 hover:text-emerald-300 disabled:opacity-50 shrink-0"
          >
            {cleaning ? 'Cleaning…' : `Clean up ${exactCount} exact duplicate(s)`}
          </button>
        )}
      </div>
      <p className="text-xs text-neutral-500">
        {exactCount > 0
          ? `${exactCount} are pixel-identical re-uploads (safe to bulk-remove). ${fuzzy.length} others look similar but need a quick look.`
          : 'These look like the same physical page, photographed more than once.'}
      </p>
      {comparing && (
        <DuplicateCompare
          caseId={caseId}
          pair={comparing}
          onDelete={discardDocument}
          onNotDuplicates={() => { markNotDuplicates(comparing); setComparing(null) }}
          onClose={() => setComparing(null)}
        />
      )}
      <div className="space-y-1.5 max-h-64 overflow-y-auto">
        {fuzzy.map((s) => (
          <div key={pairKey(s)} className="flex items-center gap-2 bg-neutral-900 border border-neutral-800 rounded px-2 py-1.5">
            <button onClick={() => setComparing(s)} title="Compare side by side" className="flex gap-1 shrink-0">
              <img src={api.documentFileUrl(caseId, s.document_a.id)} className="w-8 h-8 rounded object-cover" alt="" />
              <img src={api.documentFileUrl(caseId, s.document_b.id)} className="w-8 h-8 rounded object-cover" alt="" />
            </button>
            <div className="min-w-0 flex-1 text-xs text-neutral-400 truncate">
              {s.document_a.filename} / {s.document_b.filename}
            </div>
            <button onClick={() => setComparing(s)} className="text-xs text-emerald-400 hover:text-emerald-300 shrink-0">
              Compare…
            </button>
            <button onClick={() => markNotDuplicates(s)} className="text-xs text-neutral-500 hover:text-neutral-300 shrink-0">
              Not dupes
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function ReviewPanel({
  caseId,
  document,
  onCommitted,
  onShowPage,
  onReextracted,
  onCommitAndNext,
  reviewRemaining,
}: {
  caseId: string
  document: DocumentOut
  onCommitted: () => void
  onShowPage: (page: number) => void
  onReextracted: () => void
  onCommitAndNext: () => void
  reviewRemaining: number
}) {
  const source = document.edited_extraction ?? document.raw_extraction
  const [draft, setDraft] = useState<ExtractionResult>(
    source ?? { doc_type: '', names: [], dates: [], financial_transactions: [], legal_references: [], raw_text_notes: '', parse_warning: null },
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmReextract, setConfirmReextract] = useState(false)
  const pageTag = (page?: number | null) =>
    page ? <PageTag page={page} onClick={isPdf(document.filename) ? () => onShowPage(page) : undefined} /> : null

  if (document.status === 'pending' || document.status === 'processing') {
    return <p className="text-neutral-400 text-sm">AI extraction in progress…</p>
  }
  // AI extraction failed outright (no API key, network down, etc.) — rather
  // than a dead end, fall through to the same editable form used for manual
  // entries, with the failure reason shown as context.
  const extractionFailedMessage =
    document.status === 'error' && !document.raw_extraction
      ? document.error_message ?? 'AI extraction failed.'
      : null

  async function handleCommit(goToNext = false) {
    setSaving(true)
    setError(null)
    try {
      await api.commitDocument(caseId, document.id, draft)
      if (goToNext) onCommitAndNext()
      else onCommitted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to commit document.')
    } finally {
      setSaving(false)
    }
  }

  async function handleReextract() {
    if (!confirmReextract) {
      setConfirmReextract(true)
      return
    }
    setSaving(true)
    setError(null)
    try {
      await api.reextractDocument(caseId, document.id)
      onReextracted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to re-run extraction.')
    } finally {
      setSaving(false)
      setConfirmReextract(false)
    }
  }

  async function handleUncommit() {
    setSaving(true)
    setError(null)
    try {
      await api.uncommitDocument(caseId, document.id)
      onCommitted()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to reopen document for editing.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      {document.has_file && !document.committed && (
        <div className="flex justify-end">
          <button
            onClick={handleReextract}
            disabled={saving}
            title="Read the document with AI again. Replaces the current unreviewed fields."
            className="text-xs text-neutral-400 hover:text-white disabled:opacity-40"
          >
            {confirmReextract ? 'Replace current fields? Click again to confirm' : '↻ Re-run AI extraction'}
          </button>
        </div>
      )}
      {extractionFailedMessage && (
        <p className="text-amber-400 text-xs bg-amber-900/20 border border-amber-800 rounded px-2 py-1">
          AI extraction couldn't run for this document ({extractionFailedMessage}) — fill in the fields below by hand.
        </p>
      )}
      {!document.has_file && !extractionFailedMessage && (
        <p className="text-neutral-500 text-xs bg-neutral-900 border border-neutral-800 rounded px-2 py-1">
          Manual entry — no scanned source. Fill in whatever applies.
        </p>
      )}
      {draft.extracted_by && (
        <p className="text-neutral-500 text-[11px]">Read by {draft.extracted_by.replace(/:/g, ' · ')}</p>
      )}
      {draft.parse_warning && (
        <p className="text-yellow-400 text-xs bg-yellow-900/20 border border-yellow-800 rounded px-2 py-1">
          {draft.parse_warning}
        </p>
      )}

      <div>
        <label className="block text-xs text-neutral-400 mb-1">Document Type</label>
        <input
          value={draft.doc_type ?? ''}
          onChange={(e) => setDraft({ ...draft, doc_type: e.target.value })}
          className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
          disabled={document.committed}
        />
      </div>

      <EditableList
        title="Names"
        items={draft.names}
        disabled={document.committed}
        onChange={(names) => setDraft({ ...draft, names })}
        renderRow={(item, update, remove) => (
          <div className="flex gap-2">
            <input
              value={item.name}
              onChange={(e) => update({ ...item, name: e.target.value })}
              placeholder="Name"
              className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              disabled={document.committed}
            />
            <input
              value={item.role ?? ''}
              onChange={(e) => update({ ...item, role: e.target.value })}
              placeholder="Role"
              className="flex-1 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              disabled={document.committed}
            />
            {pageTag(item.page)}
            {!document.committed && <RemoveButton onClick={remove} />}
          </div>
        )}
        onAdd={() => setDraft({ ...draft, names: [...draft.names, { name: '', role: null }] })}
      />

      <EditableList
        title="Dates"
        items={draft.dates}
        disabled={document.committed}
        onChange={(dates) => setDraft({ ...draft, dates })}
        renderRow={(item, update, remove) => (
          <div>
          <div className="flex gap-2">
            <select
              value={item.label}
              onChange={(e) => update({ ...item, label: e.target.value })}
              className="bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              disabled={document.committed}
            >
              {['birth', 'petition_filed', 'decree_issued', 'payment', 'document_date', 'other', 'unlabeled'].map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
            <input
              type="date"
              value={item.date ?? ''}
              // Editing the date means the reviewer has checked it, so the
              // ambiguity note no longer applies; the original wording stays.
              onChange={(e) => update({ ...item, date: e.target.value || null, note: null })}
              className={`flex-1 bg-neutral-900 border rounded px-2 py-1 text-sm text-white ${
                item.note ? 'border-amber-700' : 'border-neutral-700'
              }`}
              disabled={document.committed}
            />
            {pageTag(item.page)}
            {!document.committed && <RemoveButton onClick={remove} />}
          </div>
          {(item.raw || item.note) && (
            <div className="mt-0.5 pl-1 text-[11px] leading-snug">
              {item.raw && <span className="text-neutral-500">As written: “{item.raw}”</span>}
              {item.note && <span className="block text-amber-400">{item.note}</span>}
            </div>
          )}
          </div>
        )}
        onAdd={() => setDraft({ ...draft, dates: [...draft.dates, { label: 'other', date: null }] })}
      />

      <EditableList
        title="Financial Transactions"
        items={draft.financial_transactions}
        disabled={document.committed}
        onChange={(financial_transactions) => setDraft({ ...draft, financial_transactions })}
        renderRow={(item, update, remove) => (
          <div className="flex gap-2 flex-wrap">
            <input
              value={item.amount ?? ''}
              onChange={(e) => update({ ...item, amount: e.target.value })}
              placeholder="Amount"
              className="w-24 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              disabled={document.committed}
            />
            <input
              value={item.currency ?? ''}
              onChange={(e) => update({ ...item, currency: e.target.value })}
              placeholder="Currency"
              className="w-20 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              disabled={document.committed}
            />
            <input
              value={item.description ?? ''}
              onChange={(e) => update({ ...item, description: e.target.value })}
              placeholder="Description"
              className="flex-1 min-w-32 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              disabled={document.committed}
            />
            <input
              value={item.linked_case_number ?? ''}
              onChange={(e) => update({ ...item, linked_case_number: e.target.value })}
              placeholder="Linked case #"
              className="w-28 bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
              disabled={document.committed}
            />
            {pageTag(item.page)}
            {!document.committed && <RemoveButton onClick={remove} />}
          </div>
        )}
        onAdd={() =>
          setDraft({
            ...draft,
            financial_transactions: [...draft.financial_transactions, { amount: null, currency: null, description: null, linked_case_number: null }],
          })
        }
      />

      <div>
        <label className="block text-xs text-neutral-400 mb-1">Legal References (comma-separated)</label>
        <input
          value={draft.legal_references.join(', ')}
          onChange={(e) =>
            setDraft({ ...draft, legal_references: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })
          }
          className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
          disabled={document.committed}
        />
      </div>

      <div>
        <label className="block text-xs text-neutral-400 mb-1">Notes</label>
        <textarea
          value={draft.raw_text_notes ?? ''}
          onChange={(e) => setDraft({ ...draft, raw_text_notes: e.target.value })}
          rows={2}
          className="w-full bg-neutral-900 border border-neutral-700 rounded px-2 py-1 text-sm text-white"
          disabled={document.committed}
        />
      </div>

      {error && <p className="text-red-400 text-sm">{error}</p>}

      {document.committed ? (
        <div className="flex items-center gap-3">
          <p className="text-emerald-400 text-sm">Committed to case.</p>
          <button
            onClick={handleUncommit}
            disabled={saving}
            className="text-xs text-neutral-400 hover:text-white disabled:opacity-50"
          >
            {saving ? 'Reopening…' : 'Edit'}
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-3 flex-wrap">
          <button
            onClick={() => handleCommit(true)}
            disabled={saving}
            title="Commit this document and open the next one waiting for review"
            className="bg-red-700 hover:bg-red-600 disabled:opacity-50 text-white text-sm font-medium px-4 py-2 rounded"
          >
            {saving ? 'Committing…' : 'Commit & next →'}
          </button>
          <button
            onClick={() => handleCommit(false)}
            disabled={saving}
            className="text-sm text-neutral-300 hover:text-white border border-neutral-700 px-3 py-2 rounded disabled:opacity-50"
          >
            Commit to Case
          </button>
          <span className="text-xs text-neutral-500">{reviewRemaining} awaiting review</span>
        </div>
      )}
    </div>
  )
}

function EditableList<T>({
  title,
  items,
  disabled,
  onChange,
  renderRow,
  onAdd,
}: {
  title: string
  items: T[]
  disabled: boolean
  onChange: (items: T[]) => void
  renderRow: (item: T, update: (next: T) => void, remove: () => void) => React.ReactNode
  onAdd: () => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="block text-xs text-neutral-400">{title}</label>
        {!disabled && (
          <button onClick={onAdd} className="text-xs text-red-400 hover:text-red-300">
            + Add
          </button>
        )}
      </div>
      <div className="space-y-1">
        {items.length === 0 && <p className="text-neutral-600 text-xs">None extracted.</p>}
        {items.map((item, idx) => (
          <div key={idx}>
            {renderRow(
              item,
              (next) => {
                const copy = [...items]
                copy[idx] = next
                onChange(copy)
              },
              () => onChange(items.filter((_, i) => i !== idx)),
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function PageTag({ page, onClick }: { page: number; onClick?: () => void }) {
  const className = 'shrink-0 self-center text-[10px] px-1.5 py-0.5 rounded border border-neutral-700 text-neutral-400'
  return onClick ? (
    <button onClick={onClick} title={`Show page ${page} in the viewer`} className={`${className} hover:text-white hover:border-neutral-500`}>
      p.{page}
    </button>
  ) : (
    <span className={className}>p.{page}</span>
  )
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return (
    <button onClick={onClick} className="text-neutral-500 hover:text-red-400 text-sm px-1">
      ✕
    </button>
  )
}
