import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { DocumentOut, FlagOut } from '../types'

/** Normalize the ways a currency gets written into one key for totals.
 *  Unknown currencies are kept as written rather than guessed. */
export function currencyKey(raw: string | null | undefined): string {
  const t = (raw ?? '').trim().toLowerCase().replace(/\s+/g, ' ')
  if (!t) return 'unspecified'
  if (/^(usd|us\$|u\.s\.\$|us dollars?|dollars?|dólar(es)?|dolar(es)?|\$us)$/.test(t)) return 'USD'
  if (/^(clp|ch\$|\$ ?chilenos?|pesos?( chilenos?)?|chilean pesos?)$/.test(t)) return 'CLP'
  if (t === '$') return '$ (unspecified)'
  return raw!.trim().toUpperCase()
}

/** Parse an amount as written. Chilean documents write "2.500.000,50",
 *  US ones "2,500,000.50": the last separator followed by exactly 1-2
 *  digits is the decimal mark; groups of three are thousands. Returns null
 *  when the text isn't clearly a number, so it is never guessed. */
export function parseAmount(raw: string | null | undefined): number | null {
  if (!raw) return null
  const text = raw.replace(/[^\d.,]/g, '')
  if (!/\d/.test(text)) return null
  const lastSep = Math.max(text.lastIndexOf('.'), text.lastIndexOf(','))
  let integerPart = text
  let decimalPart = ''
  if (lastSep >= 0 && text.length - lastSep - 1 <= 2) {
    integerPart = text.slice(0, lastSep)
    decimalPart = text.slice(lastSep + 1)
  }
  const groups = integerPart.split(/[.,]/)
  if (groups.length > 1 && !groups.slice(1).every((g) => g.length === 3)) return null
  const value = Number(groups.join('') + (decimalPart ? `.${decimalPart}` : ''))
  return Number.isFinite(value) ? value : null
}

interface PaymentRow {
  key: string
  document: DocumentOut
  amountRaw: string | null
  amount: number | null
  currencyRaw: string | null
  currency: string
  description: string | null
  linkedCase: string | null
  page: number | null
  paymentDates: string[]
  flagged: boolean
}

const fmt = (n: number) => n.toLocaleString(undefined, { maximumFractionDigits: 2 })

