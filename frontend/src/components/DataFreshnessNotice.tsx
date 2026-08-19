import { AlertCircle } from 'lucide-react'

export interface DataFreshnessInfo {
  snapshot_date?: string | null
  current_date?: string | null
  is_stale?: boolean
}

interface Props {
  freshness?: DataFreshnessInfo | null
  snapshotDate?: string | null
  currentDate?: string | null
  label?: string
}

function beijingToday(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date())
}

function latestWeekday(dateText: string): string {
  const value = new Date(`${dateText}T00:00:00Z`)
  while (value.getUTCDay() === 0 || value.getUTCDay() === 6) {
    value.setUTCDate(value.getUTCDate() - 1)
  }
  return value.toISOString().slice(0, 10)
}

/** Shared fail-closed warning for pages that render a known historical snapshot. */
export function DataFreshnessNotice({ freshness, snapshotDate, currentDate, label = '当前数据' }: Props) {
  const snapshot = (freshness?.snapshot_date ?? snapshotDate)?.slice(0, 10) || null
  const current = (freshness?.current_date ?? currentDate)?.slice(0, 10) || beijingToday()
  // Keep the UI fail-closed if an older backend omits or mislabels the
  // freshness flag: a weekday snapshot older than today's latest weekday is
  // still historical data and must be visible to the user.
  const staleByDate = snapshot ? snapshot < latestWeekday(beijingToday()) : false
  const stale = Boolean(freshness?.is_stale) || staleByDate
  if (!stale) return null

  const displaySnapshot = snapshot || '未知日期'
  const displayCurrent = current || '当前北京日期'

  return (
    <div
      role="status"
      className="mx-4 mt-3 flex items-start gap-1.5 rounded border border-sky-400/30 bg-sky-400/[0.08] px-2.5 py-2 text-[11px] leading-relaxed text-sky-700 dark:text-sky-200"
    >
      <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-sky-500 dark:text-sky-300" />
      <span>
        {label}停留在 <strong>{displaySnapshot}</strong>，当前北京日期为 <strong>{displayCurrent}</strong>。
        当前页面仅反映该历史快照，请在数据中心完成同步后再据此决策。
      </span>
    </div>
  )
}
