const SEVERITY_STYLES: Record<string, string> = {
  CRITICAL: 'bg-red-900/60 text-red-300 border-red-700',
  HIGH: 'bg-orange-900/60 text-orange-300 border-orange-700',
  MEDIUM: 'bg-yellow-900/50 text-yellow-300 border-yellow-700',
  LOW: 'bg-neutral-800 text-neutral-300 border-neutral-600',
}

export function SeverityBadge({ severity }: { severity: string }) {
  const style = SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.LOW
  return (
    <span className={`inline-block px-2 py-0.5 rounded border text-xs font-medium ${style}`}>
      {severity}
    </span>
  )
}

const CATEGORY_STYLES: Record<string, string> = {
  RED: 'bg-red-900/60 text-red-300 border-red-700',
  ORANGE: 'bg-orange-900/60 text-orange-300 border-orange-700',
  YELLOW: 'bg-yellow-900/50 text-yellow-300 border-yellow-700',
}

export function CategoryBadge({ category }: { category: string }) {
  const style = CATEGORY_STYLES[category] ?? 'bg-neutral-800 text-neutral-300 border-neutral-600'
  return (
    <span className={`inline-block px-2 py-0.5 rounded border text-xs font-medium ${style}`}>
      {category}
    </span>
  )
}

export function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    pending: 'bg-neutral-800 text-neutral-300 border-neutral-600',
    processing: 'bg-blue-900/50 text-blue-300 border-blue-700',
    extracted: 'bg-emerald-900/50 text-emerald-300 border-emerald-700',
    reviewed: 'bg-purple-900/50 text-purple-300 border-purple-700',
    error: 'bg-red-900/60 text-red-300 border-red-700',
  }
  return (
    <span className={`inline-block px-2 py-0.5 rounded border text-xs font-medium ${styles[status] ?? styles.pending}`}>
      {status}
    </span>
  )
}