export function FinancialPanel({ caseId, caseNumber }: { caseId: string; caseNumber: string }) {
  const [documents, setDocuments] = useState<DocumentOut[]>([])
  const [flags, setFlags] = useState<FlagOut[]>([])
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    Promise.all([api.listDocuments(caseId), api.getFlags(caseId)])
      .then(([docs, flagList]) => { setDocuments(docs); setFlags(flagList); setLoaded(true) })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load financial data.'))
  }, [caseId])

  const { rows, pendingPayments } = useMemo(() => {
    const flaggedDocs = new Set(flags.filter((f) => f.flag_type === 'FINANCIAL_ANOMALY').map((f) => f.related_document_id))
    const out: PaymentRow[] = []
    let pending = 0
    for (const doc of [...documents].sort((a, b) => a.upload_order - b.upload_order)) {
      const x = doc.edited_extraction ?? doc.raw_extraction
      if (!x) continue
      if (!doc.committed) {
        pending += x.financial_transactions.length
        continue
      }
      const paymentDates = x.dates.filter((d) => d.label === 'payment').map((d) => d.date ?? d.raw ?? '').filter(Boolean)
      x.financial_transactions.forEach((t, i) => {
        out.push({
          key: `${doc.id}:${i}`, document: doc, amountRaw: t.amount, amount: parseAmount(t.amount),
          currencyRaw: t.currency, currency: currencyKey(t.currency), description: t.description,
          linkedCase: t.linked_case_number, page: t.page ?? null, paymentDates, flagged: flaggedDocs.has(doc.id),
        })
      })
    }
    out.sort((a, b) => (a.paymentDates[0] ?? '9999').localeCompare(b.paymentDates[0] ?? '9999'))
    return { rows: out, pendingPayments: pending }
  }, [documents, flags])

  const totals = useMemo(() => {
    const byCurrency = new Map<string, { sum: number; count: number; unread: number }>()
    for (const r of rows) {
      const t = byCurrency.get(r.currency) ?? { sum: 0, count: 0, unread: 0 }
      if (r.amount == null) t.unread += 1
      else { t.sum += r.amount; t.count += 1 }
      byCurrency.set(r.currency, t)
    }
    return [...byCurrency.entries()].sort((a, b) => b[1].count - a[1].count)
  }, [rows])

  if (error) return <p className="text-red-400 text-sm">{error}</p>
  if (!loaded) return <p className="text-neutral-500 text-sm">Loading payments…</p>

  return (
    <div className="space-y-5 max-w-6xl">
      <p className="text-xs text-neutral-500">
        Every payment, fee or amount recorded in reviewed documents. Amounts are shown as written; totals are kept separate
        per currency, because historical pesos and dollars can't be honestly added together.
        {pendingPayments > 0 && <span className="text-amber-400"> {pendingPayments} more payment(s) appear in documents still awaiting review.</span>}
      </p>

      {rows.length === 0 ? (
        <p className="text-sm text-neutral-500">No payments in reviewed documents yet.</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-3">
            {totals.map(([currency, t]) => (
              <div key={currency} className="border border-neutral-800 rounded px-4 py-3 min-w-44">
                <div className="text-[11px] uppercase tracking-wide text-neutral-500">{currency}</div>
                <div className="text-xl font-semibold text-white">{t.count ? fmt(t.sum) : '—'}</div>
                <div className="text-xs text-neutral-500">
                  {t.count} payment{t.count === 1 ? '' : 's'}
                  {t.unread > 0 && <span className="text-amber-400"> · {t.unread} amount{t.unread === 1 ? '' : 's'} not readable as a number</span>}
                </div>
              </div>
            ))}
          </div>

          <div className="overflow-x-auto border border-neutral-800 rounded">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-neutral-500 border-b border-neutral-800">
                  <th className="px-3 py-2 font-medium">Payment date</th>
                  <th className="px-3 py-2 font-medium text-right">Amount</th>
                  <th className="px-3 py-2 font-medium">Currency</th>
                  <th className="px-3 py-2 font-medium">For</th>
                  <th className="px-3 py-2 font-medium">Case no. nearby</th>
                  <th className="px-3 py-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800">
                {rows.map((r) => {
                  const otherCase = r.linkedCase && r.linkedCase !== caseNumber && /\d/.test(r.linkedCase)
                  return (
                    <tr key={r.key} className={r.flagged ? 'bg-red-950/25' : ''}>
                      <td className="px-3 py-2 text-neutral-300 whitespace-nowrap">{r.paymentDates.join(', ') || <span className="text-neutral-600">not stated</span>}</td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <span className="text-white">{r.amountRaw ?? '—'}</span>
                        {r.amountRaw && r.amount == null && <div className="text-[10px] text-amber-400">not a clear number</div>}
                      </td>
                      <td className="px-3 py-2 text-neutral-300">{r.currencyRaw ?? <span className="text-neutral-600">—</span>}</td>
                      <td className="px-3 py-2 text-neutral-300">
                        {r.description ?? <span className="text-neutral-600">—</span>}
                        {r.flagged && <span className="ml-2 text-[10px] font-semibold px-1.5 py-0.5 rounded bg-red-900/60 text-red-200">FLAGGED</span>}
                      </td>
                      <td className={`px-3 py-2 whitespace-nowrap ${otherCase ? 'text-amber-300' : 'text-neutral-400'}`}
                        title={otherCase ? 'Differs from this case number' : undefined}>
                        {r.linkedCase ?? <span className="text-neutral-600">—</span>}
                      </td>
                      <td className="px-3 py-2 text-xs text-neutral-500 max-w-56 truncate" title={r.document.filename}>
                        {r.document.filename}{r.page ? ` · p.${r.page}` : ''}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-neutral-600">
            Highlighted rows come from documents that raised a financial-anomaly flag. A case number in amber differs from this case's own number.
          </p>
        </>
      )}
    </div>
  )
}
