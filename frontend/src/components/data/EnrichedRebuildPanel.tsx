import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button, NumberInput } from '@mantine/core'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { usePreferences } from '@/lib/useSharedQueries'

type Props = {
  isRunning: boolean
  onStart: (jobId: string) => void
  purpose?: 'enriched' | 'turnover'
  historicalShareRows?: number
}

export function EnrichedRebuildPanel({
  isRunning,
  onStart,
  purpose = 'enriched',
  historicalShareRows = 0,
}: Props) {
  const qc = useQueryClient()
  const prefs = usePreferences()
  const batchSize = prefs.data?.enriched_batch_size ?? 1000
  const isTurnoverRebuild = purpose === 'turnover'
  const canRebuild = !isTurnoverRebuild || historicalShareRows > 0
  const [editing, setEditing] = useState(false)
  const [draftSize, setDraftSize] = useState(String(batchSize))
  const [hint, setHint] = useState<string | null>(null)

  function clampAndSave(raw: number) {
    if (isNaN(raw) || 1 > raw) { setHint('已自动设为最小值 1'); saveBatch.mutate(1); return }
    if (raw > 10000) { setHint('已自动设为上限 10000'); saveBatch.mutate(10000); return }
    setHint(null); saveBatch.mutate(raw)
  }

  const saveBatch = useMutation({
    mutationFn: (size: number) => api.updateEnrichedBatchSize(size),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.preferences })
      setEditing(false)
    },
  })
  const rebuild = useMutation({
    mutationFn: api.rebuildEnriched,
    onSuccess: ({ job_id }) => {
      onStart(job_id)
      qc.invalidateQueries({ queryKey: QK.pipelineJobs })
    },
  })

  return (
    <div className="px-4 pb-4 pt-3 border-t border-accent/20 space-y-4">
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <div className="text-xs font-medium text-foreground">批次大小</div>
            <div className="text-[10px] text-muted">每批计算的标的数量，影响内存占用与进度粒度</div>
          </div>
          {editing ? (
            <div className="flex items-center gap-1.5">
              <NumberInput
                size="xs"
                w={80}
                value={draftSize}
                onChange={v => setDraftSize(String(v))}
                min={1}
                max={10000}
                autoFocus
                hideControls
                onKeyDown={e => {
                  if (e.key === 'Enter') clampAndSave(parseInt(draftSize))
                  if (e.key === 'Escape') { setEditing(false); setHint(null) }
                }}
                classNames={{ input: 'rounded-btn bg-surface border-border font-mono text-right tabular-nums' }}
              />
              <Button
                size="compact-xs"
                variant="light"
                onClick={() => clampAndSave(parseInt(draftSize))}
                loading={saveBatch.isPending}
              >
                保存
              </Button>
              <Button
                size="compact-xs"
                variant="subtle"
                color="gray"
                onClick={() => setEditing(false)}
              >
                取消
              </Button>
            </div>
          ) : (
            <Button
              size="compact-xs"
              variant="default"
              onClick={() => { setDraftSize(String(batchSize)); setEditing(true) }}
              className="font-mono tabular-nums"
            >
              {batchSize} 只/批
            </Button>
          )}
        </div>
        <div className="flex items-start gap-1.5 px-3 py-1.5 rounded-btn bg-warning/10 border border-warning/20">
          <span className="text-[10px] text-warning leading-relaxed">
            每批内存占用 = 批次大小 × 日K历史天数。批次越大或日K历史越长，内存占用越高，可能导致程序崩溃。内存不足时请适当降低此值。
          </span>
        </div>
        {hint && (
          <div className="px-3 py-1 rounded-btn bg-accent/10 border border-accent/20 text-[10px] text-accent">
            {hint}
          </div>
        )}
      </div>

      <div>
        {isTurnoverRebuild && (
          <div className={`mb-3 rounded-btn border px-3 py-2 text-[10px] leading-relaxed ${
            canRebuild
              ? 'border-accent/20 bg-accent/5 text-secondary'
              : 'border-warning/20 bg-warning/10 text-warning'
          }`}>
            {canRebuild
              ? `已检测到 ${historicalShareRows.toLocaleString()} 条历史股本记录。重算会按公告可用日匹配历史流通股本，并覆盖全部 Enriched 分区。`
              : '未检测到历史股本数据，请先在财务分析页面同步“股本表”，再执行重算。'}
          </div>
        )}
        <div className="text-[10px] text-muted mb-2">
          {isTurnoverRebuild
            ? '为保证数据一致性，将基于现有日 K、除权因子和历史股本重新生成 Enriched；其他指标也会按当前逻辑同步更新。'
            : '基于已有 kline_daily + adj_factor 全量计算前复权 + 技术指标 + 信号'}
        </div>
        <Button
          fullWidth
          size="xs"
          onClick={() => rebuild.mutate()}
          disabled={!canRebuild || isRunning}
          loading={rebuild.isPending}
        >
          {rebuild.isPending ? '计算中…' : isTurnoverRebuild ? '重新计算并覆盖' : '全量计算'}
        </Button>
        {rebuild.isError && (
          <div className="mt-2 text-[10px] text-danger">
            启动失败：{String((rebuild.error as Error)?.message ?? rebuild.error)}
          </div>
        )}
      </div>
    </div>
  )
}
