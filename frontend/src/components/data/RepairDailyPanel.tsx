import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Badge, Button } from '@mantine/core'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { DatePicker } from '@/components/DatePicker'

function pad(n: number) { return String(n).padStart(2, '0') }
function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
/** 往前推 N 天 */
function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function RepairDailyPanel({ caps, isRunning, latestDate, onStart }: {
  caps: { label: string; capabilities: Record<string, { rpm: number | null; batch: number | null; subscribe: number | null }> } | undefined
  isRunning: boolean
  latestDate: string | null
  onStart: () => void
}) {
  const qc = useQueryClient()
  const hasBatchCap = !!caps?.capabilities?.['kline.daily.batch']

  // 默认起始日期: 最新数据往前推 30 天 (兼顾补缺口 + 复核近期数据, 成本不高)
  const [startDate, setStartDate] = useState(daysAgo(30))

  const repair = useMutation({
    mutationFn: () => api.repairDaily(startDate),
    onSuccess: () => {
      onStart()
      qc.invalidateQueries({ queryKey: QK.pipelineJobs })
    },
  })

  const today = todayStr()
  const canSubmit = hasBatchCap && !isRunning && !repair.isPending && startDate <= today
  const gapDays = latestDate
    ? Math.max(0, Math.round((Date.parse(today) - Date.parse(latestDate)) / 86400000))
    : null

  return (
    <div className="space-y-3">
      <div className="rounded-card bg-accent/8 border border-accent/20 p-3 space-y-1.5">
        <div className="text-xs text-foreground">
          当数据出现缺口时(漏跑、停服),从这里重拉选定区间到今天的全部数据并重算。
        </div>
        <div className="text-[10px] text-muted leading-relaxed">
          完整复用盘后管道流程 (A股日K · 除权因子 · 指标重算 · 指数),新数据按 (个股, 日期) 覆盖旧值,不会重复,也无需先清除。
        </div>
      </div>

      {/* 起始日期 — 用户主要操作,放上面 */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-secondary">起始日期</span>
        <DatePicker
          value={startDate}
          onChange={setStartDate}
          max={today}
          align="right"
          buttonClassName="font-mono text-xs"
        />
      </div>

      {/* 本地最新数据 — 参考信息,放下面 */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted">本地最新数据</span>
        <span className="font-mono text-xs text-secondary">
          {latestDate ?? '—'}
          {gapDays !== null && gapDays > 0 && (
            <span className="ml-2 text-warning/90">已落后 {gapDays} 天</span>
          )}
        </span>
      </div>

      <div className="text-[10px] text-muted -mt-1">
        将重拉 <span className="font-mono text-secondary">{startDate}</span>
        {' → '}<span className="font-mono text-secondary">{today}</span>(今天) 的 A股日K · 除权 · 指数并重算指标
      </div>

      <Button
        fullWidth
        size="xs"
        onClick={() => repair.mutate()}
        disabled={!canSubmit}
        loading={repair.isPending}
      >
        {repair.isPending ? '请求中…' : '开始修正'}
      </Button>

      {!hasBatchCap && (
        <Badge size="xs" variant="light" fullWidth className="h-auto min-h-0 px-1.5 py-px rounded text-[10px] leading-normal normal-case tracking-normal font-medium bg-warning/8 text-warning/80">
          需 Pro+ 权限
        </Badge>
      )}
    </div>
  )
}
