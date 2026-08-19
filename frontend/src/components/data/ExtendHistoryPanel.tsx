import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Badge, Button, NumberInput, SegmentedControl } from '@mantine/core'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'

export function ExtendHistoryPanel({ caps, isRunning, earliestDate, onStart }: {
  caps: { label: string; capabilities: Record<string, { rpm: number | null; batch: number | null; subscribe: number | null }> } | undefined
  isRunning: boolean
  earliestDate: string | null
  onStart: () => void
}) {
  const qc = useQueryClient()
  const [value, setValue] = useState(6)
  const [unit, setUnit] = useState<'month' | 'year'>('month')
  const hasBatchCap = !!caps?.capabilities?.['kline.daily.batch']

  const extend = useMutation({
    mutationFn: () => api.extendHistory(value, unit),
    onSuccess: () => {
      onStart()
      qc.invalidateQueries({ queryKey: QK.pipelineJobs })
    },
  })

  const offsetDays = unit === 'month' ? value * 30 : value * 365
  const estimate = earliestDate
    ? (() => {
        const d = new Date(earliestDate)
        d.setDate(d.getDate() - offsetDays)
        return d.toISOString().slice(0, 10)
      })()
    : null

  const maxValue = unit === 'year' ? 10 : 36

  return (
    <div className="px-4 pb-4 pt-3 border-t border-accent/20 space-y-3">
      <div className="text-[10px] text-secondary">向前扩展历史数据</div>

      <div className="flex items-center gap-2">
        <NumberInput
          size="xs"
          w={72}
          min={1}
          max={maxValue}
          value={value}
          disabled={!hasBatchCap || isRunning}
          onChange={v => setValue(Math.max(1, Math.min(maxValue, Number(v) || 1)))}
          classNames={{ input: 'rounded-btn font-mono tabular-nums' }}
        />

        <SegmentedControl
          size="xs"
          value={unit}
          disabled={!hasBatchCap || isRunning}
          onChange={u => {
            const next = u as 'month' | 'year'
            setUnit(next)
            if (next === 'year' && value > 10) setValue(1)
            if (next === 'month' && value > 36) setValue(6)
          }}
          data={[
            { label: '月', value: 'month' },
            { label: '年', value: 'year' },
          ]}
        />
      </div>

      {estimate && (
        <div className="text-[10px] text-muted">
          预计扩展至 <span className="font-mono text-secondary">{estimate}</span>
          {earliestDate && <span> (当前最早: <span className="font-mono text-secondary">{earliestDate}</span>)</span>}
        </div>
      )}

      <Button
        fullWidth
        size="xs"
        onClick={() => extend.mutate()}
        disabled={!hasBatchCap || isRunning || !earliestDate}
        loading={extend.isPending}
      >
        {extend.isPending ? '请求中…' : '获取数据'}
      </Button>

      {!hasBatchCap && (
        <Badge size="xs" variant="light" className="h-auto min-h-0 px-1.5 py-px rounded text-[10px] leading-normal normal-case tracking-normal font-medium bg-warning/8 text-warning/80">
          需 Pro+ 权限
        </Badge>
      )}
    </div>
  )
}
