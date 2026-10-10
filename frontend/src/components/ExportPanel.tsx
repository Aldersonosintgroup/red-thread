import { api } from '../api/client'

export function ExportPanel({ caseId }: { caseId: string }) {
  return (
    <div className="space-y-4 max-w-md">
      <p className="text-neutral-400 text-sm">
        Export the full case file — subject profile, actors, timeline, discrepancies, flags, and
        score breakdown.
      </p>
      <div className="flex gap-3">
        <a
          href={api.exportPdfUrl(caseId)}
          className="bg-red-700 hover:bg-red-600 text-white text-sm font-medium px-4 py-2 rounded"
        >
          Download PDF Report
        </a>
        <a
          href={api.exportJsonUrl(caseId)}
          className="bg-neutral-800 hover:bg-neutral-700 text-white text-sm font-medium px-4 py-2 rounded"
        >
          Download JSON Export
        </a>
      </div>
    </div>
  )
}
